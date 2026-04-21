"""Figure 3: Scalability — overhead and correction success across block sizes.

Panel A: Overhead ratio vs block size (analytical).
         CRISP decreases as O(1/sqrt(L)); BCH overhead is flat for fixed t per 256-bit block.
         BCH t values are BER-matched: t = round(BER × 256) at BER=1%,2%,5%,6%.

Panel B: CRISP empirical success rate vs BER, one line per block size.
         Shows the correction envelope as BER is increased at each scale.

Panel C: BCH analytical success rate vs BER, one line per block size.
         t = round(BER × 256) per 256-bit block; success = P(Binom(256,ber)<=t)^n_blocks.
         Shows BCH collapses because t is sized at the 50th percentile, not the 95th.
"""
from __future__ import annotations

import argparse
import math
import os
from typing import Any

from experiments.common import (
    compute_overhead_ratio,
    ensure_dir,
    parse_int_list,
    stable_key,
    stable_rng,
    write_csv,
    write_json,
)
from experiments.ecc_comparison import bch_block_success_prob, bch_overhead
from experiments.trial_runner import get_flip_indices, run_trials_parallel, run_trials_serial

DEFAULT_BIT_LENGTHS = [256, 512, 1024, 2048, 4096, 8192, 16384]
DEFAULT_BER_VALUES  = [0.01, 0.02, 0.03, 0.04, 0.05, 0.06]
DEFAULT_KEYS        = 20
DEFAULT_ROUNDS      = 8
DEFAULT_HASH_BITS   = 32
GROUP_SIZE          = 1
BCH_BLOCK_SIZE      = 256

# BER-matched t values for Panel A: t = round(BER × 256)
# BER  1% → t=3,  2% → t=5,  5% → t=13,  6% → t=15
BCH_T_VALUES = [3, 5, 13, 15]
BCH_T_LABELS = {3: "1% BER", 5: "2% BER", 13: "5% BER", 15: "6% BER"}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Figure 3: Scalability — overhead and BER-sweep success across block sizes"
    )
    p.add_argument("--bit-lengths", type=str,
                   default=",".join(str(x) for x in DEFAULT_BIT_LENGTHS))
    p.add_argument("--ber-values",  type=str,
                   default=",".join(str(x) for x in DEFAULT_BER_VALUES))
    p.add_argument("--keys",     type=int, default=DEFAULT_KEYS)
    p.add_argument("--rounds",   type=int, default=DEFAULT_ROUNDS)
    p.add_argument("--hash-bits",type=int, default=DEFAULT_HASH_BITS)
    p.add_argument("--seed",     type=int, default=0)
    p.add_argument("--out-dir",  type=str, default="results/fig3")
    p.add_argument("--no-plot",  action="store_true")
    p.add_argument("--parallel", action="store_true")
    p.add_argument("--workers",  type=int, default=0)
    p.add_argument("--max-flips",type=int, default=None,
                   help="Max combo evaluations per trial (default: unlimited)")
    return p.parse_args()


def main() -> None:
    args    = parse_args()
    HASH_BITS   = args.hash_bits
    bit_lengths = parse_int_list(args.bit_lengths)
    ber_values  = [float(x) for x in args.ber_values.split(",") if x.strip()]
    if not bit_lengths:
        raise ValueError("--bit-lengths must be non-empty")
    if not ber_values:
        raise ValueError("--ber-values must be non-empty")

    ensure_dir(args.out_dir)
    write_json(os.path.join(args.out_dir, "config.json"), {
        "bit_lengths":  bit_lengths,
        "ber_values":   ber_values,
        "keys":         args.keys,
        "rounds":       args.rounds,
        "hash_bits":    HASH_BITS,
        "group_size":   GROUP_SIZE,
        "bch_t_values": BCH_T_VALUES,
    })

    # ── Panel A: analytical overhead ─────────────────────────────────────────
    plot_lengths = sorted(set(bit_lengths + [128, 256, 512, 1024, 2048, 4096, 8192, 16384]))
    overhead_rows: list[dict[str, Any]] = []
    for L in plot_lengths:
        row: dict[str, Any] = {
            "bit_length":       L,
            "our_overhead_ratio": compute_overhead_ratio(L, GROUP_SIZE, GROUP_SIZE, HASH_BITS),
        }
        for t in BCH_T_VALUES:
            row[f"bch_t{t}_overhead_ratio"] = bch_overhead(L, t)["overhead_ratio"]
        overhead_rows.append(row)

    write_csv(
        os.path.join(args.out_dir, "fig3_overhead.csv"),
        overhead_rows,
        ["bit_length", "our_overhead_ratio"] + [f"bch_t{t}_overhead_ratio" for t in BCH_T_VALUES],
    )

    # ── Panel B: CRISP empirical BER sweep ────────────────────────────────────
    bits_by_length = {L: [(i * 3 + 1) % 2 for i in range(L)] for L in bit_lengths}

    all_tasks: list[tuple] = []
    all_metas: list[tuple] = []
    for L in bit_lengths:
        bits = bits_by_length[L]
        for ber in ber_values:
            flip_count = max(1, round(ber * L))
            for key_id in range(args.keys):
                key = stable_key(args.seed, key_id)
                rng = stable_rng(args.seed, key_id, flip_count, HASH_BITS, L, ber, "random")
                flip_indices = get_flip_indices(flip_count, L, "random", rng)
                all_tasks.append((
                    bits, key, args.rounds, flip_indices,
                    GROUP_SIZE, GROUP_SIZE, HASH_BITS,
                    "include_partial", args.max_flips, 0, "crc", 1, 1,
                ))
                all_metas.append((L, ber, flip_count, key_id))

    total = len(all_tasks)
    print(f"Running {total} CRISP trials "
          f"({len(bit_lengths)} block sizes × {len(ber_values)} BER values × {args.keys} trials)...")
    if args.parallel:
        flat_results = run_trials_parallel(all_tasks, args.workers)
    else:
        flat_results = run_trials_serial(all_tasks)

    sweep_rows: list[dict[str, Any]] = []
    for trial, (L, ber, flip_count, key_id) in zip(flat_results, all_metas):
        sweep_rows.append({
            "bit_length":    L,
            "ber":           ber,
            "flip_count":    flip_count,
            "key_id":        key_id,
            "overhead_ratio": compute_overhead_ratio(L, GROUP_SIZE, GROUP_SIZE, HASH_BITS),
            "fully_corrected": int(trial["fully_corrected"]),
            "solve_time_ms": trial["solve_time_ms"],
        })

    write_csv(
        os.path.join(args.out_dir, "fig3_ber_sweep.csv"),
        sweep_rows,
        ["bit_length", "ber", "flip_count", "key_id",
         "overhead_ratio", "fully_corrected", "solve_time_ms"],
    )

    # Print summary table
    print(f"\n{'L':>7}  {'BER':>6}  {'flips':>6}  {'flips/node':>10}  {'success':>8}")
    print("-" * 50)
    for L in bit_lengths:
        N = math.ceil(math.sqrt(L))
        for ber in ber_values:
            subset = [r for r in sweep_rows if r["bit_length"] == L and r["ber"] == ber]
            rate   = sum(r["fully_corrected"] for r in subset) / len(subset)
            fc     = subset[0]["flip_count"]
            fpn    = fc / N
            print(f"{L:>7}  {ber:>6.1%}  {fc:>6}  {fpn:>10.2f}  {rate:>8.1%}")

    # ── Panel C: BCH analytical BER sweep ────────────────────────────────────
    bch_rows: list[dict[str, Any]] = []
    for L in bit_lengths:
        n_blocks = max(1, L // BCH_BLOCK_SIZE)
        for ber in ber_values:
            t        = max(1, round(ber * BCH_BLOCK_SIZE))
            # P(all n_blocks succeed) = P(Binom(256,ber) <= t)^n_blocks
            p_block  = bch_block_success_prob(t, ber, BCH_BLOCK_SIZE)
            p_all    = p_block ** n_blocks
            bch_rows.append({
                "bit_length":       L,
                "ber":              ber,
                "t":                t,
                "n_blocks":         n_blocks,
                "bch_success_rate": p_all,
                "overhead_ratio":   bch_overhead(L, t)["overhead_ratio"],
            })

    write_csv(
        os.path.join(args.out_dir, "fig3_bch_analytical.csv"),
        bch_rows,
        ["bit_length", "ber", "t", "n_blocks", "bch_success_rate", "overhead_ratio"],
    )

    if args.no_plot:
        return

    try:
        import matplotlib.pyplot as plt
        import matplotlib.ticker as ticker
        import matplotlib.cm as cm
        import numpy as np
    except ModuleNotFoundError as e:
        raise RuntimeError("matplotlib required; use --no-plot to skip") from e

    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(19, 6))
    fig.suptitle(
        f"CRISP Scalability  (CRC-{HASH_BITS}, group_size={GROUP_SIZE})",
        fontsize=13, fontweight="bold",
    )

    # ── Panel A: overhead vs block size ──────────────────────────────────────
    our_xs = [r["bit_length"] for r in overhead_rows]
    our_ys = [r["our_overhead_ratio"] * 100 for r in overhead_rows]
    ax1.plot(our_xs, our_ys, "o-", color="#377eb8", linewidth=2.5, markersize=5,
             label=f"CRISP ({HASH_BITS}-bit CRC)")

    bch_colors = {3: "#e41a1c", 5: "#ff7f00", 13: "#984ea3", 15: "#a65628"}
    for t in BCH_T_VALUES:
        bch_ys = [r[f"bch_t{t}_overhead_ratio"] * 100 for r in overhead_rows]
        ax1.plot(our_xs, bch_ys, "--", linewidth=1.5, color=bch_colors[t],
                 label=f"BCH t={t} ({BCH_T_LABELS[t]})")

    ax1.set_xscale("log", base=2)
    ax1.set_xlabel("Block size (bits)")
    ax1.set_ylabel("Overhead (%)")
    ax1.set_title("Overhead vs block size")
    ax1.grid(True, alpha=0.3)
    ax1.legend(fontsize=8)
    ax1.yaxis.set_major_formatter(ticker.PercentFormatter())
    ax1.xaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f"{int(x):,}"))
    ax1.annotate("CRISP ∝ 1/√L",
                 xy=(4096, compute_overhead_ratio(4096, GROUP_SIZE, GROUP_SIZE, HASH_BITS) * 100),
                 xytext=(0.38, 0.52), textcoords="axes fraction",
                 arrowprops=dict(arrowstyle="->", color="#377eb8"),
                 fontsize=9, color="#377eb8")

    # ── Shared color map for block sizes ─────────────────────────────────────
    palette = cm.get_cmap("plasma", len(bit_lengths))
    size_colors = {L: palette(i) for i, L in enumerate(bit_lengths)}
    ber_pct = [b * 100 for b in ber_values]

    # ── Panel B: CRISP empirical success vs BER ───────────────────────────────
    for L in bit_lengths:
        ys = []
        es = []
        for ber in ber_values:
            subset = [r for r in sweep_rows if r["bit_length"] == L and r["ber"] == ber]
            n    = len(subset)
            rate = sum(r["fully_corrected"] for r in subset) / n
            se   = math.sqrt(rate * (1 - rate) / n) if n > 1 and 0 < rate < 1 else 0.0
            ys.append(rate * 100)
            es.append(se * 100)
        ax2.errorbar(ber_pct, ys, yerr=es, marker="o", linewidth=2,
                     capsize=3, color=size_colors[L],
                     label=f"{L:,} bits")

    ax2.set_xlabel("BER (%)")
    ax2.set_ylabel("Success rate (%)")
    ax2.set_title("CRISP: success rate vs BER\n(empirical, random errors)")
    ax2.set_ylim(-5, 105)
    ax2.yaxis.set_major_formatter(ticker.PercentFormatter())
    ax2.xaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f"{x:.0f}%"))
    ax2.grid(True, alpha=0.3)
    ax2.legend(fontsize=8, title="Block size")

    # ── Panel C: BCH analytical success vs BER ───────────────────────────────
    for L in bit_lengths:
        ys = []
        for ber in ber_values:
            row = next(r for r in bch_rows if r["bit_length"] == L and r["ber"] == ber)
            ys.append(row["bch_success_rate"] * 100)
        ax3.plot(ber_pct, ys, marker="s", linewidth=2,
                 color=size_colors[L], label=f"{L:,} bits")

    ax3.set_xlabel("BER (%)")
    ax3.set_ylabel("Success rate (%)")
    ax3.set_title("BCH: success rate vs BER\n(analytical, t = round(BER × 256) per block)")
    ax3.set_ylim(-5, 105)
    ax3.yaxis.set_major_formatter(ticker.PercentFormatter())
    ax3.xaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f"{x:.0f}%"))
    ax3.grid(True, alpha=0.3)
    ax3.legend(fontsize=8, title="Block size")

    note = "BCH success ≈ 0% because t = expected errors/block\n≈ 50th percentile, not 95th"
    ax3.text(0.05, 0.15, note, transform=ax3.transAxes, fontsize=9,
             color="#e41a1c",
             bbox=dict(boxstyle="round,pad=0.3", facecolor="lightyellow", alpha=0.8))

    plt.tight_layout()
    out_path = os.path.join(args.out_dir, "fig3_scalability.png")
    plt.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close()
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
