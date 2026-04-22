"""Overhead vs block size — our scheme vs RS (left panel) and BCH (right panel).

Each panel shows 7 BER levels (0.1%–5%) as a color family (light→dark).
Lines are labeled directly at the right end. Crossover points (where our
scheme becomes cheaper) are marked on the our-scheme line for each BER.

RS model: GF(2^8), 255-byte codewords, t = ceil(255·P/(1+2P)), P = 1-(1-BER)^8.
BCH model: tiled 256-bit blocks, t = round(BER·256) per block.
"""
from __future__ import annotations

import math
import os

from experiments.common import compute_overhead_ratio, ensure_dir
from experiments.ecc_comparison import bch_overhead

OUT_DIR     = "results/fig_overhead_zones"
HASH_BITS   = 32
SYMBOL_BITS = 8
BER_LEVELS  = [0.001, 0.005, 0.01, 0.02, 0.03, 0.04, 0.05]
BLOCK_SIZES = [512, 1024, 2048, 4096, 8192, 16384, 32768, 65536, 131072, 262144, 524288]


def our_oh(L: int) -> float:
    return compute_overhead_ratio(L, 1, 1, HASH_BITS) * 100


def rs_oh(L: int, ber: float) -> float | None:
    P = 1.0 - (1.0 - ber) ** SYMBOL_BITS
    t = max(1, math.ceil(255 * P / (1 + 2 * P)))
    if t >= 128:
        return None
    k = 255 - 2 * t
    n_chunks = math.ceil((L // 8) / k)
    return n_chunks * 2 * t / (L // 8) * 100


def bch_oh(L: int, ber: float) -> float:
    t = max(1, round(ber * 256))
    return bch_overhead(L, t)["overhead_ratio"] * 100


def find_crossover(scheme_fn, ber: float) -> float | None:
    """Block size where our_oh(L) first drops below scheme_fn(L, ber)."""
    # Analytical: our_oh ≈ 2*HASH_BITS*100/sqrt(L); solve for scheme asymptote
    asymptote = scheme_fn(BLOCK_SIZES[-1], ber)
    if asymptote is None or math.isnan(asymptote):
        return None
    if asymptote <= 0:
        return None
    L_cross = (2 * HASH_BITS * 100 / asymptote) ** 2
    if L_cross < BLOCK_SIZES[0] or L_cross > BLOCK_SIZES[-1]:
        return None
    return L_cross


def main() -> None:
    ensure_dir(OUT_DIR)

    ours = [our_oh(L) for L in BLOCK_SIZES]

    try:
        import matplotlib.pyplot as plt
        import matplotlib.ticker as mticker
    except ModuleNotFoundError as e:
        raise RuntimeError("matplotlib required") from e

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(18, 7))
    fig.suptitle(
        f"Overhead vs Block Size — Our Scheme vs RS and BCH\n"
        f"BER levels: {', '.join(f'{b*100:.1f}%' for b in BER_LEVELS)}  (lighter = lower BER)",
        fontsize=13, fontweight="bold",
    )

    n = len(BER_LEVELS)
    # Skip very light shades so lines are always visible
    rs_colors  = [plt.cm.Greens(0.35  + 0.55 * i / (n - 1)) for i in range(n)]
    bch_colors = [plt.cm.Purples(0.35 + 0.55 * i / (n - 1)) for i in range(n)]

    panels = [
        (ax1, "RS",  rs_oh,  rs_colors,  "--", "Reed-Solomon vs Ours"),
        (ax2, "BCH", bch_oh, bch_colors, ":",  "BCH vs Ours"),
    ]

    for ax, scheme_name, scheme_fn, colors, ls, title in panels:
        # ── Our scheme line ───────────────────────────────────────────────────
        ax.plot(BLOCK_SIZES, ours,
                color="#377eb8", linewidth=3, marker="o", markersize=5, zorder=10)

        # Right-side label for our scheme — placed just past last tick
        ax.annotate("Ours (CRC-32)",
                    xy=(BLOCK_SIZES[-1], ours[-1]),
                    xytext=(8, 0), textcoords="offset points",
                    fontsize=9, fontweight="bold", color="#377eb8",
                    va="center", annotation_clip=False)

        # ── Scheme lines + right labels + crossover markers ───────────────────
        for i, ber in enumerate(BER_LEVELS):
            vals = [scheme_fn(L, ber) for L in BLOCK_SIZES]
            # Filter out None
            valid = [(L, v) for L, v in zip(BLOCK_SIZES, vals) if v is not None]
            if not valid:
                continue

            ax.plot([x[0] for x in valid], [x[1] for x in valid],
                    color=colors[i], linewidth=1.8, linestyle=ls, zorder=5)

            # Right-side label
            last_L, last_v = valid[-1]
            ax.annotate(f"{scheme_name} {ber*100:.1f}%",
                        xy=(last_L, last_v),
                        xytext=(8, 0), textcoords="offset points",
                        fontsize=8, color=colors[i],
                        va="center", annotation_clip=False)

            # Crossover marker on the our-scheme line
            L_cross = find_crossover(scheme_fn, ber)
            if L_cross is not None:
                y_cross = our_oh(L_cross)
                ax.scatter([L_cross], [y_cross],
                           marker="v", s=55, color=colors[i], zorder=11,
                           edgecolors="white", linewidths=0.5)
                # Stagger label above/below to reduce overlap
                offset = 6 if i % 2 == 0 else -12
                ax.annotate(f"{ber*100:.1f}%",
                            xy=(L_cross, y_cross),
                            xytext=(0, offset), textcoords="offset points",
                            fontsize=7, color=colors[i], ha="center",
                            annotation_clip=False)

        # ── Axes ─────────────────────────────────────────────────────────────
        ax.set_xscale("log", base=2)
        ax.set_xticks(BLOCK_SIZES)
        ax.set_xticklabels(
            [f"{L//1024}K" if L >= 1024 else str(L) for L in BLOCK_SIZES],
            rotation=35, fontsize=8)
        ax.xaxis.set_minor_locator(mticker.NullLocator())
        ax.set_xlabel("Block size (bits)", fontsize=11)
        ax.set_ylabel("Overhead (%)", fontsize=11)
        ax.set_title(title, fontsize=11)
        ax.set_ylim(0, max(ours) * 1.1)
        ax.grid(True, alpha=0.3)

        # Leave room on the right for labels
        ax.set_xlim(right=BLOCK_SIZES[-1] * 3.5)

        # Small legend explaining the crossover marker
        from matplotlib.lines import Line2D
        ax.legend(
            handles=[
                Line2D([0], [0], color="#377eb8", linewidth=2.5, label="Ours (CRC-32)"),
                Line2D([0], [0], color="gray",    linewidth=1.8, linestyle=ls,
                       label=f"{scheme_name} (BER family)"),
                plt.scatter([], [], marker="v", color="gray", s=40,
                            label="Crossover: ours becomes cheaper"),
            ],
            fontsize=8, loc="upper right",
        )

    plt.tight_layout()
    out_path = os.path.join(OUT_DIR, "fig_overhead_zones.png")
    plt.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close()
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
