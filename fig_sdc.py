"""Figure: Silent data corruption (SDC) rate and error floor.

Each trial is classified into exactly one of three outcomes:

  success          — corrected bits match original  (fully_corrected == True)
  silent_error     — all hash nodes satisfied yet bits are wrong
                     (mismatched_after == 0 AND fully_corrected == False)
                     This is a hash-collision / mis-correction event.
  detected_failure — solver left ≥1 hash node mismatched
                     (mismatched_after >  0 AND fully_corrected == False)
                     The decoder knows something is wrong.

Layout: 2 rows × 3 cols  (6 panels)
  Rows   — block sizes  (default: 1 024 and 4 096 bits)
  Col 0  — Success rate vs BER           (linear y, 0–100 %)
  Col 1  — SDC (silent-error) rate vs BER (log y — shows hash-collision floor)
  Col 2  — Detected-failure rate vs BER   (linear y, 0–100 %)

Lines within each panel: hash_bits ∈ {8, 16, 32}, group_size = 1.
A second sub-figure (fig_sdc_groupsize.png) repeats the layout but fixes
  block_size = 4 096 and varies group_size ∈ {1, 2, 4} instead.

Quick smoke test (few keys):
  python fig_sdc.py --keys 5 --parallel --no-groupsize-fig

Full run for lab server:
  python fig_sdc.py --keys 50 --parallel
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
    stable_key,
    stable_rng,
    write_csv,
    write_json,
)
from experiments.trial_runner import get_flip_indices, run_trials_parallel, run_trials_serial

# ── Defaults ──────────────────────────────────────────────────────────────────
DEFAULT_BIT_LENGTHS  = [1024, 4096]
DEFAULT_HASH_BITS    = [8, 16, 32]
DEFAULT_GROUP_SIZES  = [1, 2, 4]       # used in groupsize sub-figure
FIXED_GROUP_SIZE     = 1               # used in main figure
FIXED_BIT_LENGTH_GS  = 4096           # block size for groupsize sub-figure
DEFAULT_BER_VALUES   = [0.01, 0.02, 0.04, 0.06, 0.08, 0.10, 0.13, 0.16, 0.20]
DEFAULT_KEYS         = 20
DEFAULT_ROUNDS       = 8

HASH_COLORS = {8: "#e41a1c", 16: "#377eb8", 32: "#4daf4a"}
GS_COLORS   = {1: "#984ea3", 2: "#ff7f00", 4: "#a65628"}


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="SDC rate and error floor: Approximate ECC"
    )
    p.add_argument("--bit-lengths", type=str,
                   default=",".join(str(x) for x in DEFAULT_BIT_LENGTHS))
    p.add_argument("--hash-bits", type=str,
                   default=",".join(str(x) for x in DEFAULT_HASH_BITS))
    p.add_argument("--ber-values", type=str,
                   default=",".join(str(x) for x in DEFAULT_BER_VALUES))
    p.add_argument("--keys",   type=int, default=DEFAULT_KEYS)
    p.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS)
    p.add_argument("--seed",   type=int, default=0)
    p.add_argument("--out-dir", type=str, default="results/fig_sdc")
    p.add_argument("--no-plot", action="store_true")
    p.add_argument("--no-groupsize-fig", action="store_true",
                   help="Skip the group-size variation sub-figure")
    p.add_argument("--parallel", action="store_true")
    p.add_argument("--workers", type=int, default=0)
    return p.parse_args()


def _parse_list(s: str, cast) -> list:
    return [cast(x.strip()) for x in s.split(",") if x.strip()]


# ── Trial helpers ─────────────────────────────────────────────────────────────

def _classify(trial: dict[str, Any]) -> tuple[int, int, int]:
    """Return (success, silent_error, detected_failure) — exactly one is 1."""
    if trial["fully_corrected"]:
        return 1, 0, 0
    if trial["mismatched_after"] == 0:
        return 0, 1, 0   # all hashes match but bits are wrong → hash collision
    return 0, 0, 1


def _build_tasks(
    bit_lengths, hash_bits_list, group_sizes, ber_values, keys, rounds, seed
):
    """Return (tasks, metas) for all (L, h, g, ber, key_id) combinations."""
    all_tasks: list[tuple] = []
    all_metas: list[tuple] = []

    for L in bit_lengths:
        bits = [(i * 3 + 1) % 2 for i in range(L)]
        for h in hash_bits_list:
            for g in group_sizes:
                for ber in ber_values:
                    flip_count = max(1, round(ber * L))
                    for key_id in range(keys):
                        key = stable_key(seed, key_id)
                        rng = stable_rng(seed, key_id, flip_count, h, L, g, "random")
                        flip_indices = get_flip_indices(flip_count, L, "random", rng)
                        all_tasks.append((
                            bits, key, rounds, flip_indices,
                            g, g, h, "include_partial", None, 0, "crc", 1, 1,
                        ))
                        all_metas.append((L, h, g, ber, flip_count, key_id))

    return all_tasks, all_metas


def _aggregate_rows(flat_results, all_metas) -> list[dict[str, Any]]:
    rows = []
    for trial, (L, h, g, ber, fc, key_id) in zip(flat_results, all_metas):
        suc, sil, det = _classify(trial)
        rows.append({
            "bit_length": L,
            "hash_bits":  h,
            "group_size": g,
            "ber":        ber,
            "flip_count": fc,
            "key_id":     key_id,
            "overhead_ratio": compute_overhead_ratio(L, g, g, h),
            "success":         suc,
            "silent_error":    sil,
            "detected_failure": det,
            "mismatched_before": trial["mismatched_before"],
            "mismatched_after":  trial["mismatched_after"],
            "solve_time_ms":     trial["solve_time_ms"],
        })
    return rows


# ── Plotting helpers ──────────────────────────────────────────────────────────

def _plot_sdc_grid(fig, axes, rows, row_key, row_keys, row_label_fn,
                   line_key, line_vals, line_colors, line_label_fn,
                   ber_values, bit_lengths_for_title):
    """Fill a (nrows × 3) axis grid with success / SDC / detected-failure panels."""
    import matplotlib.ticker as ticker

    for row_idx, rk in enumerate(row_keys):
        ax_s = axes[row_idx][0]   # success rate
        ax_e = axes[row_idx][1]   # SDC rate (log)
        ax_d = axes[row_idx][2]   # detected failure

        for lv in line_vals:
            color = line_colors[lv]
            label = line_label_fn(lv)

            xs, ys_suc, yerr_suc = [], [], []
            xs_e, ys_sil  = [], []
            xs_d, ys_det, yerr_det = [], [], []

            for ber in sorted(ber_values):
                subset = [r for r in rows
                          if r[row_key] == rk        # type: ignore[index]
                          and r[line_key] == lv]
                subset = [r for r in subset if abs(r["ber"] - ber) < 1e-9]
                if not subset:
                    continue
                n = len(subset)
                s_rate = sum(r["success"]         for r in subset) / n
                e_rate = sum(r["silent_error"]    for r in subset) / n
                d_rate = sum(r["detected_failure"] for r in subset) / n

                se_s = math.sqrt(s_rate * (1 - s_rate) / n) if 0 < s_rate < 1 else 0
                se_d = math.sqrt(d_rate * (1 - d_rate) / n) if 0 < d_rate < 1 else 0

                xs.append(ber * 100)
                ys_suc.append(s_rate * 100)
                yerr_suc.append(se_s * 100)

                xs_e.append(ber * 100)
                ys_sil.append(max(e_rate, 1e-9))   # floor for log axis

                xs_d.append(ber * 100)
                ys_det.append(d_rate * 100)
                yerr_det.append(se_d * 100)

            ax_s.errorbar(xs, ys_suc, yerr=yerr_suc, marker="o", markersize=4,
                          linewidth=2, capsize=3, color=color, label=label)
            ax_e.semilogy(xs_e, ys_sil, marker="s", markersize=4,
                          linewidth=2, color=color, label=label)
            ax_d.errorbar(xs_d, ys_det, yerr=yerr_det, marker="^", markersize=4,
                          linewidth=2, capsize=3, color=color, label=label)

        row_title = row_label_fn(rk)
        ax_s.set_title(f"{row_title}\nSuccess rate", fontsize=9)
        ax_e.set_title(f"{row_title}\nSDC (silent-error) rate", fontsize=9)
        ax_d.set_title(f"{row_title}\nDetected-failure rate", fontsize=9)

        for ax in axes[row_idx]:
            ax.set_xlabel("BER (%)", fontsize=8)
            ax.grid(True, which="both", alpha=0.3)
            ax.legend(fontsize=7, ncol=1)
            ax.xaxis.set_major_formatter(
                ticker.FuncFormatter(lambda x, _: f"{x:.0f}%"))

        ax_s.set_ylim(-5, 105)
        ax_s.set_ylabel("Rate (%)", fontsize=8)
        ax_s.yaxis.set_major_formatter(ticker.PercentFormatter())
        ax_s.axhline(100, linestyle="--", color="gray", linewidth=1, alpha=0.5)

        ax_e.set_ylabel("Rate (log scale)", fontsize=8)
        ax_e.set_ylim(1e-5, 1.2)
        ax_e.yaxis.set_major_formatter(
            ticker.FuncFormatter(lambda y, _: f"{y:.1e}".replace("e-0", "e-")
                                              .replace("e+0", "e+")))
        ax_e.axhline(1e-3, linestyle=":", color="gray", linewidth=1, alpha=0.5,
                     label="10⁻³ reference")
        ax_e.text(0.02, 0.15, "Values at 0 events shown\nat detection floor (1/n_keys)",
                  transform=ax_e.transAxes, fontsize=6.5, color="gray",
                  bbox=dict(boxstyle="round,pad=0.2", facecolor="lightyellow",
                            edgecolor="gray", alpha=0.7))

        ax_d.set_ylim(-5, 105)
        ax_d.set_ylabel("Rate (%)", fontsize=8)
        ax_d.yaxis.set_major_formatter(ticker.PercentFormatter())


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    args = parse_args()
    bit_lengths    = _parse_list(args.bit_lengths, int)
    hash_bits_list = _parse_list(args.hash_bits,   int)
    ber_values     = _parse_list(args.ber_values,   float)
    ensure_dir(args.out_dir)

    write_json(os.path.join(args.out_dir, "config.json"), {
        "bit_lengths": bit_lengths,
        "hash_bits":   hash_bits_list,
        "group_sizes": DEFAULT_GROUP_SIZES,
        "ber_values":  ber_values,
        "keys":        args.keys,
        "rounds":      args.rounds,
        "seed":        args.seed,
    })

    # ── Figure 1 tasks: vary (L, h) with group_size = 1 ──────────────────
    print(f"Building tasks for main figure  "
          f"(group_size={FIXED_GROUP_SIZE}, {len(bit_lengths)} block sizes, "
          f"{len(hash_bits_list)} CRC widths, {len(ber_values)} BER points, "
          f"{args.keys} keys)...")
    fig1_tasks, fig1_metas = _build_tasks(
        bit_lengths, hash_bits_list, [FIXED_GROUP_SIZE],
        ber_values, args.keys, args.rounds, args.seed
    )
    print(f"  {len(fig1_tasks)} trials")

    # ── Figure 2 tasks: vary (g, h) with fixed L ─────────────────────────
    fig2_tasks, fig2_metas = [], []
    if not args.no_groupsize_fig:
        print(f"Building tasks for group-size figure  "
              f"(L={FIXED_BIT_LENGTH_GS}, {len(DEFAULT_GROUP_SIZES)} group sizes)...")
        fig2_tasks, fig2_metas = _build_tasks(
            [FIXED_BIT_LENGTH_GS], hash_bits_list, DEFAULT_GROUP_SIZES,
            ber_values, args.keys, args.rounds, args.seed
        )
        print(f"  {len(fig2_tasks)} trials")

    all_tasks = fig1_tasks + fig2_tasks
    all_metas = fig1_metas + fig2_metas

    print(f"\nRunning {len(all_tasks)} trials total...")
    if args.parallel:
        flat = run_trials_parallel(all_tasks, args.workers)
    else:
        flat = run_trials_serial(all_tasks)

    all_rows = _aggregate_rows(flat, all_metas)

    # Write CSV
    fieldnames = [
        "bit_length", "hash_bits", "group_size", "ber", "flip_count", "key_id",
        "overhead_ratio", "success", "silent_error", "detected_failure",
        "mismatched_before", "mismatched_after", "solve_time_ms",
    ]
    write_csv(os.path.join(args.out_dir, "fig_sdc_trials.csv"), all_rows, fieldnames)

    # Print summary
    print(f"\n{'L':>6}  {'h':>3}  {'g':>2}  {'BER':>6}  "
          f"{'success':>8}  {'SDC':>10}  {'detected':>9}")
    print("-" * 60)
    for L in bit_lengths + ([FIXED_BIT_LENGTH_GS]
                            if not args.no_groupsize_fig else []):
        for h in hash_bits_list:
            for g in ([FIXED_GROUP_SIZE] if L != FIXED_BIT_LENGTH_GS
                      else DEFAULT_GROUP_SIZES):
                for ber in ber_values:
                    subset = [r for r in all_rows
                              if r["bit_length"] == L and r["hash_bits"] == h
                              and r["group_size"] == g
                              and abs(r["ber"] - ber) < 1e-9]
                    if not subset:
                        continue
                    n = len(subset)
                    s = sum(r["success"]         for r in subset) / n
                    e = sum(r["silent_error"]    for r in subset) / n
                    d = sum(r["detected_failure"] for r in subset) / n
                    print(f"{L:>6}  {h:>3}  {g:>2}  {ber:>5.1%}  "
                          f"{s:>8.1%}  {e:>10.2e}  {d:>9.1%}")

    if args.no_plot:
        return

    try:
        import matplotlib.pyplot as plt
    except ModuleNotFoundError as e:
        raise RuntimeError("matplotlib required; install it or use --no-plot") from e

    # ── Figure 1: vary hash_bits, rows = block sizes ──────────────────────
    fig1_rows = [r for r in all_rows if r["group_size"] == FIXED_GROUP_SIZE]
    fig1, axes1 = plt.subplots(
        len(bit_lengths), 3,
        figsize=(15, 5 * len(bit_lengths)),
        squeeze=False,
    )
    fig1.suptitle(
        f"SDC & Error Floor — group_size = {FIXED_GROUP_SIZE}  "
        f"({args.keys} keys/cell)",
        fontsize=13, fontweight="bold",
    )

    row_key = "bit_length"
    _plot_sdc_grid(
        fig1, axes1,
        rows=fig1_rows,
        row_key="bit_length",
        row_keys=bit_lengths,
        row_label_fn=lambda L: f"L = {L:,} bits",
        line_key="hash_bits",
        line_vals=hash_bits_list,
        line_colors=HASH_COLORS,
        line_label_fn=lambda h: f"CRC-{h}  ({compute_overhead_ratio(4096, FIXED_GROUP_SIZE, FIXED_GROUP_SIZE, h):.0%} OH at 4 096b)",
        ber_values=ber_values,
        bit_lengths_for_title=bit_lengths,
    )

    plt.tight_layout()
    out1 = os.path.join(args.out_dir, "fig_sdc.png")
    fig1.savefig(out1, dpi=200, bbox_inches="tight")
    plt.close(fig1)
    print(f"Saved: {out1}")

    # ── Figure 2: vary group_size, rows = hash_bits ───────────────────────
    if args.no_groupsize_fig:
        return

    fig2_rows = [r for r in all_rows if r["bit_length"] == FIXED_BIT_LENGTH_GS]
    fig2, axes2 = plt.subplots(
        len(hash_bits_list), 3,
        figsize=(15, 5 * len(hash_bits_list)),
        squeeze=False,
    )
    fig2.suptitle(
        f"SDC & Error Floor — block size = {FIXED_BIT_LENGTH_GS:,} bits  "
        f"({args.keys} keys/cell)",
        fontsize=13, fontweight="bold",
    )

    _plot_sdc_grid(
        fig2, axes2,
        rows=fig2_rows,
        row_key="hash_bits",
        row_keys=hash_bits_list,
        row_label_fn=lambda h: f"CRC-{h}",
        line_key="group_size",
        line_vals=DEFAULT_GROUP_SIZES,
        line_colors=GS_COLORS,
        line_label_fn=lambda g: (
            f"group={g}  "
            f"({compute_overhead_ratio(FIXED_BIT_LENGTH_GS, g, g, 16):.0%} OH)"
        ),
        ber_values=ber_values,
        bit_lengths_for_title=[FIXED_BIT_LENGTH_GS],
    )

    plt.tight_layout()
    out2 = os.path.join(args.out_dir, "fig_sdc_groupsize.png")
    fig2.savefig(out2, dpi=200, bbox_inches="tight")
    plt.close(fig2)
    print(f"Saved: {out2}")


if __name__ == "__main__":
    main()
