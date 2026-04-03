"""Figure C: Correction success rate and decoder complexity vs. BER.

Compares 32x32, 64x64, and 128x128 grid sizes (bit-lengths 1024, 4096, 16384)
with group_size=1 and a fixed hash width, producing a 2-subplot figure:
  Top:    Correction success rate vs. BER
  Bottom: Mean combos evaluated vs. BER  (decoder complexity)
"""
from __future__ import annotations

import argparse
import math
import os
from concurrent.futures import ProcessPoolExecutor
from typing import Any

from bitflip_solver import correct_with_dag
from grid_shuffle import bits_to_grid, grid_to_bits, source_index_to_grid_coord
from group_hash import build_hash_nodes

from experiments.common import (
    agg,
    ensure_dir,
    stable_key,
    stable_rng,
    write_csv,
    write_json,
)

COLORS = ["#1f77b4", "#ff7f0e", "#2ca02c"]
MARKERS = ["o", "s", "^"]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Figure C: BER sweep — correction rate and complexity")
    p.add_argument("--grid-sizes", type=str, default="32,64,128",
                   help="Grid side-lengths to compare (bit-length = n*n)")
    p.add_argument("--hash-bits", type=int, choices=[8, 16, 32], default=16)
    p.add_argument("--rounds", type=int, default=8)
    p.add_argument("--ber-min", type=float, default=0.001)
    p.add_argument("--ber-max", type=float, default=0.05)
    p.add_argument("--ber-steps", type=int, default=20)
    p.add_argument("--keys", type=int, default=30, help="Trials per BER point")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--tail-policy", default="include_partial",
                   choices=["include_partial", "pad_with_zeros", "drop_partial"])
    p.add_argument("--max-combos", type=int, default=50000,
                   help="Per-trial combo budget cap (prevents slow trials at high BER)")
    p.add_argument("--out-dir", type=str, default="results/fig_c")
    p.add_argument("--no-plot", action="store_true")
    p.add_argument("--parallel", action="store_true",
                   help="Run trials in parallel using multiple processes")
    p.add_argument("--workers", type=int, default=0,
                   help="Number of parallel workers (0 = cpu_count)")
    return p.parse_args()


def ber_to_flip_count(ber: float, bit_length: int) -> int:
    return max(1, round(ber * bit_length))


def run_trial(
    bits: list[int],
    key: bytes,
    rounds: int,
    flip_indices: list[int],
    hash_bits: int,
    tail_policy: str,
    max_combos: int | None,
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
        row_group_size=1,
        col_group_size=1,
        hash_bits=hash_bits,
        tail_policy=tail_policy,
        max_combos=max_combos,
    )
    restored = grid_to_bits(result.corrected_grid, meta, key=key)
    return {
        "fully_corrected": restored == bits,
        "total_combos_evaluated": result.total_combos_evaluated,
        "solve_time_seconds": result.solve_time_seconds,
        "mismatched_before": len(result.mismatched_before),
        "mismatched_after": len(result.mismatched_after),
    }


def _trial_task(task: tuple) -> dict[str, Any]:
    bits, key, rounds, flip_indices, hash_bits, tail_policy, max_combos = task
    return run_trial(bits, key, rounds, flip_indices, hash_bits, tail_policy, max_combos)


def main() -> None:
    args = parse_args()
    grid_sizes = [int(x) for x in args.grid_sizes.split(",") if x.strip()]

    ensure_dir(args.out_dir)

    ber_points = [
        args.ber_min * ((args.ber_max / args.ber_min) ** (i / max(1, args.ber_steps - 1)))
        for i in range(args.ber_steps)
    ]

    write_json(os.path.join(args.out_dir, "config.json"), {
        "grid_sizes": grid_sizes,
        "hash_bits": args.hash_bits,
        "rounds": args.rounds,
        "ber_min": args.ber_min,
        "ber_max": args.ber_max,
        "ber_steps": args.ber_steps,
        "keys": args.keys,
        "seed": args.seed,
        "max_combos": args.max_combos,
        "tail_policy": args.tail_policy,
    })

    # Build all tasks upfront so RNG state is deterministic regardless of
    # parallel/serial execution.
    all_tasks: list[tuple] = []
    all_metas: list[tuple] = []
    for n in grid_sizes:
        bit_length = n * n
        bits = [(i * 3 + 1) % 2 for i in range(bit_length)]
        for ber in ber_points:
            flip_count = ber_to_flip_count(ber, bit_length)
            actual_ber = flip_count / bit_length
            for key_id in range(args.keys):
                key = stable_key(args.seed, key_id)
                rng = stable_rng(args.seed, key_id, flip_count, args.hash_bits, n)
                flip_indices = rng.sample(range(bit_length), min(flip_count, bit_length))
                all_tasks.append((
                    bits, key, args.rounds, flip_indices,
                    args.hash_bits, args.tail_policy, args.max_combos,
                ))
                all_metas.append((n, bit_length, actual_ber, flip_count, ber))

    total = len(all_tasks)
    print(f"Running {total} trials ({len(grid_sizes)} grid sizes × {args.ber_steps} BER points × {args.keys} keys)...")

    if args.parallel:
        n_workers = args.workers if args.workers > 0 else (os.cpu_count() or 1)
        print(f"Parallel mode: {n_workers} workers")
        with ProcessPoolExecutor(max_workers=n_workers) as executor:
            flat_results = list(executor.map(_trial_task, all_tasks))
    else:
        flat_results = [_trial_task(t) for t in all_tasks]

    rows: list[dict[str, Any]] = []
    idx = 0
    for n in grid_sizes:
        bit_length = n * n
        for ber in ber_points:
            flip_count = ber_to_flip_count(ber, bit_length)
            actual_ber = flip_count / bit_length
            trial_results = flat_results[idx: idx + args.keys]
            idx += args.keys

            success_rate = sum(1 for t in trial_results if t["fully_corrected"]) / len(trial_results)
            combos_agg = agg([float(t["total_combos_evaluated"]) for t in trial_results])
            time_agg = agg([t["solve_time_seconds"] for t in trial_results])

            rows.append({
                "grid_size": n,
                "bit_length": bit_length,
                "hash_bits": args.hash_bits,
                "ber_target": round(ber, 6),
                "ber_actual": round(actual_ber, 6),
                "flip_count": flip_count,
                "success_rate": round(success_rate, 4),
                "mean_combos": round(combos_agg.mean, 2),
                "stdev_combos": round(combos_agg.stdev, 2),
                "mean_solve_time_s": round(time_agg.mean, 6),
                "stdev_solve_time_s": round(time_agg.stdev, 6),
                "n_trials": args.keys,
            })
            print(
                f"{n:3d}x{n:<3d}  BER={actual_ber:.3f}  flips={flip_count:4d}  "
                f"success={success_rate:.3f}  combos={combos_agg.mean:.1f}  "
                f"time={time_agg.mean*1000:.1f}ms"
            )

    csv_path = os.path.join(args.out_dir, "figure_c_ber.csv")
    write_csv(csv_path, rows=rows, fieldnames=[
        "grid_size", "bit_length", "hash_bits",
        "ber_target", "ber_actual", "flip_count",
        "success_rate", "mean_combos", "stdev_combos",
        "mean_solve_time_s", "stdev_solve_time_s", "n_trials",
    ])
    print(f"Wrote CSV: {csv_path}")

    if args.no_plot:
        return

    try:
        import matplotlib.pyplot as plt
    except ModuleNotFoundError as e:
        raise RuntimeError("matplotlib required; use --no-plot to skip") from e

    fig, (ax_top, ax_bot) = plt.subplots(2, 1, figsize=(9, 8), sharex=True)

    for i, n in enumerate(grid_sizes):
        bit_length = n * n
        subset = sorted(
            [r for r in rows if r["grid_size"] == n],
            key=lambda r: r["ber_actual"],
        )
        xs = [r["ber_actual"] * 100 for r in subset]
        ys_success = [r["success_rate"] for r in subset]
        ys_combos = [max(r["mean_combos"], 1) for r in subset]
        label = f"{n}\u00d7{n}  ({bit_length:,} bits)"

        ax_top.plot(xs, ys_success, marker=MARKERS[i], color=COLORS[i],
                    linewidth=2, label=label)
        ax_bot.plot(xs, ys_combos, marker=MARKERS[i], color=COLORS[i],
                    linewidth=2, label=label)

    ax_top.set_ylabel("Correction success rate")
    ax_top.set_ylim(-0.05, 1.05)
    ax_top.set_xscale("log")
    ax_top.set_title(
        f"Correction success rate vs. BER\n"
        f"(group_size=1, hash_bits={args.hash_bits}, rounds={args.rounds}, "
        f"max_combos={args.max_combos:,})"
    )
    ax_top.legend()
    ax_top.grid(True, alpha=0.3)

    ax_bot.set_xlabel("BER (%)")
    ax_bot.set_ylabel("Mean combinations evaluated")
    ax_bot.set_xscale("log")
    ax_bot.set_yscale("log")
    ax_bot.set_title("Decoder complexity vs. BER")
    ax_bot.legend()
    ax_bot.grid(True, alpha=0.3)

    plt.tight_layout()
    out_png = os.path.join(args.out_dir, "figure_c_ber.png")
    plt.savefig(out_png, dpi=200)
    plt.close()
    print(f"Wrote plot: {out_png}")


if __name__ == "__main__":
    main()
