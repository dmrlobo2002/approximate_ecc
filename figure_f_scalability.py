"""Figure F: Correction threshold BER vs. data-word size (scalability).

For each bit-length and group-size config, runs a BER sweep and reports
the highest BER at which correction success rate >= threshold (default 90%).
Shows how the scheme scales as the data word grows.
"""
from __future__ import annotations

import argparse
import os
from typing import Any

from bitflip_solver import correct_with_dag
from grid_shuffle import bits_to_grid, grid_to_bits, source_index_to_grid_coord

from experiments.common import (
    agg,
    compute_overhead_ratio,
    ensure_dir,
    parse_int_list,
    stable_key,
    stable_rng,
    write_csv,
    write_json,
)

GROUP_CONFIGS = [
    (1, 1, "g=1"),
    (2, 2, "g=2"),
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Figure F: Scalability — BER threshold vs. bit-length")
    p.add_argument("--lengths", type=str, default="64,128,256",
                   help="Comma-separated bit-lengths to test")
    p.add_argument("--hash-bits", type=int, default=16, choices=[8, 16, 32])
    p.add_argument("--rounds", type=int, default=8)
    p.add_argument("--ber-min", type=float, default=0.001)
    p.add_argument("--ber-max", type=float, default=0.10)
    p.add_argument("--ber-steps", type=int, default=15)
    p.add_argument("--keys", type=int, default=20)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--threshold", type=float, default=0.90,
                   help="Success rate threshold for BER threshold calculation")
    p.add_argument("--tail-policy", default="include_partial",
                   choices=["include_partial", "pad_with_zeros", "drop_partial"])
    p.add_argument("--out-dir", type=str, default="results/fig_f")
    p.add_argument("--no-plot", action="store_true")
    return p.parse_args()


def run_ber_point(
    bit_length: int,
    flip_count: int,
    key: bytes,
    rounds: int,
    row_group_size: int,
    col_group_size: int,
    hash_bits: int,
    tail_policy: str,
    seed: int,
    key_id: int,
) -> bool:
    bits = [(i * 3 + 1) % 2 for i in range(bit_length)]
    baseline_grid, meta = bits_to_grid(bits, key=key, rounds=rounds)
    current_grid = [row[:] for row in baseline_grid]
    rng = stable_rng(seed, key_id, flip_count, bit_length)
    flip_indices = rng.sample(range(bit_length), min(flip_count, bit_length))
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
    return restored == bits


def main() -> None:
    args = parse_args()
    lengths = parse_int_list(args.lengths)
    ensure_dir(args.out_dir)

    ber_points = [
        args.ber_min * ((args.ber_max / args.ber_min) ** (i / max(1, args.ber_steps - 1)))
        for i in range(args.ber_steps)
    ]

    write_json(os.path.join(args.out_dir, "config.json"), {
        "lengths": lengths,
        "hash_bits": args.hash_bits,
        "rounds": args.rounds,
        "ber_min": args.ber_min,
        "ber_max": args.ber_max,
        "ber_steps": args.ber_steps,
        "keys": args.keys,
        "threshold": args.threshold,
        "seed": args.seed,
    })

    sweep_rows: list[dict[str, Any]] = []
    threshold_rows: list[dict[str, Any]] = []

    for bit_length in lengths:
        for row_gs, col_gs, cfg_label in GROUP_CONFIGS:
            overhead = compute_overhead_ratio(bit_length, row_gs, col_gs, args.hash_bits)
            best_threshold_ber: float | None = None

            for ber in ber_points:
                flip_count = max(1, round(ber * bit_length))
                actual_ber = flip_count / bit_length
                successes = sum(
                    1 for key_id in range(args.keys)
                    if run_ber_point(
                        bit_length=bit_length,
                        flip_count=flip_count,
                        key=stable_key(args.seed, key_id),
                        rounds=args.rounds,
                        row_group_size=row_gs,
                        col_group_size=col_gs,
                        hash_bits=args.hash_bits,
                        tail_policy=args.tail_policy,
                        seed=args.seed,
                        key_id=key_id,
                    )
                )
                success_rate = successes / args.keys
                if success_rate >= args.threshold:
                    best_threshold_ber = actual_ber

                sweep_rows.append({
                    "bit_length": bit_length,
                    "group_config": cfg_label,
                    "ber_actual": round(actual_ber, 6),
                    "flip_count": flip_count,
                    "success_rate": round(success_rate, 4),
                    "overhead_ratio": round(overhead, 4),
                })
                print(
                    f"L={bit_length:4d}  {cfg_label}  BER={actual_ber:.3f}  "
                    f"success={success_rate:.3f}"
                )

            threshold_rows.append({
                "bit_length": bit_length,
                "group_config": cfg_label,
                "overhead_ratio": round(overhead, 4),
                "threshold_ber": round(best_threshold_ber, 5) if best_threshold_ber else None,
                "threshold_pct": f"{args.threshold:.0%}",
            })

    write_csv(
        os.path.join(args.out_dir, "figure_f_sweep.csv"),
        sweep_rows,
        fieldnames=["bit_length", "group_config", "ber_actual", "flip_count",
                    "success_rate", "overhead_ratio"],
    )
    write_csv(
        os.path.join(args.out_dir, "figure_f_thresholds.csv"),
        threshold_rows,
        fieldnames=["bit_length", "group_config", "overhead_ratio", "threshold_ber", "threshold_pct"],
    )
    print(f"Wrote CSVs to {args.out_dir}/")

    if args.no_plot:
        return

    try:
        import matplotlib.pyplot as plt
    except ModuleNotFoundError as e:
        raise RuntimeError("matplotlib required; use --no-plot to skip") from e

    markers = {"g=1": "o", "g=2": "s", "g=4": "^"}
    colors = {"g=1": "#1f77b4", "g=2": "#ff7f0e", "g=4": "#2ca02c"}

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    fig.suptitle(f"Scalability: {args.hash_bits}-bit hash, success threshold={args.threshold:.0%}", fontsize=13)

    ax_l, ax_r = axes

    # Left: BER threshold vs bit-length
    for _, _, cfg_label in GROUP_CONFIGS:
        subset = [r for r in threshold_rows if r["group_config"] == cfg_label]
        xs = [r["bit_length"] for r in subset]
        ys = [r["threshold_ber"] if r["threshold_ber"] else 0.0 for r in subset]
        ax_l.plot(xs, ys, marker=markers[cfg_label], color=colors[cfg_label],
                  linewidth=2, label=cfg_label)

    ax_l.set_title("Correction threshold BER vs. data-word size")
    ax_l.set_xlabel("Bit-length L")
    ax_l.set_ylabel(f"Max BER at ≥{args.threshold:.0%} success")
    ax_l.set_yscale("log")
    ax_l.grid(True, alpha=0.3)
    ax_l.legend()

    # Right: Success rate curves for each L at g=1
    for bit_length in lengths:
        subset = sorted(
            [r for r in sweep_rows if r["bit_length"] == bit_length and r["group_config"] == "g=1"],
            key=lambda r: r["ber_actual"],
        )
        ax_r.plot(
            [r["ber_actual"] for r in subset],
            [r["success_rate"] for r in subset],
            linewidth=2, marker="o", label=f"L={bit_length}",
        )

    ax_r.set_title("Success rate vs. BER (g=1)")
    ax_r.set_xlabel("BER")
    ax_r.set_ylabel("Correction success rate")
    ax_r.set_xscale("log")
    ax_r.set_ylim(-0.05, 1.05)
    ax_r.grid(True, alpha=0.3)
    ax_r.legend()

    plt.tight_layout()
    out_png = os.path.join(args.out_dir, "figure_f_scalability.png")
    plt.savefig(out_png, dpi=200)
    plt.close()
    print(f"Wrote plot: {out_png}")


if __name__ == "__main__":
    main()
