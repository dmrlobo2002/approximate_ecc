"""Figure 5: Adaptive grouping — overhead and correction vs block size across grouping strategies.

Panel A: Analytical overhead ratio vs block size for 5 strategies:
         group-4 (merge 4 rows/cols), group-2, default (1:1), split-2, split-4.

Panel B: Empirical max correctable errors at ≥95% success vs block size.
         Shows that grouping reduces overhead at the cost of correction capability,
         while splitting increases capability at the cost of overhead.

Panel C: Hash size sweep — max correctable flips vs block size for CRC-8/16/32
         using the default strategy (group_size=1, splits=1) on smaller block sizes.
         Shows that CRC-8 achieves similar correction to CRC-32 at 4× less overhead.
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
MAX_BITS_PER_NODE = 64  # skip strategy+block_size combos where solver is intractable
DEFAULT_MAX_COMBOS = 500_000  # per-trial combo budget; prevents hanging on hard instances

# Hash sweep (Panel C) — default strategy only, smaller block sizes
HASH_SWEEP_BITS = [8, 16, 32]
DEFAULT_HASH_SWEEP_LENGTHS = [128, 256, 512, 1024]
HASH_SWEEP_COLORS = {8: "#e41a1c", 16: "#377eb8", 32: "#4daf4a"}


def _bits_per_node(bit_length: int, row_group_size: int, col_group_size: int,
                   row_splits: int = 1, col_splits: int = 1) -> int:
    """Largest node size (in source bits) for a given strategy and block size.
    Splits divide each group's column/row coverage, reducing bits per node.
    """
    n = math.ceil(math.sqrt(bit_length))
    bits_per_row_node = math.ceil(n * row_group_size / row_splits)
    bits_per_col_node = math.ceil(n * col_group_size / col_splits)
    return max(bits_per_row_node, bits_per_col_node)
DEFAULT_KEYS = 20
DEFAULT_ROUNDS = 8
HASH_BITS = 32
SUCCESS_THRESHOLD = 0.95

STRATEGIES = [
    {"label": "group-4", "row_group_size": 4, "col_group_size": 4, "row_splits": 1, "col_splits": 1},
    {"label": "group-2", "row_group_size": 2, "col_group_size": 2, "row_splits": 1, "col_splits": 1},
    {"label": "default", "row_group_size": 1, "col_group_size": 1, "row_splits": 1, "col_splits": 1},
    {"label": "split-2", "row_group_size": 1, "col_group_size": 1, "row_splits": 2, "col_splits": 2},
    {"label": "split-4", "row_group_size": 1, "col_group_size": 1, "row_splits": 4, "col_splits": 4},
]

BCH_T_VALUES = [5, 20, 50]
BCH_COLORS = {5: "#8c510a", 20: "#bf812d", 50: "#dfc27d"}
BCH_CHUNK_SIZE = 256  # BCH applied to 256-bit chunks for L > 256

STRATEGY_COLORS = {
    "group-4": "#d73027",
    "group-2": "#fc8d59",
    "default": "#4dac26",
    "split-2": "#4575b4",
    "split-4": "#313695",
}


def bch_overhead_ratio(L: int, t: int) -> float:
    """BCH overhead ratio for block size L with correction capability t.
    For L <= BCH_CHUNK_SIZE: exact analytical overhead via cyclotomic cosets.
    For L > BCH_CHUNK_SIZE: constant — modeled as ceil(L/256) x BCH(256, t) chunks.
    """
    if L <= BCH_CHUNK_SIZE:
        return bch_overhead(L, t)["overhead_ratio"]
    return bch_overhead(BCH_CHUNK_SIZE, t)["parity_bits"] / BCH_CHUNK_SIZE


def bch_max_correctable(L: int, t: int) -> int:
    """Total errors BCH can correct across all 256-bit chunks covering L bits."""
    return math.ceil(L / BCH_CHUNK_SIZE) * t


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
    p.add_argument("--max-combos", type=int, default=DEFAULT_MAX_COMBOS,
                   help="Per-trial combo budget (0 = unlimited, not recommended)")
    p.add_argument("--hash-sweep-lengths", type=str,
                   default=",".join(str(x) for x in DEFAULT_HASH_SWEEP_LENGTHS),
                   help="Block sizes for hash-width sweep (Panel C)")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    bit_lengths = parse_int_list(args.bit_lengths)
    if not bit_lengths:
        raise ValueError("--bit-lengths must be non-empty")
    hash_bits = args.hash_bits
    ensure_dir(args.out_dir)
    max_combos = args.max_combos if args.max_combos > 0 else None
    hash_sweep_lengths = parse_int_list(args.hash_sweep_lengths)
    write_json(os.path.join(args.out_dir, "config.json"), {
        "bit_lengths": bit_lengths,
        "hash_bits": hash_bits,
        "keys": args.keys,
        "rounds": args.rounds,
        "strategies": [s["label"] for s in STRATEGIES],
        "success_threshold": SUCCESS_THRESHOLD,
        "max_combos": max_combos,
        "hash_sweep_bits": HASH_SWEEP_BITS,
        "hash_sweep_lengths": hash_sweep_lengths,
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
        for t in BCH_T_VALUES:
            row[f"overhead_bch_t{t}"] = bch_overhead_ratio(L, t)
        overhead_rows.append(row)

    overhead_fieldnames = (
        ["bit_length"]
        + [f"overhead_{s['label']}" for s in STRATEGIES]
        + [f"overhead_bch_t{t}" for t in BCH_T_VALUES]
    )
    write_csv(os.path.join(args.out_dir, "fig5_overhead.csv"), overhead_rows, overhead_fieldnames)

    # --- Panel B: empirical max-correctable flips at ≥95% success ---
    all_lengths_needed = sorted(set(bit_lengths) | set(hash_sweep_lengths))
    bits_by_length = {L: [(i * 3 + 1) % 2 for i in range(L)] for L in all_lengths_needed}

    all_tasks: list[tuple] = []
    all_metas: list[tuple] = []  # (strategy_label, L, flip_count, key_id)
    skipped_cells: set[tuple[str, int]] = set()  # (strategy_label, L) pairs skipped as intractable

    for s in STRATEGIES:
        for L in bit_lengths:
            node_bits = _bits_per_node(L, s["row_group_size"], s["col_group_size"], s["row_splits"], s["col_splits"])
            if node_bits > MAX_BITS_PER_NODE:
                skipped_cells.add((s["label"], L))
                print(f"  Skipping {s['label']} at L={L} — node too large ({node_bits} bits/node > {MAX_BITS_PER_NODE})")
                continue
            for flip_count in flip_sweep_counts(L):
                for key_id in range(args.keys):
                    key = stable_key(args.seed, key_id)
                    rng = stable_rng(args.seed, key_id, flip_count, hash_bits, L, s["label"])
                    flip_indices = get_flip_indices(flip_count, L, "random", rng)
                    all_tasks.append((
                        bits_by_length[L], key, args.rounds, flip_indices,
                        s["row_group_size"], s["col_group_size"],
                        hash_bits, "include_partial", max_combos, 0, "crc",
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
    max_correctable: dict[tuple[str, int], int | None] = {}
    for s in STRATEGIES:
        for L in bit_lengths:
            overhead = compute_overhead_ratio(
                L, s["row_group_size"], s["col_group_size"], hash_bits,
                row_splits=s["row_splits"], col_splits=s["col_splits"],
            )
            if (s["label"], L) in skipped_cells:
                max_correctable[(s["label"], L)] = None
                print(f"  {s['label']:8s}  L={L:6d}  overhead={overhead:.1%}  SKIPPED (node too large)")
                continue
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
            print(f"  {s['label']:8s}  L={L:6d}  overhead={overhead:.1%}  max_flips_at_{int(SUCCESS_THRESHOLD*100)}pct={best}")

    # --- Panel C: hash size sweep (default strategy, smaller block sizes) ---
    hash_sweep_tasks: list[tuple] = []
    hash_sweep_metas: list[tuple] = []  # (hb, L, flip_count, key_id)

    for hb in HASH_SWEEP_BITS:
        for L in hash_sweep_lengths:
            for flip_count in flip_sweep_counts(L):
                for key_id in range(args.keys):
                    key = stable_key(args.seed, key_id)
                    rng = stable_rng(args.seed, key_id, flip_count, hb, L, "hash_sweep")
                    flip_indices = get_flip_indices(flip_count, L, "random", rng)
                    hash_sweep_tasks.append((
                        bits_by_length[L], key, args.rounds, flip_indices,
                        1, 1, hb, "include_partial", max_combos, 0, "crc", 1, 1,
                    ))
                    hash_sweep_metas.append((hb, L, flip_count, key_id))

    print(f"Running {len(hash_sweep_tasks)} hash-sweep trials ({len(HASH_SWEEP_BITS)} hash widths × {len(hash_sweep_lengths)} block sizes)...")
    if args.parallel:
        hash_sweep_results = run_trials_parallel(hash_sweep_tasks, args.workers)
    else:
        hash_sweep_results = run_trials_serial(hash_sweep_tasks)

    hash_sweep_rows: list[dict[str, Any]] = []
    for trial, (hb, L, flip_count, key_id) in zip(hash_sweep_results, hash_sweep_metas):
        hash_sweep_rows.append({
            "hash_bits": hb,
            "bit_length": L,
            "flip_count": flip_count,
            "key_id": key_id,
            "fully_corrected": int(trial["fully_corrected"]),
            "solve_time_ms": trial["solve_time_ms"],
        })

    write_csv(os.path.join(args.out_dir, "fig5_hash_sweep.csv"), hash_sweep_rows,
              ["hash_bits", "bit_length", "flip_count", "key_id", "fully_corrected", "solve_time_ms"])

    hash_max_correctable: dict[tuple[int, int], int] = {}
    for hb in HASH_SWEEP_BITS:
        for L in hash_sweep_lengths:
            best = 0
            for flip_count in flip_sweep_counts(L):
                subset = [
                    r for r in hash_sweep_rows
                    if r["hash_bits"] == hb and r["bit_length"] == L and r["flip_count"] == flip_count
                ]
                if not subset:
                    continue
                rate = sum(r["fully_corrected"] for r in subset) / len(subset)
                if rate >= SUCCESS_THRESHOLD:
                    best = flip_count
            hash_max_correctable[(hb, L)] = best
            overhead = compute_overhead_ratio(L, 1, 1, hb)
            print(f"  CRC-{hb:2d}  L={L:6d}  overhead={overhead:.1%}  max_flips_at_{int(SUCCESS_THRESHOLD*100)}pct={best}")

    if args.no_plot:
        return

    try:
        import matplotlib.pyplot as plt
        import matplotlib.ticker as ticker
    except ModuleNotFoundError as e:
        raise RuntimeError("matplotlib required; install it or use --no-plot") from e

    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(20, 6))
    fig.suptitle(
        f"Adaptive Grouping: Approximate ECC (Panels A–B: {hash_bits}-bit CRC; Panel C: hash sweep)",
        fontsize=13, fontweight="bold",
    )

    # Panel A: overhead vs block size
    xs = [r["bit_length"] for r in overhead_rows]
    for s in STRATEGIES:
        ys = [r[f"overhead_{s['label']}"] * 100 for r in overhead_rows]
        color = STRATEGY_COLORS[s["label"]]
        linestyle = "--" if "group" in s["label"] else ("-" if s["label"] == "default" else ":")
        ax1.plot(xs, ys, linestyle=linestyle, marker="o", markersize=4,
                 color=color, linewidth=2, label=s["label"])
    for t in BCH_T_VALUES:
        ys = [r[f"overhead_bch_t{t}"] * 100 for r in overhead_rows]
        ax1.plot(xs, ys, linestyle=":", marker="^", markersize=3,
                 color=BCH_COLORS[t], linewidth=1.5, label=f"BCH t={t}")

    ax1.set_xscale("log", base=2)
    ax1.set_xlabel("Block size (bits)")
    ax1.set_ylabel("Overhead (%)")
    ax1.set_title("Overhead ratio vs block size\n(grouping reduces, splits increase overhead)")
    ax1.grid(True, alpha=0.3)
    ax1.legend(fontsize=9)
    ax1.yaxis.set_major_formatter(ticker.PercentFormatter())
    ax1.xaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f"{int(x):,}"))

    # Panel B: max correctable flips vs block size
    all_xs = sorted(bit_lengths)
    for s in STRATEGIES:
        all_ys = [max_correctable.get((s["label"], L)) for L in all_xs]
        xs = [x for x, y in zip(all_xs, all_ys) if y is not None]
        ys = [y for y in all_ys if y is not None]
        if not xs:
            continue
        color = STRATEGY_COLORS[s["label"]]
        linestyle = "--" if "group" in s["label"] else ("-" if s["label"] == "default" else ":")
        ax2.plot(xs, ys, linestyle=linestyle, marker="s", markersize=5,
                 color=color, linewidth=2, label=s["label"])
    for t in BCH_T_VALUES:
        ys = [bch_max_correctable(L, t) for L in all_xs]
        ax2.plot(all_xs, ys, linestyle=":", marker="^", markersize=3,
                 color=BCH_COLORS[t], linewidth=1.5, label=f"BCH t={t}")

    ax2.set_xscale("log", base=2)
    ax2.set_xlabel("Block size (bits)")
    ax2.set_ylabel(f"Max correctable flips (≥{int(SUCCESS_THRESHOLD*100)}% success)")
    ax2.set_title(f"Max correctable errors vs block size\n(BER sweep, ≥{int(SUCCESS_THRESHOLD*100)}% success threshold)")
    ax2.grid(True, alpha=0.3)
    ax2.legend(fontsize=9)
    ax2.xaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f"{int(x):,}"))

    # Panel C: hash size sweep — max correctable flips vs block size, one line per CRC width
    for hb in HASH_SWEEP_BITS:
        xs = sorted(hash_sweep_lengths)
        ys = [hash_max_correctable.get((hb, L), 0) for L in xs]
        overhead_pcts = [compute_overhead_ratio(L, 1, 1, hb) * 100 for L in xs]
        color = HASH_SWEEP_COLORS[hb]
        label = f"CRC-{hb} (~{overhead_pcts[len(xs)//2]:.0f}% OH at {xs[len(xs)//2]:,}b)"
        ax3.plot(xs, ys, linestyle="-", marker="o", markersize=5,
                 color=color, linewidth=2, label=label)

    ax3.set_xscale("log", base=2)
    ax3.set_xlabel("Block size (bits)")
    ax3.set_ylabel(f"Max correctable flips (≥{int(SUCCESS_THRESHOLD*100)}% success)")
    ax3.set_title(f"Hash width sweep (default strategy)\n(≥{int(SUCCESS_THRESHOLD*100)}% success threshold)")
    ax3.grid(True, alpha=0.3)
    ax3.legend(fontsize=9)
    ax3.xaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f"{int(x):,}"))

    plt.tight_layout()
    out_path = os.path.join(args.out_dir, "fig5_adaptive_grouping.png")
    plt.savefig(out_path, dpi=200)
    plt.close()
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
