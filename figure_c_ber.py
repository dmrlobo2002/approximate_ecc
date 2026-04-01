"""Figure C: Correction success rate and decoder complexity vs. BER.

Sweeps BER from --ber-min to --ber-max across several group-size configs,
producing a 2-column figure (hash_bits=16 left, hash_bits=32 right) with:
  Top row:    Correction success rate vs. BER
  Bottom row: Mean combos evaluated vs. BER  (decoder complexity)
  Inset/annotation: mean solve time at each BER point
"""
from __future__ import annotations

import argparse
import math
import os
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

# Configurations: (row_group_size, col_group_size, label)
GROUP_CONFIGS = [
    (1, 1, "g=1"),
    (2, 2, "g=2"),
    (4, 4, "g=4"),
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Figure C: BER sweep — correction rate and complexity")
    p.add_argument("--bit-length", type=int, default=256)
    p.add_argument("--rounds", type=int, default=8)
    p.add_argument("--hash-sizes", type=str, default="16,32")
    p.add_argument("--ber-min", type=float, default=0.001, help="Minimum BER (e.g. 0.001 = 0.1%%)")
    p.add_argument("--ber-max", type=float, default=0.10, help="Maximum BER (e.g. 0.10 = 10%%)")
    p.add_argument("--ber-steps", type=int, default=20, help="Number of BER points")
    p.add_argument("--keys", type=int, default=30, help="Trials per BER point")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--tail-policy", default="include_partial",
                   choices=["include_partial", "pad_with_zeros", "drop_partial"])
    p.add_argument("--out-dir", type=str, default="results/fig_c")
    p.add_argument("--no-plot", action="store_true")
    return p.parse_args()


def ber_to_flip_count(ber: float, bit_length: int) -> int:
    return max(1, round(ber * bit_length))


def run_trial(
    bits: list[int],
    key: bytes,
    rounds: int,
    flip_indices: list[int],
    row_group_size: int,
    col_group_size: int,
    hash_bits: int,
    tail_policy: str,
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
    )
    restored = grid_to_bits(result.corrected_grid, meta, key=key)
    return {
        "fully_corrected": restored == bits,
        "total_combos_evaluated": result.total_combos_evaluated,
        "solve_time_seconds": result.solve_time_seconds,
        "mismatched_before": len(result.mismatched_before),
        "mismatched_after": len(result.mismatched_after),
    }


def main() -> None:
    args = parse_args()
    hash_sizes = [int(h) for h in args.hash_sizes.split(",") if h.strip()]
    for h in hash_sizes:
        if h not in {8, 16, 32}:
            raise ValueError(f"hash size must be 8/16/32, got {h}")

    ensure_dir(args.out_dir)

    # Build BER points on a log scale for cleaner spread
    ber_points = [
        args.ber_min * ((args.ber_max / args.ber_min) ** (i / max(1, args.ber_steps - 1)))
        for i in range(args.ber_steps)
    ]

    bits = [(i * 3 + 1) % 2 for i in range(args.bit_length)]

    config: dict[str, Any] = {
        "bit_length": args.bit_length,
        "rounds": args.rounds,
        "hash_sizes": hash_sizes,
        "ber_min": args.ber_min,
        "ber_max": args.ber_max,
        "ber_steps": args.ber_steps,
        "keys": args.keys,
        "seed": args.seed,
        "tail_policy": args.tail_policy,
        "group_configs": [(r, c, lbl) for r, c, lbl in GROUP_CONFIGS],
    }
    write_json(os.path.join(args.out_dir, "config.json"), config)

    rows: list[dict[str, Any]] = []

    for hash_bits in hash_sizes:
        for row_gs, col_gs, cfg_label in GROUP_CONFIGS:
            for ber in ber_points:
                flip_count = ber_to_flip_count(ber, args.bit_length)
                actual_ber = flip_count / args.bit_length
                trial_results = []
                for key_id in range(args.keys):
                    key = stable_key(args.seed, key_id)
                    rng = stable_rng(args.seed, key_id, flip_count, hash_bits, row_gs, col_gs)
                    flip_indices = rng.sample(range(args.bit_length), min(flip_count, args.bit_length))
                    t = run_trial(
                        bits=bits,
                        key=key,
                        rounds=args.rounds,
                        flip_indices=flip_indices,
                        row_group_size=row_gs,
                        col_group_size=col_gs,
                        hash_bits=hash_bits,
                        tail_policy=args.tail_policy,
                    )
                    trial_results.append(t)

                success_rate = sum(1 for t in trial_results if t["fully_corrected"]) / len(trial_results)
                combos_agg = agg([float(t["total_combos_evaluated"]) for t in trial_results])
                time_agg = agg([t["solve_time_seconds"] for t in trial_results])

                rows.append({
                    "hash_bits": hash_bits,
                    "group_config": cfg_label,
                    "row_group_size": row_gs,
                    "col_group_size": col_gs,
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
                    f"hash={hash_bits:2d}  {cfg_label:4s}  "
                    f"BER={actual_ber:.3f}  flips={flip_count:3d}  "
                    f"success={success_rate:.3f}  "
                    f"combos={combos_agg.mean:.1f}  "
                    f"time={time_agg.mean*1000:.2f}ms"
                )

    csv_path = os.path.join(args.out_dir, "figure_c_ber.csv")
    write_csv(
        csv_path,
        rows=rows,
        fieldnames=[
            "hash_bits", "group_config", "row_group_size", "col_group_size",
            "ber_target", "ber_actual", "flip_count",
            "success_rate", "mean_combos", "stdev_combos",
            "mean_solve_time_s", "stdev_solve_time_s", "n_trials",
        ],
    )
    print(f"Wrote CSV: {csv_path}")

    if args.no_plot:
        return

    try:
        import matplotlib.pyplot as plt
    except ModuleNotFoundError as e:
        raise RuntimeError("matplotlib required for plotting; use --no-plot to skip") from e

    fig, axes = plt.subplots(2, len(hash_sizes), figsize=(7 * len(hash_sizes), 10))
    if len(hash_sizes) == 1:
        axes = [[axes[0]], [axes[1]]]

    markers = ["o", "s", "^"]
    colors = ["#1f77b4", "#ff7f0e", "#2ca02c"]

    for col_idx, hash_bits in enumerate(hash_sizes):
        ax_top = axes[0][col_idx]
        ax_bot = axes[1][col_idx]
        subset = [r for r in rows if r["hash_bits"] == hash_bits]

        for (row_gs, col_gs, cfg_label), marker, color in zip(GROUP_CONFIGS, markers, colors):
            cfg_rows = sorted(
                [r for r in subset if r["group_config"] == cfg_label],
                key=lambda r: r["ber_actual"],
            )
            xs = [r["ber_actual"] for r in cfg_rows]
            ys_success = [r["success_rate"] for r in cfg_rows]
            ys_combos = [r["mean_combos"] for r in cfg_rows]

            ax_top.plot(xs, ys_success, marker=marker, color=color, linewidth=2, label=cfg_label)
            ax_bot.plot(xs, ys_combos, marker=marker, color=color, linewidth=2, label=cfg_label)

        ax_top.set_title(f"Success rate vs. BER ({hash_bits}-bit hash)")
        ax_top.set_xlabel("BER")
        ax_top.set_ylabel("Correction success rate")
        ax_top.set_ylim(-0.05, 1.05)
        ax_top.set_xscale("log")
        ax_top.grid(True, alpha=0.3)
        ax_top.legend()

        ax_bot.set_title(f"Decoder complexity vs. BER ({hash_bits}-bit hash)")
        ax_bot.set_xlabel("BER")
        ax_bot.set_ylabel("Mean combinations evaluated")
        ax_bot.set_xscale("log")
        ax_bot.set_yscale("log")
        ax_bot.grid(True, alpha=0.3)
        ax_bot.legend()

    plt.tight_layout()
    out_png = os.path.join(args.out_dir, "figure_c_ber.png")
    plt.savefig(out_png, dpi=200)
    plt.close()
    print(f"Wrote plot: {out_png}")


if __name__ == "__main__":
    main()
