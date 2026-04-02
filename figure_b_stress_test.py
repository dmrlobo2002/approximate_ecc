"""Figure B: DAG bitflip solver effectiveness vs flip count, hash size, and flip mode."""
from __future__ import annotations

import argparse
import math
import os
from typing import Any

from bitflip_solver import correct_with_dag
from grid_shuffle import bits_to_grid, grid_to_bits, source_index_to_grid_coord
from group_hash import build_hash_nodes
from hash_dag import build_hash_graph

from experiments.common import (
    agg,
    ensure_dir,
    parse_int_list,
    stable_key,
    stable_rng,
    write_csv,
    write_json,
)

DEFAULT_BIT_LENGTH = 256
DEFAULT_ROUNDS = 8
DEFAULT_ROW_GROUP = 2
DEFAULT_COL_GROUP = 2
DEFAULT_TAIL_POLICY = "include_partial"
DEFAULT_MAX_BER = 0.05
FLIP_MODES = ["random", "burst", "both"]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Figure B: DAG solver effectiveness vs flip count, hash size, and flip mode"
    )
    p.add_argument(
        "--hash-sizes",
        type=str,
        default="16,32",
        help="Comma-separated hash bit widths, e.g. '16' or '32' or '16,32'",
    )
    p.add_argument(
        "--flip-mode",
        choices=FLIP_MODES,
        default="both",
        help=(
            "'random' = uniformly random flip locations; "
            "'burst' = contiguous block in physical memory; "
            "'both' = run both and plot side by side"
        ),
    )
    p.add_argument("--bit-length", type=int, default=DEFAULT_BIT_LENGTH, help="Number of source bits L")
    p.add_argument(
        "--max-ber",
        type=float,
        default=DEFAULT_MAX_BER,
        help="Maximum bit error rate; sets the upper flip count to floor(max_ber * bit_length), e.g. 0.05 for 5%%",
    )
    p.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS, help="Feistel rounds")
    p.add_argument("--row-group-size", type=int, default=DEFAULT_ROW_GROUP, help="Row group size")
    p.add_argument("--col-group-size", type=int, default=DEFAULT_COL_GROUP, help="Col group size")
    p.add_argument(
        "--tail-policy",
        choices=["include_partial", "pad_with_zeros", "drop_partial"],
        default=DEFAULT_TAIL_POLICY,
    )
    p.add_argument("--keys", type=int, default=20, help="Number of deterministic keys per config")
    p.add_argument("--seed", type=int, default=0, help="Seed for deterministic key and flip derivation")
    p.add_argument("--out-dir", type=str, default="results/fig_b", help="Output directory")
    p.add_argument("--no-plot", action="store_true", help="Write CSV only (skip PNG plotting)")
    # --- Viz flags (mirrors the demo) ---
    p.add_argument("--viz", action="store_true", help="Render per-step DAG PNGs colored by mismatched nodes")
    p.add_argument("--viz-dir", type=str, default="dag_viz", help="Output directory for DAG step PNGs")
    p.add_argument("--viz-prefix", type=str, default="dag", help="Prefix for DAG PNG filenames")
    p.add_argument(
        "--viz-keys",
        type=str,
        default="0",
        help="Comma-separated key_ids to render DAG viz for (default: just key 0)",
    )
    p.add_argument(
        "--viz-flip-counts",
        type=str,
        default="",
        help="Comma-separated flip counts to render DAG viz for (default: all)",
    )
    return p.parse_args()


def get_flip_indices(
    flip_count: int,
    bit_length: int,
    mode: str,
    rng,
) -> list[int]:
    if mode == "random":
        return rng.sample(range(bit_length), flip_count)
    elif mode == "burst":
        max_start = bit_length - flip_count
        start = rng.randint(0, max_start)
        return list(range(start, start + flip_count))
    else:
        raise ValueError(f"Unknown flip mode: {mode}")


def run_trial(
    bits: list[int],
    key: bytes,
    rounds: int,
    flip_indices: list[int],
    row_group_size: int,
    col_group_size: int,
    hash_bits: int,
    tail_policy: str,
    record_step_snapshots: bool = False,
) -> dict[str, Any]:
    baseline_grid, meta = bits_to_grid(bits, key=key, rounds=rounds)
    current_grid = [row[:] for row in baseline_grid]

    for src_idx in flip_indices:
        r, c = source_index_to_grid_coord(src_idx, meta)
        current_grid[r][c] ^= 1

    result = correct_with_dag(
        baseline_grid=baseline_grid,
        current_grid=current_grid,
        meta=meta,
        row_group_size=row_group_size,
        col_group_size=col_group_size,
        hash_bits=hash_bits,
        tail_policy=tail_policy,
        record_step_snapshots=record_step_snapshots,
    )

    restored_bits = grid_to_bits(result.corrected_grid, meta, key=key)

    return {
        "fully_corrected": restored_bits == bits,
        "mismatched_before": len(result.mismatched_before),
        "mismatched_after": len(result.mismatched_after),
        "correction_steps": len(result.steps),
        "total_combos_evaluated": result.total_combos_evaluated,
        "total_nodes_visited": result.total_nodes_visited,
        "max_flip_level_reached": result.max_flip_level_reached,
        "nodes_with_no_correction": result.nodes_with_no_correction,
        "solve_time_ms": round(result.solve_time_seconds * 1000, 3),
        # Pass through for viz
        "_result": result,
        "_baseline_grid": baseline_grid,
        "_meta": meta,
    }


def maybe_render_viz(
    trial: dict[str, Any],
    hash_bits: int,
    flip_count: int,
    key_id: int,
    mode: str,
    row_group_size: int,
    col_group_size: int,
    tail_policy: str,
    viz_dir: str,
    viz_prefix: str,
) -> None:
    """Render per-step DAG PNGs for a single trial, mirroring the demo's viz logic."""
    try:
        from visualize_dag import render_hash_dag_png
    except ImportError:
        print("visualize_dag not found ? skipping DAG viz.")
        return

    result = trial["_result"]
    baseline_grid = trial["_baseline_grid"]
    meta = trial["_meta"]

    if not result.step_snapshots:
        print(f"  [viz] No snapshots for mode={mode} hash={hash_bits} flips={flip_count} key={key_id}")
        return

    baseline_hashes = build_hash_nodes(
        baseline_grid,
        meta,
        row_group_size=row_group_size,
        col_group_size=col_group_size,
        hash_bits=hash_bits,
        tail_policy=tail_policy,
    )
    dag = build_hash_graph(baseline_hashes)

    trial_dir = os.path.join(viz_dir, f"{mode}_hash{hash_bits}_flips{flip_count:02d}_key{key_id}")
    os.makedirs(trial_dir, exist_ok=True)

    for i, (corrected_node_id, mismatched_node_ids) in enumerate(result.step_snapshots):
        filename = f"{viz_prefix}_step_{i:02d}_{corrected_node_id}.png"
        out_path = os.path.join(trial_dir, filename)
        try:
            render_hash_dag_png(dag, out_path=out_path, mismatched_node_ids=mismatched_node_ids)
            print(f"  [viz] Wrote: {out_path}")
        except RuntimeError as e:
            print(f"  [viz] Render failed for {out_path}: {e}")


def collect_rows(
    args: argparse.Namespace,
    hash_sizes: list[int],
    modes: list[str],
    bits: list[int],
    viz_key_ids: set[int],
    viz_flip_counts: set[int],
    max_flip_count: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for mode in modes:
        for hash_bits in hash_sizes:
            for flip_count in range(1, max_flip_count + 1):
                for key_id in range(args.keys):
                    key = stable_key(args.seed, key_id)
                    rng = stable_rng(args.seed, key_id, flip_count, hash_bits, mode)
                    flip_indices = get_flip_indices(
                        flip_count=flip_count,
                        bit_length=args.bit_length,
                        mode=mode,
                        rng=rng,
                    )

                    # Only record snapshots for trials we intend to visualize
                    want_viz = (
                        args.viz
                        and key_id in viz_key_ids
                        and (not viz_flip_counts or flip_count in viz_flip_counts)
                    )

                    trial = run_trial(
                        bits=bits,
                        key=key,
                        rounds=args.rounds,
                        flip_indices=flip_indices,
                        row_group_size=args.row_group_size,
                        col_group_size=args.col_group_size,
                        hash_bits=hash_bits,
                        tail_policy=args.tail_policy,
                        record_step_snapshots=want_viz,
                    )

                    if want_viz:
                        maybe_render_viz(
                            trial=trial,
                            hash_bits=hash_bits,
                            flip_count=flip_count,
                            key_id=key_id,
                            mode=mode,
                            row_group_size=args.row_group_size,
                            col_group_size=args.col_group_size,
                            tail_policy=args.tail_policy,
                            viz_dir=args.viz_dir,
                            viz_prefix=args.viz_prefix,
                        )

                    rows.append(
                        {
                            "flip_mode": mode,
                            "hash_bits": hash_bits,
                            "flip_count": flip_count,
                            "key_id": key_id,
                            "fully_corrected": int(trial["fully_corrected"]),
                            "mismatched_before": trial["mismatched_before"],
                            "mismatched_after": trial["mismatched_after"],
                            "correction_steps": trial["correction_steps"],
                            "total_combos_evaluated": trial["total_combos_evaluated"],
                            "total_nodes_visited": trial["total_nodes_visited"],
                            "max_flip_level_reached": trial["max_flip_level_reached"],
                            "nodes_with_no_correction": trial["nodes_with_no_correction"],
                        }
                    )

                successes = sum(
                    1 for r in rows
                    if r["flip_mode"] == mode
                    and r["hash_bits"] == hash_bits
                    and r["flip_count"] == flip_count
                    and r["fully_corrected"]
                )
                print(
                    f"mode={mode:6s}  hash_bits={hash_bits:2d}  flips={flip_count:2d}  "
                    f"success={successes}/{args.keys}"
                )

    return rows


def plot_results(
    rows: list[dict[str, Any]],
    hash_sizes: list[int],
    modes: list[str],
    out_dir: str,
    bit_length: int,
    max_flip_count: int,
) -> None:
    import matplotlib.pyplot as plt

    flip_counts = list(range(1, max_flip_count + 1))

    for mode in modes:
        fig, axes = plt.subplots(2, 2, figsize=(14, 10))
        fig.suptitle(f"Solver effectiveness — flip mode: {mode}", fontsize=14, fontweight="bold")
        mode_rows = [r for r in rows if r["flip_mode"] == mode]

        # Panel 1: Success rate
        ax1 = axes[0][0]
        for hash_bits in hash_sizes:
            xs, ys, yerr = [], [], []
            for fc in flip_counts:
                subset = [r for r in mode_rows if r["hash_bits"] == hash_bits and r["flip_count"] == fc]
                rate = sum(r["fully_corrected"] for r in subset) / len(subset) if subset else float("nan")
                n = len(subset)
                se = math.sqrt(rate * (1 - rate) / n) if n > 1 and 0 < rate < 1 else 0.0
                xs.append(fc)
                ys.append(rate)
                yerr.append(se)
            ax1.errorbar(xs, ys, yerr=yerr, marker="o", linewidth=2, capsize=3, label=f"{hash_bits}-bit")
        ax1.set_title("Success rate vs flip count")
        ax1.set_xlabel("Injected flips")
        ax1.set_ylabel("Success rate")
        ax1.set_ylim(-0.05, 1.05)
        ax1.set_xticks(flip_counts)
        ax1.grid(True, alpha=0.3)
        ax1.legend()
        ax1_ber = ax1.secondary_xaxis("top")
        ax1_ber.set_xticks(flip_counts)
        ax1_ber.set_xticklabels([f"{fc/bit_length:.1%}" for fc in flip_counts], fontsize=7, rotation=45)
        ax1_ber.set_xlabel("BER", fontsize=9)

        # Panel 2: Total combinations evaluated
        ax2 = axes[0][1]
        for hash_bits in hash_sizes:
            xs, ys, yerr = [], [], []
            for fc in flip_counts:
                subset = [r for r in mode_rows if r["hash_bits"] == hash_bits and r["flip_count"] == fc]
                vals = [float(r["total_combos_evaluated"]) for r in subset]
                a = agg(vals)
                xs.append(fc)
                ys.append(a.mean)
                yerr.append(a.sem)
            ax2.errorbar(xs, ys, yerr=yerr, marker="o", linewidth=2, capsize=3, label=f"{hash_bits}-bit")
        ax2.set_title("Search effort: total combinations evaluated")
        ax2.set_xlabel("Injected flips")
        ax2.set_ylabel("Mean combinations evaluated")
        ax2.set_xticks(flip_counts)
        ax2.grid(True, alpha=0.3)
        ax2.legend()

        # Panel 3: Max flip level reached
        ax3 = axes[1][0]
        for hash_bits in hash_sizes:
            xs, ys, yerr = [], [], []
            for fc in flip_counts:
                subset = [r for r in mode_rows if r["hash_bits"] == hash_bits and r["flip_count"] == fc]
                vals = [float(r["max_flip_level_reached"]) for r in subset]
                a = agg(vals)
                xs.append(fc)
                ys.append(a.mean)
                yerr.append(a.sem)
            ax3.errorbar(xs, ys, yerr=yerr, marker="o", linewidth=2, capsize=3, label=f"{hash_bits}-bit")
        ax3.set_title("Max flip level reached during search")
        ax3.set_xlabel("Injected flips")
        ax3.set_ylabel("Mean max flip level")
        ax3.set_xticks(flip_counts)
        ax3.grid(True, alpha=0.3)
        ax3.legend()

        # Panel 4: Solve time
        ax4 = axes[1][1]
        for hash_bits in hash_sizes:
            xs, ys, yerr = [], [], []
            for fc in flip_counts:
                subset = [r for r in mode_rows if r["hash_bits"] == hash_bits and r["flip_count"] == fc]
                vals = [float(r["solve_time_ms"]) for r in subset]
                a = agg(vals)
                xs.append(fc)
                ys.append(a.mean)
                yerr.append(a.sem)
            ax4.errorbar(xs, ys, yerr=yerr, marker="o", linewidth=2, capsize=3, label=f"{hash_bits}-bit")
        ax4.set_title("Mean solve time (ms)")
        ax4.set_xlabel("Injected flips")
        ax4.set_ylabel("Solve time (ms)")
        ax4.set_xticks(flip_counts)
        ax4.grid(True, alpha=0.3)
        ax4.legend()

        plt.tight_layout()
        out_path = os.path.join(out_dir, f"figure_b_{mode}.png")
        plt.savefig(out_path, dpi=200)
        plt.close()
        print(f"Saved plot to {out_path}")

    # Comparison plot across modes (search effort: burst vs random)
    if len(modes) == 2:
        fig, axes = plt.subplots(1, len(hash_sizes), figsize=(7 * len(hash_sizes), 5))
        if len(hash_sizes) == 1:
            axes = [axes]
        fig.suptitle("Search effort: burst vs random — Feistel shuffle equalises error patterns", fontsize=13, fontweight="bold")
        linestyles = {"random": "--", "burst": "-"}
        for ax, hash_bits in zip(axes, hash_sizes):
            for mode in modes:
                mode_rows = [r for r in rows if r["flip_mode"] == mode]
                xs, ys, yerr = [], [], []
                for fc in flip_counts:
                    subset = [r for r in mode_rows if r["hash_bits"] == hash_bits and r["flip_count"] == fc]
                    vals = [float(r["total_combos_evaluated"]) for r in subset]
                    a = agg(vals)
                    xs.append(fc)
                    ys.append(a.mean)
                    yerr.append(a.sem)
                ax.errorbar(
                    xs, ys, yerr=yerr,
                    marker="o", linewidth=2, capsize=3,
                    linestyle=linestyles[mode],
                    label=f"{mode}",
                )
            ax.set_title(f"{hash_bits}-bit hash")
            ax.set_xlabel("Injected flips")
            ax.set_ylabel("Mean combinations evaluated")
            ax.set_xticks(flip_counts)
            ax.grid(True, alpha=0.3)
            ax.legend()

        plt.tight_layout()
        out_path = os.path.join(out_dir, "figure_b_comparison.png")
        plt.savefig(out_path, dpi=200)
        plt.close()
        print(f"Saved comparison plot to {out_path}")


def main() -> None:
    args = parse_args()
    hash_sizes = parse_int_list(args.hash_sizes)
    for h in hash_sizes:
        if h not in {8, 16, 32}:
            raise ValueError(f"--hash-sizes must be from {{8, 16, 32}}, got {h}")
    if not hash_sizes:
        raise ValueError("--hash-sizes must be non-empty")
    if args.bit_length <= 0:
        raise ValueError("--bit-length must be positive")
    if args.keys <= 0:
        raise ValueError("--keys must be positive")
    if not (0 < args.max_ber <= 1.0):
        raise ValueError("--max-ber must be in (0, 1]")
    max_flip_count = max(1, int(args.max_ber * args.bit_length))

    modes = ["random", "burst"] if args.flip_mode == "both" else [args.flip_mode]

    viz_key_ids: set[int] = set(parse_int_list(args.viz_keys)) if args.viz_keys.strip() else {0}
    viz_flip_counts: set[int] = set(parse_int_list(args.viz_flip_counts)) if args.viz_flip_counts.strip() else set()

    out_dir = args.out_dir
    ensure_dir(out_dir)

    config: dict[str, Any] = {
        "hash_sizes": hash_sizes,
        "flip_mode": args.flip_mode,
        "bit_length": args.bit_length,
        "rounds": args.rounds,
        "row_group_size": args.row_group_size,
        "col_group_size": args.col_group_size,
        "tail_policy": args.tail_policy,
        "keys": args.keys,
        "seed": args.seed,
        "max_flip_count": max_flip_count,
        "max_ber": args.max_ber,
        "viz": args.viz,
        "viz_key_ids": sorted(viz_key_ids),
        "viz_flip_counts": sorted(viz_flip_counts),
    }
    write_json(os.path.join(out_dir, "config.json"), config)

    bits = [(i * 3 + 1) % 2 for i in range(args.bit_length)]
    rows = collect_rows(
        args=args,
        hash_sizes=hash_sizes,
        modes=modes,
        bits=bits,
        viz_key_ids=viz_key_ids,
        viz_flip_counts=viz_flip_counts,
        max_flip_count=max_flip_count,
    )

    csv_path = os.path.join(out_dir, "figure_b_solver.csv")
    write_csv(
        csv_path,
        rows=rows,
        fieldnames=[
            "flip_mode", "hash_bits", "flip_count", "key_id",
            "fully_corrected", "mismatched_before", "mismatched_after",
            "correction_steps", "total_combos_evaluated", "total_nodes_visited",
            "max_flip_level_reached", "nodes_with_no_correction", "solve_time_ms",
        ],
    )

    if args.no_plot:
        return

    try:
        plot_results(rows=rows, hash_sizes=hash_sizes, modes=modes, out_dir=out_dir, bit_length=args.bit_length, max_flip_count=max_flip_count)
    except ModuleNotFoundError as e:
        raise RuntimeError(
            "matplotlib is required for plotting. Install it or rerun with --no-plot."
        ) from e


if __name__ == "__main__":
    main()