"""Figure 5: Adaptive grouping — overhead and correction vs block size across grouping strategies.

Panel A: Analytical overhead ratio vs block size for 5 strategies:
         group-4 (merge 4 rows/cols), group-2, default (1:1), split-2, split-4.

Panel B: Empirical max correctable errors at ≥95% success vs block size.
         Shows that grouping reduces overhead at the cost of correction capability,
         while splitting increases capability at the cost of overhead.
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

DEFAULT_BIT_LENGTHS = [256, 512, 1024, 2048, 4096]
DEFAULT_KEYS = 20
DEFAULT_ROUNDS = 8
HASH_BITS = 16
SUCCESS_THRESHOLD = 0.95

STRATEGIES = [
    {"label": "group-4", "row_group_size": 4, "col_group_size": 4, "row_splits": 1, "col_splits": 1},
    {"label": "group-2", "row_group_size": 2, "col_group_size": 2, "row_splits": 1, "col_splits": 1},
    {"label": "default", "row_group_size": 1, "col_group_size": 1, "row_splits": 1, "col_splits": 1},
    {"label": "split-2", "row_group_size": 1, "col_group_size": 1, "row_splits": 2, "col_splits": 2},
    {"label": "split-4", "row_group_size": 1, "col_group_size": 1, "row_splits": 4, "col_splits": 4},
]

STRATEGY_COLORS = {
    "group-4": "#d73027",
    "group-2": "#fc8d59",
    "default": "#4dac26",
    "split-2": "#4575b4",
    "split-4": "#313695",
}


def flip_sweep_counts(L: int) -> list[int]:
    """Flip counts to sweep for a given block size — steps of ~1% of L."""
    step = max(1, int(0.01 * L))
    max_fc = max(step, int(0.15 * L))
    return list(range(step, max_fc + step, step))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Figure 5: Adaptive grouping — overhead and correction vs block size"
    )
    p.add_argument("--bit-lengths", type=str, default=",".join(str(x) for x in DEFAULT_BIT_LENGTHS))
    p.add_argument("--hash-bits", type=int, default=HASH_BITS)
    p.add_argument("--keys", type=int, default=DEFAULT_KEYS)
    p.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out-dir", type=str, default="results/fig5")
    p.add_argument("--no-plot", action="store_true")
    p.add_argument("--parallel", action="store_true")
    p.add_argument("--workers", type=int, default=0)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    bit_lengths = parse_int_list(args.bit_lengths)
    if not bit_lengths:
        raise ValueError("--bit-lengths must be non-empty")
    hash_bits = args.hash_bits
    ensure_dir(args.out_dir)
    write_json(os.path.join(args.out_dir, "config.json"), {
        "bit_lengths": bit_lengths,
        "hash_bits": hash_bits,
        "keys": args.keys,
        "rounds": args.rounds,
        "strategies": [s["label"] for s in STRATEGIES],
        "success_threshold": SUCCESS_THRESHOLD,
    })

    # --- Panel A: analytical overhead ---
    plot_lengths = sorted(set(bit_lengths + [128, 256, 512, 1024, 2048, 4096, 8192, 16384]))
    overhead_rows: list[dict[str, Any]] = []
    for L in plot_lengths:
        row: dict[str, Any] = {"bit_length": L}
        for s in STRATEGIES:
            ratio = compute_overhead_ratio(
                L, s["row_group_size"], s["col_group_size"], hash_bits,
                row_splits=s["row_splits"], col_splits=s["col_splits"],
            )
            row[f"overhead_{s['label']}"] = ratio
        overhead_rows.append(row)

    overhead_fieldnames = ["bit_length"] + [f"overhead_{s['label']}" for s in STRATEGIES]
    write_csv(os.path.join(args.out_dir, "fig5_overhead.csv"), overhead_rows, overhead_fieldnames)

    # --- Panel B: empirical max-correctable flips at ≥95% success ---
    bits_by_length = {L: [(i * 3 + 1) % 2 for i in range(L)] for L in bit_lengths}

    all_tasks: list[tuple] = []
    all_metas: list[tuple] = []  # (strategy_label, L, flip_count, key_id)

    for s in STRATEGIES:
        for L in bit_lengths:
            for flip_count in flip_sweep_counts(L):
                for key_id in range(args.keys):
                    key = stable_key(args.seed, key_id)
                    rng = stable_rng(args.seed, key_id, flip_count, hash_bits, L, s["label"])
                    flip_indices = get_flip_indices(flip_count, L, "random", rng)
                    all_tasks.append((
                        bits_by_length[L], key, args.rounds, flip_indices,
                        s["row_group_size"], s["col_group_size"],
                        hash_bits, "include_partial", None, 0, "crc",
                        s["row_splits"], s["col_splits"],
                    ))
                    all_metas.append((s["label"], L, flip_count, key_id))

    print(f"Running {len(all_tasks)} trials across {len(STRATEGIES)} strategies × {len(bit_lengths)} block sizes...")
    if args.parallel:
        flat_results = run_trials_parallel(all_tasks, args.workers)
    else:
        flat_results = run_trials_serial(all_tasks)

    # Collect per-trial rows
    empirical_rows: list[dict[str, Any]] = []
    for trial, (label, L, flip_count, key_id) in zip(flat_results, all_metas):
        empirical_rows.append({
            "strategy": label,
            "bit_length": L,
            "flip_count": flip_count,
            "key_id": key_id,
            "fully_corrected": int(trial["fully_corrected"]),
            "solve_time_ms": trial["solve_time_ms"],
        })

    write_csv(os.path.join(args.out_dir, "fig5_empirical.csv"), empirical_rows,
              ["strategy", "bit_length", "flip_count", "key_id", "fully_corrected", "solve_time_ms"])

    # Compute max correctable per (strategy, block size)
    max_correctable: dict[tuple[str, int], int] = {}
    for s in STRATEGIES:
        for L in bit_lengths:
            best = 0
            for flip_count in flip_sweep_counts(L):
                subset = [
                    r for r in empirical_rows
                    if r["strategy"] == s["label"] and r["bit_length"] == L and r["flip_count"] == flip_count
                ]
                if not subset:
                    continue
                rate = sum(r["fully_corrected"] for r in subset) / len(subset)
                if rate >= SUCCESS_THRESHOLD:
                    best = flip_count
            max_correctable[(s["label"], L)] = best
            overhead = compute_overhead_ratio(
                L, s["row_group_size"], s["col_group_size"], hash_bits,
                row_splits=s["row_splits"], col_splits=s["col_splits"],
            )
            print(f"  {s['label']:8s}  L={L:6d}  overhead={overhead:.1%}  max_flips_at_{int(SUCCESS_THRESHOLD*100)}pct={best}")

    if args.no_plot:
        return

    try:
        import matplotlib.pyplot as plt
        import matplotlib.ticker as ticker
    except ModuleNotFoundError as e:
        raise RuntimeError("matplotlib required; install it or use --no-plot") from e

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
    fig.suptitle(
        f"Adaptive Grouping: Approximate ECC ({hash_bits}-bit CRC)",
        fontsize=13, fontweight="bold",
    )

    # Panel A: overhead vs block size
    for s in STRATEGIES:
        xs = [r["bit_length"] for r in overhead_rows]
        ys = [r[f"overhead_{s['label']}"] * 100 for r in overhead_rows]
        color = STRATEGY_COLORS[s["label"]]
        linestyle = "--" if "group" in s["label"] else ("-" if s["label"] == "default" else ":")
        ax1.plot(xs, ys, linestyle=linestyle, marker="o", markersize=4,
                 color=color, linewidth=2, label=s["label"])

    ax1.set_xscale("log", base=2)
    ax1.set_xlabel("Block size (bits)")
    ax1.set_ylabel("Overhead (%)")
    ax1.set_title("Overhead ratio vs block size\n(grouping reduces, splits increase overhead)")
    ax1.grid(True, alpha=0.3)
    ax1.legend(fontsize=9)
    ax1.yaxis.set_major_formatter(ticker.PercentFormatter())
    ax1.xaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f"{int(x):,}"))

    # Panel B: max correctable flips vs block size
    for s in STRATEGIES:
        xs = sorted(bit_lengths)
        ys = [max_correctable.get((s["label"], L), 0) for L in xs]
        color = STRATEGY_COLORS[s["label"]]
        linestyle = "--" if "group" in s["label"] else ("-" if s["label"] == "default" else ":")
        ax2.plot(xs, ys, linestyle=linestyle, marker="s", markersize=5,
                 color=color, linewidth=2, label=s["label"])

    ax2.set_xscale("log", base=2)
    ax2.set_xlabel("Block size (bits)")
    ax2.set_ylabel(f"Max correctable flips (≥{int(SUCCESS_THRESHOLD*100)}% success)")
    ax2.set_title(f"Max correctable errors vs block size\n(BER sweep, ≥{int(SUCCESS_THRESHOLD*100)}% success threshold)")
    ax2.grid(True, alpha=0.3)
    ax2.legend(fontsize=9)
    ax2.xaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f"{int(x):,}"))

    plt.tight_layout()
    out_path = os.path.join(args.out_dir, "fig5_adaptive_grouping.png")
    plt.savefig(out_path, dpi=200)
    plt.close()
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
