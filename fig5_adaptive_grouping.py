"""Figure 5: Adaptive grouping — overhead and correction vs block size across grouping strategies.

Panel A (×4 hash sizes): Analytical overhead ratio vs block size for 5 strategies + BCH reference.
Panel B (×4 hash sizes): Empirical max correctable errors at ≥95% success vs block size + BCH reference.
Panel C: Hash size sweep — max correctable flips vs block size for CRC-8/16/32/64
         using the default strategy, on smaller block sizes.

Layout: 3 rows × 4 columns.
  Row 0 — Panel A at CRC-8, CRC-16, CRC-32, CRC-64
  Row 1 — Panel B at CRC-8, CRC-16, CRC-32, CRC-64
  Row 2 — Panel C spanning all columns
"""
from __future__ import annotations

import argparse
import contextlib
import math
import os
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
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
from experiments.trial_runner import get_flip_indices, _trial_task

DEFAULT_BIT_LENGTHS = [256, 512, 1024, 2048, 4096]
MAX_BITS_PER_NODE = 64  # skip strategy+block_size combos where solver is intractable
DEFAULT_MAX_COMBOS = 500_000  # per-trial combo budget; prevents hanging on hard instances

# Hash sizes used for Panel A/B columns and Panel C sweep
PANEL_HASH_BITS = [8, 16, 32, 64]
HASH_SWEEP_COLORS = {8: "#e41a1c", 16: "#377eb8", 32: "#4daf4a", 64: "#984ea3"}

# Panel C — default strategy only, smaller block sizes
DEFAULT_HASH_SWEEP_LENGTHS = [128, 256, 512, 1024]

DEFAULT_KEYS = 20
DEFAULT_ROUNDS = 8
SUCCESS_THRESHOLD = 0.95
EARLY_STOP_CONSECUTIVE = 3  # stop a (strategy, hb, L) sweep after this many consecutive failures

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


def _bits_per_node(bit_length: int, row_group_size: int, col_group_size: int,
                   row_splits: int = 1, col_splits: int = 1) -> int:
    """Largest node size (in source bits) for a given strategy and block size."""
    n = math.ceil(math.sqrt(bit_length))
    bits_per_row_node = math.ceil(n * row_group_size / row_splits)
    bits_per_col_node = math.ceil(n * col_group_size / col_splits)
    return max(bits_per_row_node, bits_per_col_node)


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
    max_fc = max(step, int(0.40 * L))
    return list(range(step, max_fc + step, step))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Figure 5: Adaptive grouping — overhead and correction vs block size"
    )
    p.add_argument("--bit-lengths", type=str, default=",".join(str(x) for x in DEFAULT_BIT_LENGTHS))
    p.add_argument("--keys", type=int, default=DEFAULT_KEYS)
    p.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out-dir", type=str, default="results/fig5")
    p.add_argument("--no-plot", action="store_true")
    p.add_argument("--parallel", action="store_true")
    p.add_argument("--workers", type=int, default=0)
    p.add_argument("--max-flips", type=int, default=DEFAULT_MAX_COMBOS,
                   help="Max combo evaluations per trial before giving up (0 = unlimited, not recommended)")
    p.add_argument("--hash-sweep-lengths", type=str,
                   default=",".join(str(x) for x in DEFAULT_HASH_SWEEP_LENGTHS),
                   help="Block sizes for hash-width sweep (Panel C)")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    bit_lengths = parse_int_list(args.bit_lengths)
    if not bit_lengths:
        raise ValueError("--bit-lengths must be non-empty")
    ensure_dir(args.out_dir)
    max_combos = args.max_flips if args.max_flips > 0 else None
    hash_sweep_lengths = parse_int_list(args.hash_sweep_lengths)
    write_json(os.path.join(args.out_dir, "config.json"), {
        "bit_lengths": bit_lengths,
        "panel_hash_bits": PANEL_HASH_BITS,
        "keys": args.keys,
        "rounds": args.rounds,
        "strategies": [s["label"] for s in STRATEGIES],
        "success_threshold": SUCCESS_THRESHOLD,
        "max_combos": max_combos,
        "hash_sweep_lengths": hash_sweep_lengths,
    })

    # --- Panel A: analytical overhead (one column per hash size) ---
    plot_lengths = sorted(set(bit_lengths + [128, 256, 512, 1024, 2048, 4096, 8192, 16384]))
    overhead_rows: list[dict[str, Any]] = []
    for L in plot_lengths:
        row: dict[str, Any] = {"bit_length": L}
        for hb in PANEL_HASH_BITS:
            for s in STRATEGIES:
                ratio = compute_overhead_ratio(
                    L, s["row_group_size"], s["col_group_size"], hb,
                    row_splits=s["row_splits"], col_splits=s["col_splits"],
                )
                row[f"overhead_hb{hb}_{s['label']}"] = ratio
        for t in BCH_T_VALUES:
            row[f"overhead_bch_t{t}"] = bch_overhead_ratio(L, t)
        overhead_rows.append(row)

    overhead_fieldnames = (
        ["bit_length"]
        + [f"overhead_hb{hb}_{s['label']}" for hb in PANEL_HASH_BITS for s in STRATEGIES]
        + [f"overhead_bch_t{t}" for t in BCH_T_VALUES]
    )
    write_csv(os.path.join(args.out_dir, "fig5_overhead.csv"), overhead_rows, overhead_fieldnames)

    # --- Panel B: empirical max-correctable flips at ≥95% success (all hash sizes) ---
    all_lengths_needed = sorted(set(bit_lengths) | set(hash_sweep_lengths))
    bits_by_length = {L: [(i * 3 + 1) % 2 for i in range(L)] for L in all_lengths_needed}

    workers = args.workers if args.workers > 0 else (os.cpu_count() or 1)

    # --- Panel B: wave-parallel sweep with early stopping ---
    # At each flip-count level, all active (strategy, hb, L) groups submit their
    # keys together into one shared pool — saturating cores across groups, not within one.
    empirical_rows: list[dict[str, Any]] = []
    max_correctable: dict[tuple[str, int, int], int | None] = {}
    skipped_cells: set[tuple[str, int]] = set()

    # Build group list — keys are (label, hb, L) so they're hashable
    strategy_by_label = {s["label"]: s for s in STRATEGIES}
    b_groups: list[tuple] = []  # (label, hb, L)
    for s in STRATEGIES:
        for L in bit_lengths:
            node_bits = _bits_per_node(L, s["row_group_size"], s["col_group_size"], s["row_splits"], s["col_splits"])
            if node_bits > MAX_BITS_PER_NODE:
                skipped_cells.add((s["label"], L))
                print(f"  Skipping {s['label']} at L={L} — node too large ({node_bits} bits/node > {MAX_BITS_PER_NODE})")
                for hb in PANEL_HASH_BITS:
                    max_correctable[(s["label"], hb, L)] = None
                continue
            for hb in PANEL_HASH_BITS:
                b_groups.append((s["label"], hb, L))

    g_best:   dict[tuple, int]  = {g: 0     for g in b_groups}
    g_consec: dict[tuple, int]  = {g: 0     for g in b_groups}
    g_done:   dict[tuple, bool] = {g: False for g in b_groups}
    flip_lists = {L: flip_sweep_counts(L) for L in bit_lengths}
    max_steps = max(len(v) for v in flip_lists.values())

    print(f"Panel B: {len(b_groups)} groups ({len(STRATEGIES)} strategies × {len(PANEL_HASH_BITS)} hash sizes × {len(bit_lengths)} block sizes), early stop after {EARLY_STOP_CONSECUTIVE} consecutive failures")

    if args.parallel:
        # Submit all tasks upfront in flip-count order so the queue is always full.
        # When a group early-stops, cancel its queued (not-yet-started) futures.
        b_all_futures: dict = {}           # future -> (g, key_id, flip_count)
        b_fc_futures:  dict = defaultdict(lambda: defaultdict(list))  # g -> fc -> [futures]
        with ProcessPoolExecutor(max_workers=workers) as executor:
            for step in range(max_steps):
                for g in b_groups:
                    label, hb, L = g
                    fcs = flip_lists[L]
                    if step >= len(fcs):
                        continue
                    flip_count = fcs[step]
                    s = strategy_by_label[label]
                    bits = bits_by_length[L]
                    for key_id in range(args.keys):
                        key = stable_key(args.seed, key_id)
                        rng = stable_rng(args.seed, key_id, flip_count, hb, L, label)
                        flip_indices = get_flip_indices(flip_count, L, "random", rng)
                        fut = executor.submit(_trial_task, (
                            bits, key, args.rounds, flip_indices,
                            s["row_group_size"], s["col_group_size"],
                            hb, "include_partial", max_combos, 0, "crc",
                            s["row_splits"], s["col_splits"],
                        ))
                        b_all_futures[fut] = (g, key_id, flip_count)
                        b_fc_futures[g][flip_count].append(fut)

            # Process results as they arrive; buffer per (group, flip_count)
            # so we process each flip_count only once all keys are done.
            b_buf:    dict = defaultdict(lambda: defaultdict(list))  # g->fc->[(key_id,result)]
            b_fc_idx: dict = {g: 0 for g in b_groups}               # next fc index to process

            for fut in as_completed(b_all_futures):
                if fut.cancelled():
                    continue
                g, key_id, flip_count = b_all_futures[fut]
                if g_done[g]:
                    continue
                b_buf[g][flip_count].append((key_id, fut.result()))

                label, hb, L = g
                fcs = flip_lists[L]
                while not g_done[g]:
                    idx = b_fc_idx[g]
                    if idx >= len(fcs):
                        break
                    fc = fcs[idx]
                    buf = b_buf[g][fc]
                    if len(buf) < args.keys:
                        break  # still waiting for other keys at this flip_count
                    rate = sum(r["fully_corrected"] for _, r in buf) / len(buf)
                    for kid, trial in buf:
                        empirical_rows.append({
                            "strategy": label, "hash_bits": hb, "bit_length": L,
                            "flip_count": fc, "key_id": kid,
                            "fully_corrected": int(trial["fully_corrected"]),
                            "solve_time_ms": trial["solve_time_ms"],
                        })
                    if rate >= SUCCESS_THRESHOLD:
                        g_best[g] = fc
                        g_consec[g] = 0
                    else:
                        g_consec[g] += 1
                        if g_consec[g] >= EARLY_STOP_CONSECUTIVE:
                            g_done[g] = True
                            for fc2, futs in b_fc_futures[g].items():
                                if fc2 > fc:
                                    for f in futs:
                                        f.cancel()
                            break
                    b_fc_idx[g] = idx + 1
    else:
        # Serial: simple per-group loop with early stopping.
        for g in b_groups:
            label, hb, L = g
            s = strategy_by_label[label]
            bits = bits_by_length[L]
            for flip_count in flip_lists[L]:
                results = []
                for key_id in range(args.keys):
                    key = stable_key(args.seed, key_id)
                    rng = stable_rng(args.seed, key_id, flip_count, hb, L, label)
                    flip_indices = get_flip_indices(flip_count, L, "random", rng)
                    results.append((key_id, _trial_task((
                        bits, key, args.rounds, flip_indices,
                        s["row_group_size"], s["col_group_size"],
                        hb, "include_partial", max_combos, 0, "crc",
                        s["row_splits"], s["col_splits"],
                    ))))
                rate = sum(r["fully_corrected"] for _, r in results) / len(results)
                for key_id, trial in results:
                    empirical_rows.append({
                        "strategy": label, "hash_bits": hb, "bit_length": L,
                        "flip_count": flip_count, "key_id": key_id,
                        "fully_corrected": int(trial["fully_corrected"]),
                        "solve_time_ms": trial["solve_time_ms"],
                    })
                if rate >= SUCCESS_THRESHOLD:
                    g_best[g] = flip_count
                    g_consec[g] = 0
                else:
                    g_consec[g] += 1
                    if g_consec[g] >= EARLY_STOP_CONSECUTIVE:
                        g_done[g] = True
                        break

    for g in b_groups:
        label, hb, L = g
        s = strategy_by_label[label]
        overhead = compute_overhead_ratio(
            L, s["row_group_size"], s["col_group_size"], hb,
            row_splits=s["row_splits"], col_splits=s["col_splits"],
        )
        max_correctable[(label, hb, L)] = g_best[g]
        print(f"  {label:8s}  CRC-{hb:2d}  L={L:6d}  overhead={overhead:.1%}  max_flips={g_best[g]}")

    write_csv(os.path.join(args.out_dir, "fig5_empirical.csv"), empirical_rows,
              ["strategy", "hash_bits", "bit_length", "flip_count", "key_id", "fully_corrected", "solve_time_ms"])

    # --- Panel C: hash size sweep (default strategy, smaller block sizes) ---
    hash_sweep_rows: list[dict[str, Any]] = []
    hash_max_correctable: dict[tuple[int, int], int] = {}

    default_s = strategy_by_label["default"]
    c_groups = [(hb, L) for hb in PANEL_HASH_BITS for L in hash_sweep_lengths]
    c_best:   dict[tuple, int]  = {g: 0     for g in c_groups}
    c_consec: dict[tuple, int]  = {g: 0     for g in c_groups}
    c_done:   dict[tuple, bool] = {g: False for g in c_groups}
    c_flip_lists = {L: flip_sweep_counts(L) for L in hash_sweep_lengths}
    c_max_steps = max(len(v) for v in c_flip_lists.values())

    print(f"Panel C: {len(PANEL_HASH_BITS)} hash widths × {len(hash_sweep_lengths)} block sizes (early stop after {EARLY_STOP_CONSECUTIVE} consecutive failures)")

    if args.parallel:
        c_all_futures: dict = {}
        c_fc_futures:  dict = defaultdict(lambda: defaultdict(list))
        with ProcessPoolExecutor(max_workers=workers) as executor:
            for step in range(c_max_steps):
                for g in c_groups:
                    hb, L = g
                    fcs = c_flip_lists[L]
                    if step >= len(fcs):
                        continue
                    flip_count = fcs[step]
                    bits = bits_by_length[L]
                    for key_id in range(args.keys):
                        key = stable_key(args.seed, key_id)
                        rng = stable_rng(args.seed, key_id, flip_count, hb, L, "default")
                        flip_indices = get_flip_indices(flip_count, L, "random", rng)
                        fut = executor.submit(_trial_task, (
                            bits, key, args.rounds, flip_indices,
                            default_s["row_group_size"], default_s["col_group_size"],
                            hb, "include_partial", max_combos, 0, "crc",
                            default_s["row_splits"], default_s["col_splits"],
                        ))
                        c_all_futures[fut] = (g, key_id, flip_count)
                        c_fc_futures[g][flip_count].append(fut)

            c_buf:    dict = defaultdict(lambda: defaultdict(list))
            c_fc_idx: dict = {g: 0 for g in c_groups}

            for fut in as_completed(c_all_futures):
                if fut.cancelled():
                    continue
                g, key_id, flip_count = c_all_futures[fut]
                if c_done[g]:
                    continue
                c_buf[g][flip_count].append((key_id, fut.result()))

                hb, L = g
                fcs = c_flip_lists[L]
                while not c_done[g]:
                    idx = c_fc_idx[g]
                    if idx >= len(fcs):
                        break
                    fc = fcs[idx]
                    buf = c_buf[g][fc]
                    if len(buf) < args.keys:
                        break
                    rate = sum(r["fully_corrected"] for _, r in buf) / len(buf)
                    for kid, trial in buf:
                        hash_sweep_rows.append({
                            "hash_bits": hb, "bit_length": L,
                            "flip_count": fc, "key_id": kid,
                            "fully_corrected": int(trial["fully_corrected"]),
                            "solve_time_ms": trial["solve_time_ms"],
                        })
                    if rate >= SUCCESS_THRESHOLD:
                        c_best[g] = fc
                        c_consec[g] = 0
                    else:
                        c_consec[g] += 1
                        if c_consec[g] >= EARLY_STOP_CONSECUTIVE:
                            c_done[g] = True
                            for fc2, futs in c_fc_futures[g].items():
                                if fc2 > fc:
                                    for f in futs:
                                        f.cancel()
                            break
                    c_fc_idx[g] = idx + 1
    else:
        for g in c_groups:
            hb, L = g
            bits = bits_by_length[L]
            for flip_count in c_flip_lists[L]:
                results = []
                for key_id in range(args.keys):
                    key = stable_key(args.seed, key_id)
                    rng = stable_rng(args.seed, key_id, flip_count, hb, L, "default")
                    flip_indices = get_flip_indices(flip_count, L, "random", rng)
                    results.append((key_id, _trial_task((
                        bits, key, args.rounds, flip_indices,
                        default_s["row_group_size"], default_s["col_group_size"],
                        hb, "include_partial", max_combos, 0, "crc",
                        default_s["row_splits"], default_s["col_splits"],
                    ))))
                rate = sum(r["fully_corrected"] for _, r in results) / len(results)
                for key_id, trial in results:
                    hash_sweep_rows.append({
                        "hash_bits": hb, "bit_length": L,
                        "flip_count": flip_count, "key_id": key_id,
                        "fully_corrected": int(trial["fully_corrected"]),
                        "solve_time_ms": trial["solve_time_ms"],
                    })
                if rate >= SUCCESS_THRESHOLD:
                    c_best[g] = flip_count
                    c_consec[g] = 0
                else:
                    c_consec[g] += 1
                    if c_consec[g] >= EARLY_STOP_CONSECUTIVE:
                        c_done[g] = True
                        break

    for g in c_groups:
        hb, L = g
        overhead = compute_overhead_ratio(L, 1, 1, hb)
        hash_max_correctable[(hb, L)] = c_best[g]
        print(f"  CRC-{hb:2d}  L={L:6d}  overhead={overhead:.1%}  max_flips_at_95pct={c_best[g]}")

    write_csv(os.path.join(args.out_dir, "fig5_hash_sweep.csv"), hash_sweep_rows,
              ["hash_bits", "bit_length", "flip_count", "key_id", "fully_corrected", "solve_time_ms"])

    if args.no_plot:
        return

    try:
        import matplotlib.pyplot as plt
        import matplotlib.ticker as ticker
        from matplotlib.gridspec import GridSpec
    except ModuleNotFoundError as e:
        raise RuntimeError("matplotlib required; install it or use --no-plot") from e

    # 3 rows × 4 cols: Row 0 = Panel A, Row 1 = Panel B, Row 2 = Panel C (spanning all cols)
    fig = plt.figure(figsize=(28, 18))
    fig.suptitle(
        "Adaptive Grouping: Approximate ECC — overhead & correction by hash size",
        fontsize=14, fontweight="bold",
    )
    gs = GridSpec(3, 4, figure=fig, hspace=0.45, wspace=0.35, height_ratios=[1, 1, 0.9])

    ax_a = [fig.add_subplot(gs[0, i]) for i in range(4)]
    ax_b = [fig.add_subplot(gs[1, i]) for i in range(4)]
    ax_c = fig.add_subplot(gs[2, :])

    xs_plot = [r["bit_length"] for r in overhead_rows]
    all_xs = sorted(bit_lengths)

    for col, hb in enumerate(PANEL_HASH_BITS):
        # --- Panel A col: overhead vs block size ---
        ax = ax_a[col]
        for s in STRATEGIES:
            ys = [r[f"overhead_hb{hb}_{s['label']}"] * 100 for r in overhead_rows]
            color = STRATEGY_COLORS[s["label"]]
            ls = "--" if "group" in s["label"] else ("-" if s["label"] == "default" else ":")
            ax.plot(xs_plot, ys, linestyle=ls, marker="o", markersize=3,
                    color=color, linewidth=1.8, label=s["label"])
        for t in BCH_T_VALUES:
            ys = [r[f"overhead_bch_t{t}"] * 100 for r in overhead_rows]
            ax.plot(xs_plot, ys, linestyle=":", marker="^", markersize=2.5,
                    color=BCH_COLORS[t], linewidth=1.3, label=f"BCH t={t}")

        ax.set_xscale("log", base=2)
        ax.set_xlabel("Block size (bits)", fontsize=8)
        ax.set_ylabel("Overhead (%)" if col == 0 else "", fontsize=8)
        ax.set_title(f"Overhead — CRC-{hb}\n(grouping vs splits vs BCH)", fontsize=9)
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=7, ncol=2)
        ax.yaxis.set_major_formatter(ticker.PercentFormatter())
        ax.xaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f"{int(x):,}"))
        ax.tick_params(labelsize=7)

        # --- Panel B col: max correctable vs block size ---
        ax = ax_b[col]
        for s in STRATEGIES:
            all_ys = [max_correctable.get((s["label"], hb, L)) for L in all_xs]
            xs_valid = [x for x, y in zip(all_xs, all_ys) if y is not None]
            ys_valid = [y for y in all_ys if y is not None]
            if not xs_valid:
                continue
            color = STRATEGY_COLORS[s["label"]]
            ls = "--" if "group" in s["label"] else ("-" if s["label"] == "default" else ":")
            ax.plot(xs_valid, ys_valid, linestyle=ls, marker="s", markersize=4,
                    color=color, linewidth=1.8, label=s["label"])
        for t in BCH_T_VALUES:
            ys = [bch_max_correctable(L, t) for L in all_xs]
            ax.plot(all_xs, ys, linestyle=":", marker="^", markersize=2.5,
                    color=BCH_COLORS[t], linewidth=1.3, label=f"BCH t={t}")

        ax.set_xscale("log", base=2)
        ax.set_xlabel("Block size (bits)", fontsize=8)
        ax.set_ylabel(f"Max correctable (≥{int(SUCCESS_THRESHOLD*100)}%)" if col == 0 else "", fontsize=8)
        ax.set_title(f"Max correctable — CRC-{hb}\n(≥{int(SUCCESS_THRESHOLD*100)}% success)", fontsize=9)
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=7, ncol=2)
        ax.xaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f"{int(x):,}"))
        ax.tick_params(labelsize=7)

    # --- Panel C: hash size sweep (default strategy, smaller block sizes) ---
    xs_sweep = sorted(hash_sweep_lengths)
    for hb in PANEL_HASH_BITS:
        ys = [hash_max_correctable.get((hb, L), 0) for L in xs_sweep]
        overhead_pcts = [compute_overhead_ratio(L, 1, 1, hb) * 100 for L in xs_sweep]
        mid = len(xs_sweep) // 2
        label = f"CRC-{hb} (~{overhead_pcts[mid]:.0f}% OH at {xs_sweep[mid]:,}b)"
        ax_c.plot(xs_sweep, ys, linestyle="-", marker="o", markersize=5,
                  color=HASH_SWEEP_COLORS[hb], linewidth=2, label=label)

    ax_c.set_xscale("log", base=2)
    ax_c.set_xlabel("Block size (bits)")
    ax_c.set_ylabel(f"Max correctable flips (≥{int(SUCCESS_THRESHOLD*100)}% success)")
    ax_c.set_title(
        f"Hash width sweep — default strategy (≥{int(SUCCESS_THRESHOLD*100)}% success threshold)"
    )
    ax_c.grid(True, alpha=0.3)
    ax_c.legend(fontsize=9)
    ax_c.xaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f"{int(x):,}"))

    out_path = os.path.join(args.out_dir, "fig5_adaptive_grouping.png")
    plt.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close()
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
