"""Figure 2: Overhead vs correction capability — Approximate ECC vs BCH.

Panel A: Overhead ratio vs correctable errors. BCH curve climbs steeply;
our scheme's operating points cluster near the bottom with much higher correction.

Panel B: Correction efficiency (correctable errors per 1% overhead).
Our scheme dominates BCH at high error counts.
"""
from __future__ import annotations

import argparse
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
from experiments.ecc_comparison import bch_decode_ops, bch_overhead
from experiments.trial_runner import get_flip_indices, run_trials_parallel, run_trials_serial

DEFAULT_BIT_LENGTH = 4096
DEFAULT_KEYS = 20
DEFAULT_ROUNDS = 8
SUCCESS_THRESHOLD = 0.95  # min success rate to count as "correctable"

# Our scheme configurations to test: (hash_bits, group_size)
# Note: group_size > 1 creates larger nodes (more bits per node), making the solver
# exponentially slower at high flip counts (C(n,k) search space), so we only test group_size=1.
OUR_CONFIGS = [
    (8, 1),
    (16, 1),
    (32, 1),
]

# BCH t values to show analytically
BCH_T_VALUES = [1, 5, 10, 20, 50, 100, 150, 200]

# Flip counts to empirically probe for our scheme.
# Capped at 200 to stay in the tractable solver range (verified in fig1).
# Each config has a different capability ceiling:
#   hash_bits=8  (25% overhead): corrects ~60 flips reliably
#   hash_bits=16 (50% overhead): corrects ~100 flips reliably
#   hash_bits=32 (100% overhead): corrects 200 flips reliably
PROBE_FLIP_COUNTS = [5, 10, 25, 50, 75, 100, 125, 150, 175, 200]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Figure 2: Overhead ratio vs correction capability — Approximate ECC vs BCH"
    )
    p.add_argument("--bit-length", type=int, default=DEFAULT_BIT_LENGTH)
    p.add_argument("--keys", type=int, default=DEFAULT_KEYS)
    p.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out-dir", type=str, default="results/fig2")
    p.add_argument("--no-plot", action="store_true")
    p.add_argument("--parallel", action="store_true")
    p.add_argument("--workers", type=int, default=0)
    p.add_argument("--max-flips", type=int, default=None,
                   help="Max combo evaluations per trial before giving up (default: unlimited)")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    ensure_dir(args.out_dir)
    write_json(os.path.join(args.out_dir, "config.json"), {
        "bit_length": args.bit_length,
        "keys": args.keys,
        "rounds": args.rounds,
        "seed": args.seed,
        "success_threshold": SUCCESS_THRESHOLD,
        "our_configs": OUR_CONFIGS,
        "probe_flip_counts": PROBE_FLIP_COUNTS,
        "bch_t_values": BCH_T_VALUES,
    })

    bits = [(i * 3 + 1) % 2 for i in range(args.bit_length)]

    # --- Compute BCH analytical data ---
    bch_rows: list[dict[str, Any]] = []
    for t in BCH_T_VALUES:
        info = bch_overhead(args.bit_length, t)
        bch_rows.append({
            "t": t,
            "parity_bits": info["parity_bits"],
            "overhead_ratio": info["overhead_ratio"],
            "overhead_pct": info["overhead_ratio"] * 100,
            "correctable_bits": info["correctable_bits"],
            "scheme": info["scheme"],
        })
        print(f"BCH t={t:3d}: overhead={info['overhead_ratio']:.1%}  parity={info['parity_bits']} bits")

    write_csv(os.path.join(args.out_dir, "fig2_bch.csv"), bch_rows,
              ["t", "parity_bits", "overhead_ratio", "overhead_pct", "correctable_bits", "scheme"])

    # --- Run empirical trials for our scheme ---
    all_tasks: list[tuple] = []
    all_metas: list[tuple] = []
    for hash_bits, group_size in OUR_CONFIGS:
        for fc in PROBE_FLIP_COUNTS:
            if fc > args.bit_length:
                continue
            for key_id in range(args.keys):
                key = stable_key(args.seed, key_id)
                rng = stable_rng(args.seed, key_id, fc, hash_bits, "random")
                flip_indices = get_flip_indices(fc, args.bit_length, "random", rng)
                all_tasks.append((
                    bits, key, args.rounds, flip_indices,
                    group_size, group_size, hash_bits, "include_partial", args.max_flips, 0, "crc", 1, 1,
                ))
                all_metas.append((hash_bits, group_size, fc, key_id))

    print(f"\nRunning {len(all_tasks)} empirical trials...")
    if args.parallel:
        flat_results = run_trials_parallel(all_tasks, args.workers)
    else:
        flat_results = run_trials_serial(all_tasks)

    our_rows: list[dict[str, Any]] = []
    for trial, (hash_bits, group_size, fc, key_id) in zip(flat_results, all_metas):
        our_rows.append({
            "hash_bits": hash_bits,
            "group_size": group_size,
            "flip_count": fc,
            "key_id": key_id,
            "overhead_ratio": compute_overhead_ratio(args.bit_length, group_size, group_size, hash_bits),
            "fully_corrected": int(trial["fully_corrected"]),
            "solve_time_ms": trial["solve_time_ms"],
            "total_combos_evaluated": trial["total_combos_evaluated"],
        })

    write_csv(os.path.join(args.out_dir, "fig2_ours.csv"), our_rows,
              ["hash_bits", "group_size", "flip_count", "key_id", "overhead_ratio",
               "fully_corrected", "solve_time_ms", "total_combos_evaluated"])

    # Determine max correctable flip count per config (success_rate >= threshold)
    our_operating_points: list[dict[str, Any]] = []
    for hash_bits, group_size in OUR_CONFIGS:
        overhead = compute_overhead_ratio(args.bit_length, group_size, group_size, hash_bits)
        max_correctable = 0
        for fc in PROBE_FLIP_COUNTS:
            subset = [r for r in our_rows
                      if r["hash_bits"] == hash_bits and r["group_size"] == group_size
                      and r["flip_count"] == fc]
            if not subset:
                continue
            rate = sum(r["fully_corrected"] for r in subset) / len(subset)
            if rate >= SUCCESS_THRESHOLD:
                max_correctable = fc
            print(f"  hash_bits={hash_bits:2d}  group={group_size}  overhead={overhead:.1%}  "
                  f"flips={fc:4d}  success={rate:.1%}")
        parity_bits = round(overhead * args.bit_length)
        our_operating_points.append({
            "label": f"{hash_bits}-bit CRC\n(gs={group_size})",
            "hash_bits": hash_bits,
            "group_size": group_size,
            "overhead_ratio": overhead,
            "overhead_pct": overhead * 100,
            "parity_bits": parity_bits,
            "max_correctable": max_correctable,
        })

    write_csv(os.path.join(args.out_dir, "fig2_operating_points.csv"), our_operating_points,
              ["hash_bits", "group_size", "overhead_ratio", "overhead_pct",
               "parity_bits", "max_correctable", "label"])

    if args.no_plot:
        return

    try:
        import matplotlib.pyplot as plt
        import matplotlib.ticker as ticker
    except ModuleNotFoundError as e:
        raise RuntimeError("matplotlib required; install it or use --no-plot") from e

    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(21, 7))
    fig.suptitle(
        f"Overhead vs Correction Capability: Approximate ECC vs BCH  (block size = {args.bit_length} bits)",
        fontsize=13, fontweight="bold",
    )

    # Panel A: overhead % vs max correctable errors
    bch_xs = [r["correctable_bits"] for r in bch_rows]
    bch_ys = [r["overhead_pct"] for r in bch_rows]
    ax1.plot(bch_xs, bch_ys, "s--", color="#d62728", linewidth=2, markersize=7, label="BCH (analytical upper bound)")
    for r in bch_rows:
        if r["t"] in {10, 50, 100, 200}:
            ax1.annotate(f"t={r['t']}\n{r['overhead_pct']:.0f}%",
                         xy=(r["correctable_bits"], r["overhead_pct"]),
                         xytext=(8, 4), textcoords="offset points", fontsize=7, color="#d62728")

    marker_styles = ["o", "^", "D", "v"]
    colors = ["#377eb8", "#4daf4a", "#984ea3", "#ff7f00"]
    for i, op in enumerate(our_operating_points):
        if op["max_correctable"] == 0:
            continue
        ax1.scatter([op["max_correctable"]], [op["overhead_pct"]],
                    s=120, marker=marker_styles[i], color=colors[i], zorder=5,
                    label=f"Ours: {op['label'].replace(chr(10), ', ')}  ({op['overhead_pct']:.0f}% overhead)")
        ax1.annotate(f"{op['overhead_pct']:.0f}%",
                     xy=(op["max_correctable"], op["overhead_pct"]),
                     xytext=(6, -14), textcoords="offset points", fontsize=8, color=colors[i])

    ax1.set_xlabel("Correctable bit-flips (at ≥95% success rate)")
    ax1.set_ylabel("Overhead (%)")
    ax1.set_title("Overhead vs correction capability")
    ax1.grid(True, alpha=0.3)
    ax1.legend(fontsize=9)
    ax1.yaxis.set_major_formatter(ticker.PercentFormatter())

    # Panel B: correction efficiency = correctable errors per 1% overhead
    bch_eff_xs = [r["correctable_bits"] for r in bch_rows]
    bch_eff_ys = [r["correctable_bits"] / r["overhead_pct"] for r in bch_rows]
    ax2.plot(bch_eff_xs, bch_eff_ys, "s--", color="#d62728", linewidth=2, markersize=7,
             label="BCH (analytical)")

    for i, op in enumerate(our_operating_points):
        if op["max_correctable"] == 0 or op["overhead_pct"] == 0:
            continue
        eff = op["max_correctable"] / op["overhead_pct"]
        ax2.scatter([op["max_correctable"]], [eff],
                    s=120, marker=marker_styles[i], color=colors[i], zorder=5,
                    label=f"Ours: {op['label'].replace(chr(10), ', ')}")

    ax2.set_xlabel("Correctable bit-flips")
    ax2.set_ylabel("Flips corrected per 1% overhead")
    ax2.set_title("Correction efficiency (higher is better)")
    ax2.grid(True, alpha=0.3)
    ax2.legend(fontsize=9)

    # Panel C: decode complexity — our combos evaluated vs BCH GF ops
    bch_decode_xs = [r["correctable_bits"] for r in bch_rows]
    bch_decode_ys = [bch_decode_ops(args.bit_length, r["t"]) for r in bch_rows]
    ax3.plot(bch_decode_xs, bch_decode_ys, "s--", color="#d62728", linewidth=2, markersize=7,
             label="BCH decode ops (GF field ops, analytical)")

    for i, op in enumerate(our_operating_points):
        if op["max_correctable"] == 0:
            continue
        # Use mean combos at the highest correctable flip count for this config
        subset = [r for r in our_rows
                  if r["hash_bits"] == op["hash_bits"] and r["group_size"] == op["group_size"]
                  and r["flip_count"] == op["max_correctable"]]
        if not subset:
            continue
        mean_combos = agg([r["total_combos_evaluated"] for r in subset]).mean
        ax3.scatter([op["max_correctable"]], [mean_combos],
                    s=120, marker=marker_styles[i], color=colors[i], zorder=5,
                    label=f"Ours: {op['label'].replace(chr(10), ', ')} (hash checks)")
        ax3.annotate(f"{mean_combos:,.0f}",
                     xy=(op["max_correctable"], mean_combos),
                     xytext=(6, 4), textcoords="offset points", fontsize=7, color=colors[i])

    ax3.set_xlabel("Correctable bit-flips")
    ax3.set_ylabel("Decode operations")
    ax3.set_title("Decode complexity (lower is better)")
    ax3.grid(True, alpha=0.3)
    ax3.legend(fontsize=8)
    ax3.text(0.05, 0.92,
             "BCH: GF(2^m) field ops\nOurs: CRC hash checks",
             transform=ax3.transAxes, fontsize=8,
             bbox=dict(boxstyle="round,pad=0.3", facecolor="lightyellow", edgecolor="gray", alpha=0.8))

    plt.tight_layout()
    out_path = os.path.join(args.out_dir, "fig2_overhead_comparison.png")
    plt.savefig(out_path, dpi=200)
    plt.close()
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
