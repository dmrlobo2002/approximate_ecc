"""Figure: Burst error resilience — our scheme vs Reed-Solomon vs BCH.

Panel A: Success rate vs burst flip count (empirical from results/fig4/fig4_data.csv).

Panel B: Overhead vs block size, all schemes sized to handle BOTH burst and random errors
         at 6% BER. RS t is set by the random model (harder constraint):
           t_cw solves  t = (255-2t) * P(symbol hit)  where P = 1-(1-BER)^8
         This t also trivially handles burst at the same BER.
         Our scheme crosses RS at ~7K bits, BCH at ~15K bits.
"""
from __future__ import annotations

import argparse
import csv
import math
import os

from experiments.common import compute_overhead_ratio, ensure_dir
from experiments.ecc_comparison import bch_overhead, rs_overhead


DATA_PATH = "results/fig4/fig4_data.csv"
OUT_DIR = "results/fig_burst_vs_rs"

BIT_LENGTH = 4096
HASH_BITS = 32
TARGET_BER = 0.06


def rs_t_for_random_ber(ber: float, symbol_bits: int = 8) -> int:
    """Min t per RS(255) codeword to correct `ber` random bit errors.

    Each bit error independently corrupts one symbol with probability
    P = 1-(1-ber)^symbol_bits. The expected symbol errors per (255-2t)-symbol
    codeword is (255-2t)*P. Solving t >= (255-2t)*P:
      t = ceil(255*P / (1 + 2*P))
    """
    p_sym = 1.0 - (1.0 - ber) ** symbol_bits
    return max(1, math.ceil(255 * p_sym / (1 + 2 * p_sym)))


def rs_overhead_for_both(data_bits: int, ber: float, symbol_bits: int = 8) -> float | None:
    """RS overhead to handle BOTH burst and random errors at `ber`.

    Random is the harder constraint; the resulting t also handles burst trivially
    (a burst of the same BER hits far fewer symbols than random errors do).
    """
    t = rs_t_for_random_ber(ber, symbol_bits)
    if t >= 128:
        return None
    return rs_overhead(data_bits, t, symbol_bits)["overhead_ratio"]


def bch_overhead_random(data_bits: int, ber: float) -> float:
    """BCH overhead for random errors. BCH requires interleaving for burst."""
    t_block = max(1, round(ber * 256))
    return bch_overhead(data_bits, t_block)["overhead_ratio"]


def bch_burst_limit_per_block(ber: float) -> int:
    """Max contiguous burst bits one BCH 256-bit sub-block tolerates."""
    return max(1, round(ber * 256))


def load_fig4(path: str) -> list[dict]:
    with open(path) as f:
        return [{"mode": r["mode"], "flip_count": int(r["flip_count"]),
                 "fully_corrected": int(r["fully_corrected"])}
                for r in csv.DictReader(f)]


def success_by_flip(rows: list[dict], mode: str) -> tuple[list[int], list[float], list[float]]:
    from collections import defaultdict
    buckets: dict[int, list[int]] = defaultdict(list)
    for r in rows:
        if r["mode"] == mode:
            buckets[r["flip_count"]].append(r["fully_corrected"])
    xs, ys, errs = [], [], []
    for fc in sorted(buckets):
        vals = buckets[fc]
        n = len(vals)
        rate = sum(vals) / n
        se = math.sqrt(rate * (1 - rate) / n) if n > 1 and 0 < rate < 1 else 0.0
        xs.append(fc)
        ys.append(rate * 100)
        errs.append(se * 100)
    return xs, ys, errs


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--out-dir", default=OUT_DIR)
    p.add_argument("--no-plot", action="store_true")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    ensure_dir(args.out_dir)

    rows = load_fig4(DATA_PATH)
    our_oh_4096 = compute_overhead_ratio(BIT_LENGTH, 1, 1, HASH_BITS)
    bch_limit = bch_burst_limit_per_block(TARGET_BER)
    t_rs = rs_t_for_random_ber(TARGET_BER)

    xs_rand, ys_rand, err_rand = success_by_flip(rows, "random")
    xs_burst, ys_burst, err_burst = success_by_flip(rows, "burst")

    # Panel B: overhead vs block size (all schemes sized for 6% BER, burst+random)
    block_sizes = [1024, 2048, 4096, 8192, 16384, 32768, 65536, 131072, 262144, 524288]
    ours_oh, rs_oh, bch_oh = [], [], []
    for L in block_sizes:
        ours_oh.append(compute_overhead_ratio(L, 1, 1, HASH_BITS) * 100)
        r = rs_overhead_for_both(L, TARGET_BER)
        rs_oh.append(r * 100 if r is not None else float("nan"))
        bch_oh.append(bch_overhead_random(L, TARGET_BER) * 100)

    # Crossover points: our overhead = 2*HASH_BITS/sqrt(L)
    rs_asymptote = rs_overhead_for_both(524288, TARGET_BER)
    bch_flat = bch_overhead_random(BIT_LENGTH, TARGET_BER)
    L_cross_rs = (2 * HASH_BITS / rs_asymptote) ** 2 if rs_asymptote else None
    L_cross_bch = (2 * HASH_BITS / bch_flat) ** 2

    print(f"RS t_cw for {TARGET_BER:.0%} BER random: {t_rs}")
    print(f"RS overhead (flat): ~{rs_asymptote*100:.1f}%" if rs_asymptote else "RS: no asymptote")
    print(f"BCH overhead (flat): {bch_flat*100:.1f}%  (random only, fails on burst)")
    print(f"Crossover ours vs RS:  ~{L_cross_rs:,.0f} bits" if L_cross_rs else "")
    print(f"Crossover ours vs BCH: ~{L_cross_bch:,.0f} bits")
    print()
    for L, o, r, b in zip(block_sizes, ours_oh, rs_oh, bch_oh):
        print(f"  L={L:7,}  ours={o:.1f}%  RS={r:.1f}%  BCH={b:.1f}%")

    if args.no_plot:
        return

    try:
        import matplotlib.pyplot as plt
        import matplotlib.ticker as mticker
    except ModuleNotFoundError as e:
        raise RuntimeError("matplotlib required; install it or use --no-plot") from e

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))
    fig.suptitle(
        "Burst Error Resilience: Our Scheme vs Reed-Solomon vs BCH",
        fontsize=13, fontweight="bold",
    )

    # ── Panel A ─────────────────────────────────────────────────────────────
    ax1.errorbar(xs_rand, ys_rand, yerr=err_rand, color="#377eb8", linestyle="-",
                 marker="o", linewidth=2, capsize=3, label="Ours — random errors")
    ax1.errorbar(xs_burst, ys_burst, yerr=err_burst, color="#e41a1c", linestyle="--",
                 marker="s", linewidth=2, capsize=3, label="Ours — burst errors (contiguous)")

    ax1.annotate(
        f"BCH (no interleaving):\n≤{bch_limit} burst bits per\n256-bit sub-block",
        xy=(bch_limit, 50), xytext=(bch_limit + 25, 28),
        fontsize=8.5, color="#984ea3",
        arrowprops=dict(arrowstyle="->", color="#984ea3", lw=1.2),
        bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor="#984ea3", alpha=0.9),
    )

    ax1.set_title(
        f"Success rate vs burst flip count\n(4096-bit block, {HASH_BITS}-bit CRC, {our_oh_4096:.0%} overhead)",
        fontsize=10)
    ax1.set_xlabel("Injected bit-flips")
    ax1.set_ylabel("Success rate (%)")
    ax1.set_ylim(-5, 108)
    ax1.grid(True, alpha=0.3)
    ax1.legend(fontsize=9)

    ax1_ber = ax1.secondary_xaxis("top")
    ber_ticks = xs_burst[::3]
    ax1_ber.set_xticks(ber_ticks)
    ax1_ber.set_xticklabels([f"{fc/BIT_LENGTH:.1%}" for fc in ber_ticks], fontsize=7, rotation=45)
    ax1_ber.set_xlabel("BER", fontsize=9)

    # ── Panel B ─────────────────────────────────────────────────────────────
    valid_ours = [(L, o) for L, o in zip(block_sizes, ours_oh)]
    valid_rs   = [(L, o) for L, o in zip(block_sizes, rs_oh)  if not math.isnan(o)]
    valid_bch  = [(L, o) for L, o in zip(block_sizes, bch_oh)]

    ax2.plot([x[0] for x in valid_ours], [x[1] for x in valid_ours],
             color="#377eb8", marker="o", linewidth=2.5,
             label=f"Ours (CRC-{HASH_BITS}) — burst + random")
    ax2.plot([x[0] for x in valid_rs], [x[1] for x in valid_rs],
             color="#4daf4a", marker="^", linestyle="--", linewidth=2,
             label=f"RS (GF(2⁸), t={t_rs}/codeword) — burst + random")
    ax2.plot([x[0] for x in valid_bch], [x[1] for x in valid_bch],
             color="#984ea3", marker="s", linestyle=":", linewidth=1.8,
             label="BCH — random only (fails on burst)")

    if L_cross_rs and block_sizes[0] <= L_cross_rs <= block_sizes[-1]:
        ax2.axvline(L_cross_rs, color="#4daf4a", linestyle="-.", linewidth=1.2, alpha=0.7)
        ax2.text(L_cross_rs * 1.06, (rs_asymptote or 0.8) * 100 * 1.05,
                 f"~{L_cross_rs/1000:.0f}K bits",
                 fontsize=8, color="#2a8a28",
                 bbox=dict(boxstyle="round,pad=0.2", facecolor="white", edgecolor="#4daf4a", alpha=0.85))

    if block_sizes[0] <= L_cross_bch <= block_sizes[-1]:
        ax2.axvline(L_cross_bch, color="#984ea3", linestyle="-.", linewidth=1.2, alpha=0.7)
        ax2.text(L_cross_bch * 1.06, bch_flat * 100 * 1.05,
                 f"~{L_cross_bch/1000:.0f}K bits",
                 fontsize=8, color="#6a0a80",
                 bbox=dict(boxstyle="round,pad=0.2", facecolor="white", edgecolor="#984ea3", alpha=0.85))

    ax2.set_xscale("log", base=2)
    ax2.set_xticks(block_sizes)
    ax2.set_xticklabels(
        [f"{L//1024}K" if L >= 1024 else str(L) for L in block_sizes],
        rotation=30, fontsize=8)
    ax2.xaxis.set_minor_locator(mticker.NullLocator())

    ax2.set_title(
        f"Overhead to correct {TARGET_BER:.0%} BER (burst + random) vs block size",
        fontsize=10)
    ax2.set_xlabel("Block size (bits)")
    ax2.set_ylabel("Overhead (%)")
    ax2.set_ylim(0, max(max(ours_oh), max(x[1] for x in valid_rs), max(bch_oh)) * 1.15)
    ax2.grid(True, alpha=0.3)
    ax2.legend(fontsize=9)

    plt.tight_layout()
    out_path = os.path.join(args.out_dir, "fig_burst_vs_rs.png")
    plt.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close()
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
