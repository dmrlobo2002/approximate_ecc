"""Figure: Overhead crossover — Approximate ECC vs BCH and Reed-Solomon.

Purely analytical — no solver trials needed, runs in seconds.

Outputs (to --out-dir):
  fig_crossover.png  — 3×3 panel comprehensive figure

Panel layout
────────────
Row 0  Overhead (%) vs BER          at L = 256, 1 024, 4 096 bits
Row 1  Overhead (%) vs block size   at BER = 2%, 5%, 10%
Row 2  Crossover BER vs block size  one panel per group_size ∈ {1, 2, 4}
         Solid line  = BER where our overhead first equals BCH overhead.
         Dashed line = same threshold vs Reed-Solomon.
         Below a curve → our scheme has *lower* overhead than the reference.

Our scheme is swept across all 9 configs:
  hash_bits ∈ {8, 16, 32}  ×  group_size ∈ {1, 2, 4}

BCH model  : tile 256-bit BCH(256, t) blocks.  t = ⌈BER × 256⌉ per block.
             Overhead = BCH(256, t) overhead ratio — constant in L (exact
             cyclotomic coset computation).
RS  model  : tile RS(255) codewords over GF(2⁸) bytes.  t = ⌈255 × p_sym⌉
             per codeword, p_sym = 1−(1−BER)⁸.  Overhead = 2t/(255−2t) —
             constant in L.
"""
from __future__ import annotations

import argparse
import math
import os
from typing import Optional

from experiments.common import compute_overhead_ratio, ensure_dir
from experiments.ecc_comparison import (
    bch_overhead as _bch_overhead,
    bch_t_for_target_success,
)

# ── Config space ──────────────────────────────────────────────────────────────
HASH_BITS_LIST = [8, 16, 32]
GROUP_SIZES    = [1, 2, 4]

BLOCK_SIZES_ROW0   = [256, 1024, 4096]
BER_VALUES_ROW1    = [0.02, 0.05, 0.10]
BLOCK_SIZES_SWEEP  = [128, 256, 512, 1024, 2048, 4096, 8192, 16384]
BER_RANGE          = (0.001, 0.25)   # log-swept x-axis for overhead-vs-BER panels
BER_POINTS         = 300

# ── Visual style ──────────────────────────────────────────────────────────────
CONFIG_COLORS   = {8: "#e41a1c", 16: "#377eb8", 32: "#4daf4a"}
GROUP_LINESTYLE = {1: "-", 2: "--", 4: ":"}
BCH_COLOR        = "#8c2d04"   # dark red
BCH_HONEST_COLOR = "#4a1486"   # dark purple — honest-t (95% success)
RS_COLOR         = "#f16913"   # orange
BCH_LS           = "-"
BCH_HONEST_LS    = "--"
RS_LS            = "-."


# ── Analytical overhead functions ─────────────────────────────────────────────

def bch_overhead_ratio(L: int, ber: float) -> float:
    """BCH overhead using 256-bit tiling model.

    t errors correctable per 256-bit sub-block; overhead ratio is constant in L
    (same as BCH(256, t) overhead, independent of total block size).
    """
    t = max(1, round(ber * 256))
    return min(_bch_overhead(256, t)["overhead_ratio"], 2.5)


def rs_overhead_ratio(L: int, ber: float, symbol_bits: int = 8) -> float:
    """RS overhead using 255-symbol (GF(2^8)) tiling model.

    t errors correctable per RS(255) codeword; overhead ratio = 2t/(255-2t),
    constant in L once you tile multiple codewords for larger blocks.
    """
    if L <= symbol_bits or ber <= 0.0:
        return 0.0
    p_sym = 1.0 - (1.0 - ber) ** symbol_bits
    t = math.ceil(255 * p_sym)   # expected errors per 255-symbol codeword
    if t >= 128:
        return 2.5
    data_sym = 255 - 2 * t
    if data_sym <= 0:
        return 2.5
    return min((2 * t) / data_sym, 2.5)


def bch_overhead_ratio_honest(L: int, ber: float, target: float = 0.95) -> float:
    """BCH overhead using honest-t: min t for 95% system success under random errors.

    Unlike bch_overhead_ratio(), this INCREASES with L because more 256-bit sub-blocks
    demand higher per-block reliability to hit the system-level target.
    """
    n_blocks = math.ceil(L / 256)
    t = bch_t_for_target_success(ber, n_blocks, target_prob=target)
    return min(_bch_overhead(256, t)["overhead_ratio"], 2.5)


def our_overhead_ratio(L: int, h: int, g: int) -> float:
    return compute_overhead_ratio(L, g, g, h)


def crossover_ber(L: int, h: int, g: int, ref: str = "bch") -> Optional[float]:
    """Binary-search for the BER at which reference overhead = our overhead.

    Returns the crossover BER, or None if no crossover exists in (0, 1).
    'Below' the crossover BER → our scheme is cheaper than the reference.
    """
    our = our_overhead_ratio(L, h, g)
    ref_fn = bch_overhead_ratio if ref == "bch" else rs_overhead_ratio

    hi_ber = 0.9999
    if ref_fn(L, hi_ber) < our:
        return None          # reference always cheaper

    lo_ber = 1e-6
    if ref_fn(L, lo_ber) >= our:
        return lo_ber        # reference already more expensive at tiniest BER

    lo, hi = lo_ber, hi_ber
    for _ in range(80):
        mid = (lo + hi) / 2
        if ref_fn(L, mid) < our:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def crossover_ber_honest(
    L: int, h: int, g: int, target: float = 0.95
) -> Optional[float]:
    """Binary-search crossover BER for honest BCH (95% success target).

    Returns BER above which our scheme has lower overhead than honest BCH,
    or None if honest BCH is always cheaper.
    """
    our = our_overhead_ratio(L, h, g)
    hi_ber = 0.9999
    if bch_overhead_ratio_honest(L, hi_ber, target) < our:
        return None
    lo_ber = 1e-6
    if bch_overhead_ratio_honest(L, lo_ber, target) >= our:
        return lo_ber
    lo, hi = lo_ber, hi_ber
    for _ in range(80):
        mid = (lo + hi) / 2
        if bch_overhead_ratio_honest(L, mid, target) < our:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Overhead crossover: Approximate ECC vs BCH and Reed-Solomon"
    )
    p.add_argument("--out-dir", default="results/fig_crossover")
    p.add_argument("--no-plot", action="store_true",
                   help="Print crossover table and exit without plotting")
    return p.parse_args()


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    args = parse_args()
    ensure_dir(args.out_dir)

    # Always print the crossover table
    print(f"\n{'L':>6}  {'h':>3}  {'g':>2}  {'our OH':>8}  "
          f"{'BCH cross':>10}  {'BCH honest':>11}  {'RS cross':>10}")
    print("-" * 62)
    for L in BLOCK_SIZES_SWEEP:
        for h in HASH_BITS_LIST:
            for g in GROUP_SIZES:
                our = our_overhead_ratio(L, h, g)
                cx_b = crossover_ber(L, h, g, "bch")
                cx_bh = crossover_ber_honest(L, h, g)
                cx_r = crossover_ber(L, h, g, "rs")
                b_str  = f"{cx_b:.2%}"  if cx_b  is not None else "never"
                bh_str = f"{cx_bh:.2%}" if cx_bh is not None else "never"
                r_str  = f"{cx_r:.2%}"  if cx_r  is not None else "never"
                print(f"{L:>6}  {h:>3}  {g:>2}  {our:>7.1%}  {b_str:>10}  {bh_str:>11}  {r_str:>10}")

    if args.no_plot:
        return

    try:
        import matplotlib.pyplot as plt
        import matplotlib.ticker as ticker
        from matplotlib.gridspec import GridSpec
    except ModuleNotFoundError as e:
        raise RuntimeError("matplotlib required; install it or use --no-plot") from e

    # Log-spaced BER sweep
    bers = [
        BER_RANGE[0] * (BER_RANGE[1] / BER_RANGE[0]) ** (i / (BER_POINTS - 1))
        for i in range(BER_POINTS)
    ]

    fig = plt.figure(figsize=(21, 18))
    fig.suptitle(
        "Overhead Crossover: Approximate ECC vs BCH and Reed-Solomon  (analytical)",
        fontsize=14, fontweight="bold",
    )
    gs = GridSpec(3, 3, figure=fig, hspace=0.50, wspace=0.35)
    axes = [[fig.add_subplot(gs[r, c]) for c in range(3)] for r in range(3)]

    # ── Row 0: overhead % vs BER, one panel per block size ───────────────
    for col, L in enumerate(BLOCK_SIZES_ROW0):
        ax = axes[0][col]

        bch_ys        = [bch_overhead_ratio(L, b)        * 100 for b in bers]
        bch_honest_ys = [bch_overhead_ratio_honest(L, b) * 100 for b in bers]
        rs_ys         = [rs_overhead_ratio(L, b)         * 100 for b in bers]
        ax.plot(bers, bch_ys, color=BCH_COLOR, linewidth=2.5, linestyle=BCH_LS,
                label="BCH (expected-t)", zorder=4)
        ax.plot(bers, bch_honest_ys, color=BCH_HONEST_COLOR, linewidth=2.0,
                linestyle=BCH_HONEST_LS,
                label="BCH (95%-success honest-t)" if col == 0 else None, zorder=4)
        ax.plot(bers, rs_ys,  color=RS_COLOR,  linewidth=2.5, linestyle=RS_LS,
                label="RS (GF 2⁸)", zorder=4)

        for g in GROUP_SIZES:
            for h in HASH_BITS_LIST:
                our_pct = our_overhead_ratio(L, h, g) * 100
                color = CONFIG_COLORS[h]
                ls    = GROUP_LINESTYLE[g]
                lbl   = f"h={h}, g={g}  ({our_pct:.0f}%)" if col == 0 else None
                ax.axhline(our_pct, color=color, linestyle=ls,
                           linewidth=1.4, alpha=0.85, label=lbl, zorder=3)

                # Crossover dots
                for ref, ref_fn, mk in [
                    ("bch", bch_overhead_ratio, "o"),
                    ("rs",  rs_overhead_ratio,  "s"),
                ]:
                    cx = crossover_ber(L, h, g, ref)
                    if cx is not None and BER_RANGE[0] < cx < BER_RANGE[1]:
                        ax.plot(cx, our_pct, marker=mk, color=color, markersize=6,
                                zorder=6, markeredgecolor="white", markeredgewidth=0.7)

        ax.set_xscale("log")
        ax.set_xlabel("Bit Error Rate (BER)", fontsize=9)
        ax.set_ylabel("Overhead (%)" if col == 0 else "", fontsize=9)
        ax.set_title(f"Overhead vs BER   (L = {L:,} bits)", fontsize=10)
        ax.set_xlim(BER_RANGE)
        ax.set_ylim(0, 160)
        ax.grid(True, which="both", alpha=0.25)
        ax.xaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f"{x:.0%}"))
        ax.yaxis.set_major_formatter(ticker.PercentFormatter())
        if col == 0:
            ax.legend(fontsize=6.5, ncol=2, loc="upper left",
                      framealpha=0.85, borderpad=0.5)
        ax.text(0.97, 0.95, "● = BCH crossover\n■ = RS crossover",
                transform=ax.transAxes, fontsize=7, ha="right", va="top",
                bbox=dict(boxstyle="round,pad=0.3", facecolor="lightyellow",
                          edgecolor="gray", alpha=0.8))

    # ── Row 1: overhead % vs block size, one panel per BER value ─────────
    Ls_sweep = BLOCK_SIZES_SWEEP
    for col, ber in enumerate(BER_VALUES_ROW1):
        ax = axes[1][col]

        bch_ys        = [bch_overhead_ratio(L, ber)        * 100 for L in Ls_sweep]
        bch_honest_ys = [bch_overhead_ratio_honest(L, ber) * 100 for L in Ls_sweep]
        rs_ys         = [rs_overhead_ratio(L, ber)         * 100 for L in Ls_sweep]
        ax.plot(Ls_sweep, bch_ys, color=BCH_COLOR, linewidth=2.5,
                linestyle=BCH_LS, marker="s", markersize=4, label="BCH (expected-t)", zorder=4)
        ax.plot(Ls_sweep, bch_honest_ys, color=BCH_HONEST_COLOR, linewidth=2.0,
                linestyle=BCH_HONEST_LS, marker="D", markersize=4,
                label="BCH (95%-success honest-t)" if col == 0 else None, zorder=4)
        ax.plot(Ls_sweep, rs_ys,  color=RS_COLOR,  linewidth=2.5,
                linestyle=RS_LS,  marker="^", markersize=4,
                label="RS (GF 2⁸)", zorder=4)

        for g in GROUP_SIZES:
            for h in HASH_BITS_LIST:
                our_ys = [our_overhead_ratio(L, h, g) * 100 for L in Ls_sweep]
                color  = CONFIG_COLORS[h]
                ls     = GROUP_LINESTYLE[g]
                lbl    = f"h={h}, g={g}" if col == 0 else None
                ax.plot(Ls_sweep, our_ys, color=color, linestyle=ls,
                        linewidth=1.4, alpha=0.85, marker="o", markersize=3,
                        label=lbl, zorder=3)

                # Mark crossover block size
                for ref, ref_fn, mk in [
                    ("bch", bch_overhead_ratio, "o"),
                    ("rs",  rs_overhead_ratio,  "s"),
                ]:
                    # Find first L where our overhead < reference
                    prev_our = None
                    for Li in Ls_sweep:
                        o = our_overhead_ratio(Li, h, g) * 100
                        r = ref_fn(Li, ber) * 100
                        if prev_our is not None and o < r:
                            ax.plot(Li, o, marker=mk, color=color, markersize=6,
                                    zorder=6, markeredgecolor="white",
                                    markeredgewidth=0.7)
                            break
                        prev_our = o

        ax.set_xscale("log", base=2)
        ax.set_xlabel("Block size (bits)", fontsize=9)
        ax.set_ylabel("Overhead (%)" if col == 0 else "", fontsize=9)
        ax.set_title(f"Overhead vs Block Size   (BER = {ber:.0%})", fontsize=10)
        ax.set_ylim(0, 160)
        ax.grid(True, which="both", alpha=0.25)
        ax.xaxis.set_major_formatter(
            ticker.FuncFormatter(lambda x, _: f"{int(x):,}"))
        ax.yaxis.set_major_formatter(ticker.PercentFormatter())
        if col == 0:
            ax.legend(fontsize=6.5, ncol=2, loc="upper right",
                      framealpha=0.85, borderpad=0.5)

    # ── Row 2: crossover BER vs block size, one panel per group_size ─────
    for col, g in enumerate(GROUP_SIZES):
        ax = axes[2][col]

        for h in HASH_BITS_LIST:
            color = CONFIG_COLORS[h]
            for ref, ls, mk, lbl_sfx in [
                ("bch", "-",  "o", "vs BCH (expected-t)"),
                ("rs",  "--", "s", "vs RS"),
            ]:
                xs, ys = [], []
                for L in Ls_sweep:
                    cx = crossover_ber(L, h, g, ref)
                    if cx is not None:
                        xs.append(L)
                        ys.append(cx * 100)
                if xs:
                    ax.plot(xs, ys, color=color, linestyle=ls, linewidth=1.8,
                            marker=mk, markersize=4,
                            label=f"h={h} {lbl_sfx}")

            # Honest BCH crossover (95%-success target)
            xs_h, ys_h = [], []
            for L in Ls_sweep:
                cx_h = crossover_ber_honest(L, h, g)
                if cx_h is not None:
                    xs_h.append(L)
                    ys_h.append(cx_h * 100)
            if xs_h:
                ax.plot(xs_h, ys_h, color=color, linestyle=":", linewidth=1.8,
                        marker="D", markersize=4,
                        label=f"h={h} vs BCH (honest-t)")

        ax.set_xscale("log", base=2)
        ax.set_xlabel("Block size (bits)", fontsize=9)
        ax.set_ylabel("Crossover BER (%)" if col == 0 else "", fontsize=9)
        ax.set_title(
            f"Crossover BER vs Block Size   (group_size = {g})\n"
            f"At BER above a curve, our scheme has lower overhead",
            fontsize=9,
        )
        ax.grid(True, which="both", alpha=0.25)
        ax.xaxis.set_major_formatter(
            ticker.FuncFormatter(lambda x, _: f"{int(x):,}"))
        ax.yaxis.set_major_formatter(
            ticker.FuncFormatter(lambda y, _: f"{y:.1f}%"))
        ax.legend(fontsize=7, ncol=2, framealpha=0.85)
        # Shade region above the lowest crossover curve
        ax.text(0.03, 0.93,
                "← smaller block needs higher BER\n   before our overhead wins",
                transform=ax.transAxes, fontsize=7, color="#555555", va="top")

    plt.tight_layout()
    out_path = os.path.join(args.out_dir, "fig_crossover.png")
    plt.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close()
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
