"""Figure 6: Comprehensive BER × Bit-Length study.

Panel A (2D): Success rate vs BER — one line per bit-length.
Panel B (2D): Success rate vs bit-length — one line per BER value.
Panel C (3D): Success rate surface over (BER, bit-length).
Panel D (3D): Mean solve time surface over (BER, bit-length).
"""
from __future__ import annotations

import argparse
import math
import os
from typing import Any

import numpy as np

from experiments.common import (
    Agg,
    agg,
    compute_overhead_ratio,
    ensure_dir,
    stable_key,
    stable_rng,
    write_csv,
    write_json,
)
from experiments.trial_runner import get_flip_indices, run_trials_parallel, run_trials_serial

DEFAULT_BIT_LENGTHS = [256, 512, 1024, 2048, 4096]
DEFAULT_BER_VALUES = [0.01, 0.02, 0.05, 0.08, 0.10, 0.15]
DEFAULT_HASH_BITS = 16
DEFAULT_KEYS = 20
DEFAULT_ROUNDS = 8


def parse_float_list(spec: str) -> list[float]:
    spec = spec.strip()
    if not spec:
        return []
    return [float(x.strip()) for x in spec.split(",") if x.strip()]


def parse_int_list(spec: str) -> list[int]:
    spec = spec.strip()
    if not spec:
        return []
    return [int(x.strip()) for x in spec.split(",") if x.strip()]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Figure 6: Comprehensive BER × Bit-Length study"
    )
    p.add_argument(
        "--bit-lengths", type=str,
        default=",".join(str(x) for x in DEFAULT_BIT_LENGTHS),
    )
    p.add_argument(
        "--ber-values", type=str,
        default=",".join(str(x) for x in DEFAULT_BER_VALUES),
    )
    p.add_argument("--hash-bits", type=int, default=DEFAULT_HASH_BITS)
    p.add_argument("--keys", type=int, default=DEFAULT_KEYS)
    p.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out-dir", type=str, default="results/fig6")
    p.add_argument("--no-plot", action="store_true")
    p.add_argument("--parallel", action="store_true")
    p.add_argument("--workers", type=int, default=0)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    bit_lengths = parse_int_list(args.bit_lengths)
    ber_values = parse_float_list(args.ber_values)
    if not bit_lengths:
        raise ValueError("--bit-lengths must be non-empty")
    if not ber_values:
        raise ValueError("--ber-values must be non-empty")

    hash_bits = args.hash_bits
    ensure_dir(args.out_dir)
    write_json(os.path.join(args.out_dir, "config.json"), {
        "bit_lengths": bit_lengths,
        "ber_values": ber_values,
        "hash_bits": hash_bits,
        "keys": args.keys,
        "rounds": args.rounds,
        "seed": args.seed,
    })

    # Build bits fixture per block size (deterministic, not random)
    bits_by_length = {L: [(i * 3 + 1) % 2 for i in range(L)] for L in bit_lengths}

    # Build all tasks across the (bit_length, ber) grid
    all_tasks: list[tuple] = []
    all_metas: list[tuple] = []  # (bit_length, ber, key_id)

    for L in bit_lengths:
        for ber in ber_values:
            flip_count = max(1, round(ber * L))
            for key_id in range(args.keys):
                key = stable_key(args.seed, key_id)
                rng = stable_rng(args.seed, key_id, flip_count, hash_bits, L, ber)
                flip_indices = get_flip_indices(flip_count, L, "random", rng)
                all_tasks.append((
                    bits_by_length[L], key, args.rounds, flip_indices,
                    1, 1,           # row_group_size, col_group_size
                    hash_bits,
                    "include_partial", None, 0, "crc",
                    1, 1,           # row_splits, col_splits
                ))
                all_metas.append((L, ber, key_id))

    total = len(all_tasks)
    print(f"Running {total} trials ({len(bit_lengths)} bit-lengths × {len(ber_values)} BER values × {args.keys} keys)...")

    if args.parallel:
        flat_results = run_trials_parallel(all_tasks, args.workers)
    else:
        flat_results = run_trials_serial(all_tasks)

    # Collect per-trial rows
    trial_rows: list[dict[str, Any]] = []
    for trial, (L, ber, key_id) in zip(flat_results, all_metas):
        trial_rows.append({
            "bit_length": L,
            "ber": ber,
            "flip_count": max(1, round(ber * L)),
            "key_id": key_id,
            "fully_corrected": int(trial["fully_corrected"]),
            "solve_time_ms": trial["solve_time_ms"],
            "total_combos_evaluated": trial["total_combos_evaluated"],
        })

    write_csv(
        os.path.join(args.out_dir, "fig6_trials.csv"),
        trial_rows,
        ["bit_length", "ber", "flip_count", "key_id", "fully_corrected", "solve_time_ms", "total_combos_evaluated"],
    )

    # Aggregate per (bit_length, ber) cell
    agg_rows: list[dict[str, Any]] = []
    # cell_stats[(L, ber)] = (success_rate_agg, solve_time_agg)
    cell_stats: dict[tuple[int, float], tuple[Agg, Agg]] = {}

    for L in bit_lengths:
        for ber in ber_values:
            subset = [r for r in trial_rows if r["bit_length"] == L and r["ber"] == ber]
            success_agg = agg([float(r["fully_corrected"]) for r in subset])
            time_agg = agg([r["solve_time_ms"] for r in subset])
            cell_stats[(L, ber)] = (success_agg, time_agg)
            agg_rows.append({
                "bit_length": L,
                "ber": ber,
                "flip_count": max(1, round(ber * L)),
                "success_rate": success_agg.mean,
                "success_sem": success_agg.sem,
                "mean_solve_ms": time_agg.mean,
                "solve_sem": time_agg.sem,
                "n": success_agg.n,
            })
            print(f"  L={L:6d}  BER={ber:.0%}  success={success_agg.mean:.1%}  t={time_agg.mean:.1f}ms")

    write_csv(
        os.path.join(args.out_dir, "fig6_agg.csv"),
        agg_rows,
        ["bit_length", "ber", "flip_count", "success_rate", "success_sem", "mean_solve_ms", "solve_sem", "n"],
    )

    if args.no_plot:
        return

    try:
        import matplotlib.pyplot as plt
        import matplotlib.ticker as ticker
        from mpl_toolkits.mplot3d import Axes3D  # noqa: F401 (registers 3d projection)
    except ModuleNotFoundError as e:
        raise RuntimeError("matplotlib required; install it or use --no-plot") from e

    # Color maps for 2D panels
    ber_cmap = plt.get_cmap("plasma")
    len_cmap = plt.get_cmap("viridis")
    ber_colors = {b: ber_cmap(i / max(len(ber_values) - 1, 1)) for i, b in enumerate(ber_values)}
    len_colors = {L: len_cmap(i / max(len(bit_lengths) - 1, 1)) for i, L in enumerate(bit_lengths)}

    fig = plt.figure(figsize=(18, 14))
    fig.suptitle(
        f"Approximate ECC: BER × Bit-Length Study ({hash_bits}-bit CRC, {args.keys} keys/cell)",
        fontsize=14, fontweight="bold",
    )

    # --- Panel A: success rate vs BER (one line per bit-length) ---
    ax_a = fig.add_subplot(2, 2, 1)
    for L in bit_lengths:
        xs = [b * 100 for b in ber_values]
        ys = [cell_stats[(L, b)][0].mean * 100 for b in ber_values]
        errs = [cell_stats[(L, b)][0].sem * 100 for b in ber_values]
        color = len_colors[L]
        ax_a.errorbar(xs, ys, yerr=errs, marker="o", markersize=5,
                      linewidth=2, color=color, label=f"{L:,} bits", capsize=3)

    ax_a.set_xlabel("BER (%)")
    ax_a.set_ylabel("Success rate (%)")
    ax_a.set_title("Success rate vs BER\n(one line per block size)")
    ax_a.set_xlim(left=0)
    ax_a.set_ylim(-5, 105)
    ax_a.grid(True, alpha=0.3)
    ax_a.legend(fontsize=8, ncol=2)
    ax_a.yaxis.set_major_formatter(ticker.PercentFormatter())
    ax_a.xaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f"{x:.0f}%"))

    # --- Panel B: success rate vs bit-length (one line per BER) ---
    ax_b = fig.add_subplot(2, 2, 2)
    for ber in ber_values:
        xs = sorted(bit_lengths)
        ys = [cell_stats[(L, ber)][0].mean * 100 for L in xs]
        errs = [cell_stats[(L, ber)][0].sem * 100 for L in xs]
        color = ber_colors[ber]
        ax_b.errorbar(xs, ys, yerr=errs, marker="s", markersize=5,
                      linewidth=2, color=color, label=f"BER {ber:.0%}", capsize=3)

    # Overhead is a function of bit-length only (group_size=1, splits=1)
    overhead_pct = {L: compute_overhead_ratio(L, 1, 1, hash_bits) * 100 for L in bit_lengths}

    ax_b.set_xscale("log", base=2)
    ax_b.set_xlabel("Block size (bits)")
    ax_b.set_ylabel("Success rate (%)")
    ax_b.set_title("Success rate vs block size\n(one line per BER, right axis = overhead)")
    ax_b.set_ylim(-5, 105)
    ax_b.grid(True, alpha=0.3)
    ax_b.legend(fontsize=8)
    ax_b.yaxis.set_major_formatter(ticker.PercentFormatter())
    ax_b.xaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f"{int(x):,}"))
    ax_b.set_xticks(bit_lengths)

    # Secondary axis: overhead % at each block size
    ax_b2 = ax_b.twinx()
    oh_xs = sorted(bit_lengths)
    oh_ys = [overhead_pct[L] for L in oh_xs]
    ax_b2.plot(oh_xs, oh_ys, color="gray", linestyle=":", linewidth=1.5,
               marker="^", markersize=4, label="Overhead %")
    ax_b2.set_ylabel("Overhead (%)", color="gray")
    ax_b2.tick_params(axis="y", labelcolor="gray")
    ax_b2.yaxis.set_major_formatter(ticker.PercentFormatter())
    ax_b2.legend(fontsize=8, loc="upper right")

    # --- Build 2D grid arrays for 3D panels ---
    ber_arr = np.array([b * 100 for b in ber_values])        # x: BER %
    len_arr = np.array(bit_lengths, dtype=float)              # y: bit-length
    overhead_arr = np.array([overhead_pct[L] for L in bit_lengths])  # y alt: overhead %

    BER_grid, LEN_grid = np.meshgrid(ber_arr, len_arr)
    BER_grid_oh, OH_grid = np.meshgrid(ber_arr, overhead_arr)

    success_grid = np.array([
        [cell_stats[(L, b)][0].mean * 100 for b in ber_values]
        for L in bit_lengths
    ])

    # --- Panel C: 3D surface — success rate vs (BER, bit-length) ---
    ax_c = fig.add_subplot(2, 2, 3, projection="3d")
    surf_c = ax_c.plot_surface(BER_grid, LEN_grid, success_grid,
                               cmap="viridis", edgecolor="none", alpha=0.9)
    fig.colorbar(surf_c, ax=ax_c, shrink=0.5, pad=0.1, label="Success rate (%)")
    ax_c.set_xlabel("BER (%)")
    ax_c.set_ylabel("Block size (bits)")
    ax_c.set_zlabel("Success rate (%)")
    ax_c.set_title("Success rate surface\n(BER × Block size)")
    ax_c.view_init(elev=30, azim=225)
    ax_c.set_zlim(0, 100)

    # --- Panel D: 3D surface — success rate vs (BER, overhead %) ---
    # Answers: "given my overhead budget and expected BER, what correction rate do I get?"
    ax_d = fig.add_subplot(2, 2, 4, projection="3d")
    surf_d = ax_d.plot_surface(BER_grid_oh, OH_grid, success_grid,
                               cmap="coolwarm", edgecolor="none", alpha=0.9)
    fig.colorbar(surf_d, ax=ax_d, shrink=0.5, pad=0.1, label="Success rate (%)")
    ax_d.set_xlabel("BER (%)")
    ax_d.set_ylabel("Overhead (%)")
    ax_d.set_zlabel("Success rate (%)")
    ax_d.set_title("Success rate surface\n(BER × Overhead)")
    ax_d.view_init(elev=30, azim=225)
    ax_d.set_zlim(0, 100)

    plt.tight_layout()
    out_path = os.path.join(args.out_dir, "fig6_ber_bitlength.png")
    plt.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close()
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
