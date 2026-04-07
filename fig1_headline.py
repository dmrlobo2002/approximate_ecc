"""Figure 1: Headline — Approximate ECC corrects 200+ flips in a 4096-bit block.

Shows success rate and solve time vs flip count for multiple hash configurations.
Demonstrates that near-100% correction is maintained across a wide BER range.
"""
from __future__ import annotations

import argparse
import math
import os
from typing import Any

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
from experiments.trial_runner import get_flip_indices, run_trials_parallel, run_trials_serial

DEFAULT_BIT_LENGTH = 4096
DEFAULT_MAX_BER = 0.065  # up to ~266 flips
DEFAULT_KEYS = 30
DEFAULT_ROUNDS = 8
CONFIGS = [
    (8, 1),   # (hash_bits, group_size)
    (16, 1),
    (32, 1),
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Figure 1: Success rate and solve time vs flip count at large block size"
    )
    p.add_argument("--bit-length", type=int, default=DEFAULT_BIT_LENGTH)
    p.add_argument("--max-ber", type=float, default=DEFAULT_MAX_BER)
    p.add_argument("--keys", type=int, default=DEFAULT_KEYS)
    p.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out-dir", type=str, default="results/fig1")
    p.add_argument("--no-plot", action="store_true")
    p.add_argument("--parallel", action="store_true")
    p.add_argument("--workers", type=int, default=0)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    max_flip_count = max(1, int(args.max_ber * args.bit_length))
    flip_counts = list(range(10, max_flip_count + 1, 10))  # step by 10 for speed
    if flip_counts[-1] != max_flip_count:
        flip_counts.append(max_flip_count)

    ensure_dir(args.out_dir)
    write_json(os.path.join(args.out_dir, "config.json"), {
        "bit_length": args.bit_length,
        "max_ber": args.max_ber,
        "max_flip_count": max_flip_count,
        "keys": args.keys,
        "rounds": args.rounds,
        "seed": args.seed,
        "configs": CONFIGS,
    })

    bits = [(i * 3 + 1) % 2 for i in range(args.bit_length)]

    # Build all tasks upfront so RNG state is determined in order
    all_tasks: list[tuple] = []
    all_metas: list[tuple] = []
    for hash_bits, group_size in CONFIGS:
        for fc in flip_counts:
            for key_id in range(args.keys):
                key = stable_key(args.seed, key_id)
                rng = stable_rng(args.seed, key_id, fc, hash_bits, "random")
                flip_indices = get_flip_indices(fc, args.bit_length, "random", rng)
                all_tasks.append((
                    bits, key, args.rounds, flip_indices,
                    group_size, group_size, hash_bits, "include_partial", None, 0, "crc",
                ))
                all_metas.append((hash_bits, group_size, fc, key_id))

    print(f"Running {len(all_tasks)} trials (bit_length={args.bit_length}, max_flips={max_flip_count})...")
    if args.parallel:
        flat_results = run_trials_parallel(all_tasks, args.workers)
    else:
        flat_results = run_trials_serial(all_tasks)

    rows: list[dict[str, Any]] = []
    for trial, (hash_bits, group_size, fc, key_id) in zip(flat_results, all_metas):
        rows.append({
            "hash_bits": hash_bits,
            "group_size": group_size,
            "flip_count": fc,
            "key_id": key_id,
            "ber": fc / args.bit_length,
            "overhead_ratio": compute_overhead_ratio(args.bit_length, group_size, group_size, hash_bits),
            "fully_corrected": int(trial["fully_corrected"]),
            "mismatched_before": trial["mismatched_before"],
            "mismatched_after": trial["mismatched_after"],
            "total_combos_evaluated": trial["total_combos_evaluated"],
            "solve_time_ms": trial["solve_time_ms"],
        })

    # Print summary
    for hash_bits, group_size in CONFIGS:
        overhead = compute_overhead_ratio(args.bit_length, group_size, group_size, hash_bits)
        for fc in flip_counts:
            subset = [r for r in rows if r["hash_bits"] == hash_bits and r["group_size"] == group_size and r["flip_count"] == fc]
            rate = sum(r["fully_corrected"] for r in subset) / len(subset)
            print(f"  hash_bits={hash_bits:2d}  group={group_size}  overhead={overhead:.1%}  flips={fc:4d}  success={rate:.1%}")

    write_csv(os.path.join(args.out_dir, "fig1_data.csv"), rows, [
        "hash_bits", "group_size", "flip_count", "key_id", "ber", "overhead_ratio",
        "fully_corrected", "mismatched_before", "mismatched_after",
        "total_combos_evaluated", "solve_time_ms",
    ])

    if args.no_plot:
        return

    try:
        import matplotlib.pyplot as plt
        import matplotlib.ticker as ticker
    except ModuleNotFoundError as e:
        raise RuntimeError("matplotlib required; install it or use --no-plot") from e

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
    fig.suptitle(
        f"Approximate ECC: {args.bit_length}-bit block — correction vs flip count",
        fontsize=14, fontweight="bold",
    )

    colors = {8: "#e41a1c", 16: "#377eb8", 32: "#4daf4a"}

    for hash_bits, group_size in CONFIGS:
        overhead = compute_overhead_ratio(args.bit_length, group_size, group_size, hash_bits)
        overhead_pct = overhead * 100
        label = f"{hash_bits}-bit CRC  ({overhead_pct:.0f}% overhead)"
        color = colors[hash_bits]

        xs, ys_rate, yerr_rate = [], [], []
        xs2, ys_time, yerr_time = [], [], []
        for fc in flip_counts:
            subset = [r for r in rows if r["hash_bits"] == hash_bits and r["group_size"] == group_size and r["flip_count"] == fc]
            n = len(subset)
            rate = sum(r["fully_corrected"] for r in subset) / n
            se = math.sqrt(rate * (1 - rate) / n) if n > 1 and 0 < rate < 1 else 0.0
            xs.append(fc)
            ys_rate.append(rate * 100)
            yerr_rate.append(se * 100)

            times = [r["solve_time_ms"] for r in subset]
            a = agg(times)
            xs2.append(fc)
            ys_time.append(a.mean)
            yerr_time.append(a.sem)

        ax1.errorbar(xs, ys_rate, yerr=yerr_rate, marker="o", linewidth=2, capsize=3,
                     label=label, color=color)
        ax2.errorbar(xs2, ys_time, yerr=yerr_time, marker="o", linewidth=2, capsize=3,
                     label=label, color=color)

    ax1.axhline(100, linestyle="--", color="gray", linewidth=1, alpha=0.5)
    ax1.axvline(200, linestyle=":", color="black", linewidth=1.5, alpha=0.7, label="200 flips")
    ax1.set_title("Success rate vs injected bit-flips")
    ax1.set_xlabel("Injected bit-flips")
    ax1.set_ylabel("Success rate (%)")
    ax1.set_ylim(-5, 105)
    ax1.grid(True, alpha=0.3)
    ax1.legend(fontsize=9)
    ax1_ber = ax1.secondary_xaxis("top")
    ax1_ber.set_xlabel("Bit Error Rate (BER)", fontsize=9)
    ber_ticks = [fc for fc in flip_counts[::3]]
    ax1_ber.set_xticks(ber_ticks)
    ax1_ber.set_xticklabels([f"{fc/args.bit_length:.1%}" for fc in ber_ticks], fontsize=7, rotation=45)

    ax2.set_title("Mean solve time vs injected bit-flips")
    ax2.set_xlabel("Injected bit-flips")
    ax2.set_ylabel("Mean solve time (ms)")
    ax2.grid(True, alpha=0.3)
    ax2.legend(fontsize=9)

    plt.tight_layout()
    out_path = os.path.join(args.out_dir, "fig1_headline.png")
    plt.savefig(out_path, dpi=200)
    plt.close()
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
