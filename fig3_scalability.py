"""Figure 3: Scalability — overhead ratio and correction success across block sizes.

Panel A: Overhead ratio vs block size for our scheme (analytical) vs BCH at various t.
         Our overhead decreases as O(1/sqrt(L)), while BCH overhead for fixed t stays constant.

Panel B: Empirical success rate at BER=5% vs block size (hash_bits=16, group_size=1).
         Shows correction remains strong as blocks grow.
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
from experiments.ecc_comparison import bch_overhead
from experiments.trial_runner import get_flip_indices, run_trials_parallel, run_trials_serial

DEFAULT_BIT_LENGTHS = [256, 512, 1024, 2048, 4096]
DEFAULT_KEYS = 20
DEFAULT_BER = 0.05
DEFAULT_ROUNDS = 8
HASH_BITS = 16
GROUP_SIZE = 1
BCH_T_VALUES = [10, 50, 100, 200]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Figure 3: Scalability — overhead and correction vs block size"
    )
    p.add_argument("--bit-lengths", type=str, default=",".join(str(x) for x in DEFAULT_BIT_LENGTHS))
    p.add_argument("--ber", type=float, default=DEFAULT_BER)
    p.add_argument("--keys", type=int, default=DEFAULT_KEYS)
    p.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out-dir", type=str, default="results/fig3")
    p.add_argument("--no-plot", action="store_true")
    p.add_argument("--parallel", action="store_true")
    p.add_argument("--workers", type=int, default=0)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    bit_lengths = parse_int_list(args.bit_lengths)
    if not bit_lengths:
        raise ValueError("--bit-lengths must be non-empty")
    ensure_dir(args.out_dir)
    write_json(os.path.join(args.out_dir, "config.json"), {
        "bit_lengths": bit_lengths,
        "ber": args.ber,
        "keys": args.keys,
        "rounds": args.rounds,
        "hash_bits": HASH_BITS,
        "group_size": GROUP_SIZE,
        "bch_t_values": BCH_T_VALUES,
    })

    # --- Panel A: analytical overhead curves ---
    # Extend block size range for the overhead plot
    plot_lengths = sorted(set(bit_lengths + [128, 256, 512, 1024, 2048, 4096, 8192, 16384]))

    overhead_rows: list[dict[str, Any]] = []
    for L in plot_lengths:
        our_overhead = compute_overhead_ratio(L, GROUP_SIZE, GROUP_SIZE, HASH_BITS)
        row: dict[str, Any] = {"bit_length": L, "our_overhead_ratio": our_overhead}
        for t in BCH_T_VALUES:
            info = bch_overhead(L, t)
            row[f"bch_t{t}_overhead_ratio"] = info["overhead_ratio"]
        overhead_rows.append(row)

    fieldnames = ["bit_length", "our_overhead_ratio"] + [f"bch_t{t}_overhead_ratio" for t in BCH_T_VALUES]
    write_csv(os.path.join(args.out_dir, "fig3_overhead.csv"), overhead_rows, fieldnames)

    # --- Panel B: empirical success rate at fixed BER ---
    bits_by_length = {L: [(i * 3 + 1) % 2 for i in range(L)] for L in bit_lengths}

    all_tasks: list[tuple] = []
    all_metas: list[tuple] = []
    for L in bit_lengths:
        bits = bits_by_length[L]
        flip_count = max(1, int(args.ber * L))
        for key_id in range(args.keys):
            key = stable_key(args.seed, key_id)
            rng = stable_rng(args.seed, key_id, flip_count, HASH_BITS, L, "random")
            flip_indices = get_flip_indices(flip_count, L, "random", rng)
            all_tasks.append((
                bits, key, args.rounds, flip_indices,
                GROUP_SIZE, GROUP_SIZE, HASH_BITS, "include_partial", None, 0, "crc", 1, 1,
            ))
            all_metas.append((L, flip_count, key_id))

    print(f"Running {len(all_tasks)} trials at BER={args.ber:.1%}...")
    if args.parallel:
        flat_results = run_trials_parallel(all_tasks, args.workers)
    else:
        flat_results = run_trials_serial(all_tasks)

    empirical_rows: list[dict[str, Any]] = []
    for trial, (L, flip_count, key_id) in zip(flat_results, all_metas):
        empirical_rows.append({
            "bit_length": L,
            "flip_count": flip_count,
            "actual_ber": flip_count / L,
            "key_id": key_id,
            "overhead_ratio": compute_overhead_ratio(L, GROUP_SIZE, GROUP_SIZE, HASH_BITS),
            "fully_corrected": int(trial["fully_corrected"]),
            "solve_time_ms": trial["solve_time_ms"],
        })

    write_csv(os.path.join(args.out_dir, "fig3_empirical.csv"), empirical_rows,
              ["bit_length", "flip_count", "actual_ber", "key_id", "overhead_ratio",
               "fully_corrected", "solve_time_ms"])

    for L in bit_lengths:
        subset = [r for r in empirical_rows if r["bit_length"] == L]
        rate = sum(r["fully_corrected"] for r in subset) / len(subset)
        fc = subset[0]["flip_count"] if subset else 0
        overhead = compute_overhead_ratio(L, GROUP_SIZE, GROUP_SIZE, HASH_BITS)
        print(f"  L={L:6d}  flips={fc:5d} (BER={args.ber:.1%})  overhead={overhead:.1%}  success={rate:.1%}")

    if args.no_plot:
        return

    try:
        import matplotlib.pyplot as plt
        import matplotlib.ticker as ticker
    except ModuleNotFoundError as e:
        raise RuntimeError("matplotlib required; install it or use --no-plot") from e

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
    fig.suptitle(
        f"Scalability: Approximate ECC  (hash_bits={HASH_BITS}, group_size={GROUP_SIZE})",
        fontsize=13, fontweight="bold",
    )

    # Panel A: overhead ratio vs block size
    our_xs = [r["bit_length"] for r in overhead_rows]
    our_ys = [r["our_overhead_ratio"] * 100 for r in overhead_rows]
    ax1.plot(our_xs, our_ys, "o-", color="#377eb8", linewidth=2.5, markersize=5,
             label=f"Ours ({HASH_BITS}-bit CRC, gs={GROUP_SIZE})")

    bch_colors = {10: "#e41a1c", 50: "#ff7f00", 100: "#984ea3", 200: "#a65628"}
    for t in BCH_T_VALUES:
        bch_xs = [r["bit_length"] for r in overhead_rows]
        bch_ys = [r[f"bch_t{t}_overhead_ratio"] * 100 for r in overhead_rows]
        ax1.plot(bch_xs, bch_ys, "--", linewidth=1.5, color=bch_colors.get(t, "gray"),
                 label=f"BCH t={t}")

    ax1.set_xscale("log", base=2)
    ax1.set_xlabel("Block size (bits)")
    ax1.set_ylabel("Overhead (%)")
    ax1.set_title("Overhead ratio vs block size")
    ax1.grid(True, alpha=0.3)
    ax1.legend(fontsize=9)
    ax1.yaxis.set_major_formatter(ticker.PercentFormatter())
    ax1.xaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f"{int(x):,}"))

    # Add annotation showing our scheme shrinks as 1/sqrt(L)
    ax1.annotate("Our overhead ∝ 1/√L\n(improves with block size)",
                 xy=(4096, compute_overhead_ratio(4096, GROUP_SIZE, GROUP_SIZE, HASH_BITS) * 100),
                 xytext=(0.45, 0.55), textcoords="axes fraction",
                 arrowprops=dict(arrowstyle="->", color="#377eb8"),
                 fontsize=9, color="#377eb8")

    # Panel B: success rate at BER=5% vs block size
    success_xs, success_ys, success_err = [], [], []
    for L in bit_lengths:
        subset = [r for r in empirical_rows if r["bit_length"] == L]
        n = len(subset)
        rate = sum(r["fully_corrected"] for r in subset) / n
        se = math.sqrt(rate * (1 - rate) / n) if n > 1 and 0 < rate < 1 else 0.0
        success_xs.append(L)
        success_ys.append(rate * 100)
        success_err.append(se * 100)

    ax2.errorbar(success_xs, success_ys, yerr=success_err, marker="o", linewidth=2.5,
                 capsize=4, color="#377eb8",
                 label=f"{HASH_BITS}-bit CRC (gs={GROUP_SIZE})")
    ax2.axhline(100, linestyle="--", color="gray", linewidth=1, alpha=0.5)
    ax2.set_xscale("log", base=2)
    ax2.set_xlabel("Block size (bits)")
    ax2.set_ylabel("Success rate (%)")
    ax2.set_title(f"Success rate at BER={args.ber:.0%} vs block size")
    ax2.set_ylim(-5, 105)
    ax2.grid(True, alpha=0.3)
    ax2.legend(fontsize=9)
    ax2.xaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f"{int(x):,}"))

    plt.tight_layout()
    out_path = os.path.join(args.out_dir, "fig3_scalability.png")
    plt.savefig(out_path, dpi=200)
    plt.close()
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
