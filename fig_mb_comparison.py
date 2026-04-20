"""
Overhead comparison: Approximate ECC vs BCH — 1 MB block, analytical.

Panel A: Overhead (%) vs BER (%) at 1 MB.
  - BCH curve: exact parity bits via 2-cyclotomic cosets (same math as fig2).
  - Our scheme: horizontal lines — overhead is fixed regardless of BER.
  - Crossover points annotated.

Panel B: Overhead (%) vs block size (bits), at fixed BER = 1%.
  - Shows how each scheme scales as data grows.
"""
from __future__ import annotations

import math
import os

from experiments.common import compute_overhead_ratio, ensure_dir
from experiments.ecc_comparison import bch_overhead, bch_t_for_target_success

OUT_DIR = "results/fig_mb"
DATA_BITS = 1024 * 1024 * 8  # 1 MB

OUR_CONFIGS = [
    (32, "#4daf4a", "Ours — 32-bit CRC"),
    (64, "#984ea3", "Ours — 64-bit CRC"),
]

# BER sweep: from 0.0001% to 10%
BER_POINTS = 120
BER_MIN = 1e-4   # %
BER_MAX = 10.0   # %

# Block size sweep for Panel B
BLOCK_SIZES = [
    1024,
    4 * 1024,
    16 * 1024,
    64 * 1024,
    256 * 1024,
    1024 * 1024,
    4 * 1024 * 1024,
    16 * 1024 * 1024,
]
BER_FIXED = 1.0  # % for Panel B


def our_overhead_pct(bit_length: int, hash_bits: int) -> float:
    return compute_overhead_ratio(bit_length, 1, 1, hash_bits) * 100


def bch_overhead_pct(bit_length: int, ber_pct: float) -> float | None:
    # t is errors per 256-bit sub-block (tiling model), NOT total errors in bit_length.
    # BCH overhead ratio is constant in block size once you tile BCH(256, t) codewords.
    t = max(1, round(ber_pct / 100 * 256))
    info = bch_overhead(256, t)
    return info["overhead_ratio"] * 100


def bch_overhead_pct_honest(bit_length: int, ber_pct: float, target: float = 0.95) -> float:
    """BCH overhead for 256-bit tiling at the t required for `target` system success rate.

    Unlike bch_overhead_pct(), this increases with bit_length: more sub-blocks demand
    higher per-block reliability to hit the system-level target.
    """
    n_blocks = math.ceil(bit_length / 256)
    t = bch_t_for_target_success(ber_pct / 100.0, n_blocks, target_prob=target)
    return bch_overhead(256, t)["overhead_ratio"] * 100


def crossover_ber(bit_length: int, hash_bits: int) -> float:
    """BER (%) at which BCH overhead equals our overhead."""
    our_pct = our_overhead_pct(bit_length, hash_bits)
    m = max(1, math.ceil(math.log2(bit_length + 1)))
    # BCH overhead ≈ t * parity_per_error / bit_length * 100
    # At crossover: our_pct = bch_t * m / bit_length * 100
    # bch_t = our_pct * bit_length / (m * 100)
    # BER = bch_t / bit_length * 100 = our_pct / m
    return our_pct / m  # approximate; refine with exact calculation below


def exact_crossover_ber(bit_length: int, hash_bits: int) -> float:
    """Binary search for exact crossover BER (%)."""
    our_pct = our_overhead_pct(bit_length, hash_bits)
    lo, hi = 1e-6, 50.0
    for _ in range(60):
        mid = (lo + hi) / 2
        bch_pct = bch_overhead_pct(bit_length, mid)
        if bch_pct is None or bch_pct < our_pct:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def main() -> None:
    ensure_dir(OUT_DIR)

    try:
        import matplotlib.pyplot as plt
        import matplotlib.ticker as ticker
    except ModuleNotFoundError as e:
        raise RuntimeError("matplotlib required: pip install matplotlib") from e

    # ── Panel A data ────────────────────────────────────────────────────────
    bers = [BER_MIN * (BER_MAX / BER_MIN) ** (i / (BER_POINTS - 1))
            for i in range(BER_POINTS)]

    bch_overheads = [bch_overhead_pct(DATA_BITS, ber) for ber in bers]
    bch_honest_overheads = [bch_overhead_pct_honest(DATA_BITS, ber) for ber in bers]

    our_pcts = {hb: our_overhead_pct(DATA_BITS, hb) for hb, _, _ in OUR_CONFIGS}
    crossovers = {hb: exact_crossover_ber(DATA_BITS, hb) for hb, _, _ in OUR_CONFIGS}

    # ── Panel B data ────────────────────────────────────────────────────────
    bch_scale = []
    bch_honest_scale = []
    for bs in BLOCK_SIZES:
        pct = bch_overhead_pct(bs, BER_FIXED)
        bch_scale.append(pct if pct is not None else float("nan"))
        bch_honest_scale.append(bch_overhead_pct_honest(bs, BER_FIXED))

    our_scale = {
        hb: [our_overhead_pct(bs, hb) for bs in BLOCK_SIZES]
        for hb, _, _ in OUR_CONFIGS
    }

    # ── Plot ────────────────────────────────────────────────────────────────
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 7))
    fig.suptitle(
        "Approximate ECC vs BCH — Overhead Comparison (analytical)",
        fontsize=14, fontweight="bold",
    )

    # --- Panel A: overhead vs BER at 1 MB ---
    ax1.plot(bers, bch_overheads,
             color="#d62728", linewidth=2.5, label="BCH (expected-t, constant overhead)")
    ax1.plot(bers, bch_honest_overheads,
             color="#4a1486", linewidth=2.5, linestyle="--",
             label="BCH (honest-t, 95% success — rises with L)")

    for hash_bits, color, label in OUR_CONFIGS:
        pct = our_pcts[hash_bits]
        cx = crossovers[hash_bits]
        ax1.axhline(pct, color=color, linewidth=2, linestyle="--",
                    label=f"{label}  ({pct:.2f}% overhead, fixed)")
        # Crossover annotation
        ax1.axvline(cx, color=color, linewidth=0.8, linestyle=":", alpha=0.7)
        ax1.annotate(
            f"crossover\n{cx:.3f}% BER",
            xy=(cx, pct),
            xytext=(cx * 2.5, pct * 1.3),
            fontsize=8, color=color,
            arrowprops=dict(arrowstyle="->", color=color, lw=1.0),
        )

    # Reference lines
    for ref_ber, label in [(1.0, "1% BER"), (5.0, "5% BER")]:
        ax1.axvline(ref_ber, color="gray", linewidth=0.8, linestyle=":", alpha=0.5)
        ax1.text(ref_ber * 1.05, ax1.get_ylim()[1] * 0.02 if ax1.get_ylim()[1] > 0 else 1,
                 label, fontsize=7, color="gray", va="bottom")

    ax1.set_xscale("log")
    ax1.set_yscale("log")
    ax1.set_xlabel("Bit Error Rate — BER (%)", fontsize=11)
    ax1.set_ylabel("ECC Overhead (%)", fontsize=11)
    ax1.set_title(f"Overhead vs BER  (block size = 1 MB = {DATA_BITS:,} bits)", fontsize=11)
    ax1.set_xlim(BER_MIN * 0.8, BER_MAX * 1.2)
    ax1.set_ylim(0.001, 200)
    ax1.grid(True, which="both", alpha=0.3)
    ax1.legend(fontsize=9, loc="upper left")

    ax1.yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f"{x:g}%"))
    ax1.xaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f"{x:g}%"))

    # Shade region where ours wins (below BCH, above our line)
    for hash_bits, color, _ in OUR_CONFIGS:
        pct = our_pcts[hash_bits]
        ours_line = [pct] * len(bers)
        ax1.fill_between(bers, ours_line, bch_overheads,
                         where=[b > pct for b in bch_overheads],
                         alpha=0.07, color=color)

    # --- Panel B: overhead vs block size at BER=1% ---
    bs_bits = BLOCK_SIZES
    ax2.plot(bs_bits, bch_scale,
             color="#d62728", linewidth=2.5, marker="s", markersize=6,
             label=f"BCH expected-t  (BER = {BER_FIXED}%)")
    ax2.plot(bs_bits, bch_honest_scale,
             color="#4a1486", linewidth=2.5, linestyle="--", marker="D", markersize=6,
             label=f"BCH honest-t 95% success  (BER = {BER_FIXED}%)")

    for hash_bits, color, label in OUR_CONFIGS:
        ax2.plot(bs_bits, our_scale[hash_bits],
                 color=color, linewidth=2, linestyle="--", marker="o", markersize=6,
                 label=label)

    ax2.set_xscale("log", base=2)
    ax2.set_yscale("log")
    ax2.set_xlabel("Block size (bits)", fontsize=11)
    ax2.set_ylabel("ECC Overhead (%)", fontsize=11)
    ax2.set_title(f"Overhead vs Block Size  (fixed BER = {BER_FIXED}%)", fontsize=11)
    ax2.grid(True, which="both", alpha=0.3)
    ax2.legend(fontsize=9)

    ax2.xaxis.set_major_formatter(
        ticker.FuncFormatter(lambda x, _: (
            f"{int(x)//1024}K" if x < 1024*1024
            else f"{int(x)//(1024*1024)}M"
        ))
    )
    ax2.yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f"{x:g}%"))

    # Annotate 1 MB on Panel B
    ax2.axvline(DATA_BITS, color="gray", linewidth=1, linestyle=":", alpha=0.6)
    ax2.text(DATA_BITS * 1.1, ax2.get_ylim()[0] * 2 if ax2.get_ylim()[0] > 0 else 0.01,
             "1 MB", fontsize=8, color="gray")

    plt.tight_layout()
    out_path = os.path.join(OUT_DIR, "fig_mb_comparison.png")
    plt.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close()
    print(f"Saved: {out_path}")

    # ── Print summary table ─────────────────────────────────────────────────
    print(f"\n{'BER':>10}  {'t/block':>8}  {'BCH OH':>10}  {'BCH honest OH':>14}", end="")
    for hb, _, _ in OUR_CONFIGS:
        print(f"  {'Ours '+str(hb)+'b':>12}", end="")
    print()
    print("-" * (10 + 10 + 12 + 16 + len(OUR_CONFIGS) * 14 + 4))
    for ber in [0.001, 0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0, 10.0]:
        t = max(1, round(ber / 100 * 256))
        bch_pct = bch_overhead(256, t)["overhead_ratio"] * 100
        bch_honest_pct = bch_overhead_pct_honest(DATA_BITS, ber)
        print(f"{ber:>9.3f}%  {t:>8}  {bch_pct:>9.3f}%  {bch_honest_pct:>13.3f}%", end="")
        for hb, _, _ in OUR_CONFIGS:
            print(f"  {our_pcts[hb]:>11.3f}%", end="")
        print()

    print("\nCrossover BERs (BCH overhead = our overhead):")
    for hb, _, label in OUR_CONFIGS:
        cx = crossovers[hb]
        cx_t = round(cx / 100 * DATA_BITS)
        print(f"  {label}: {cx:.4f}% BER  ({cx_t:,} flips)")


if __name__ == "__main__":
    main()
