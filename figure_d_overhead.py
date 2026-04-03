"""Figure D: ECC overhead ratio vs. correction threshold (BER at 90% success).

Plots our scheme at 32x32, 64x64, and 128x128 grid sizes alongside analytic
BCH and Hamming reference points on a (overhead_ratio, correction_threshold_BER)
scatter plot.

The correction threshold for our scheme is read from Figure C's CSV
(results/fig_c/figure_c_ber.csv). If that file does not exist, only the
reference codes are plotted.
"""
from __future__ import annotations

import argparse
import csv
import math
import os
from typing import Any

from experiments.common import compute_overhead_ratio, ensure_dir, write_csv, write_json
from experiments.ecc_comparison import bch_overhead, hamming_overhead


COLORS = ["#1f77b4", "#ff7f0e", "#2ca02c"]
MARKERS = ["o", "s", "^"]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Figure D: Overhead vs. correction capability")
    p.add_argument("--grid-sizes", type=str, default="32,64,128",
                   help="Grid side-lengths to plot (bit-length = n*n)")
    p.add_argument("--hash-bits", type=int, choices=[8, 16, 32], default=16)
    p.add_argument("--fig-c-csv", type=str, default="results/fig_c/figure_c_ber.csv",
                   help="Path to Figure C CSV to extract correction thresholds")
    p.add_argument("--threshold", type=float, default=0.90,
                   help="Success rate threshold defining 'correction threshold BER'")
    p.add_argument("--out-dir", type=str, default="results/fig_d")
    p.add_argument("--no-plot", action="store_true")
    return p.parse_args()


def load_fig_c(csv_path: str) -> list[dict]:
    if not os.path.exists(csv_path):
        return []
    with open(csv_path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def correction_threshold_ber(fig_c_rows: list[dict], grid_size: int, hash_bits: int, threshold: float) -> float | None:
    """Largest BER where success_rate >= threshold for this grid_size + hash_bits."""
    if not fig_c_rows or "grid_size" not in fig_c_rows[0]:
        return None  # Old CSV format without grid_size column
    subset = sorted(
        [
            r for r in fig_c_rows
            if int(r["grid_size"]) == grid_size and int(r["hash_bits"]) == hash_bits
        ],
        key=lambda r: float(r["ber_actual"]),
    )
    best = None
    for r in subset:
        if float(r["success_rate"]) >= threshold:
            best = float(r["ber_actual"])
    return best


def main() -> None:
    args = parse_args()
    grid_sizes = [int(x) for x in args.grid_sizes.split(",") if x.strip()]
    ensure_dir(args.out_dir)
    fig_c_rows = load_fig_c(args.fig_c_csv)

    if not fig_c_rows:
        print(f"Note: {args.fig_c_csv} not found — our scheme points will be omitted. Run figure_c first.")

    # --- Our scheme data points (one per grid size) ---
    our_points: list[dict[str, Any]] = []
    for n in grid_sizes:
        bit_length = n * n
        overhead = compute_overhead_ratio(bit_length, row_group_size=1, col_group_size=1, hash_bits=args.hash_bits)
        thr = correction_threshold_ber(fig_c_rows, n, args.hash_bits, args.threshold)
        our_points.append({
            "grid_size": n,
            "bit_length": bit_length,
            "scheme": f"Ours {n}\u00d7{n} ({args.hash_bits}b)",
            "hash_bits": args.hash_bits,
            "overhead_ratio": round(overhead, 4),
            "correction_threshold_ber": round(thr, 5) if thr is not None else None,
        })

    # --- BCH reference curve: sweep t at each grid size ---
    # Use the largest grid size as the representative block length for BCH,
    # since BCH scales with block length. Also add a curve for each grid size.
    ref_points: list[dict[str, Any]] = []
    t_values = [1, 2, 4, 8, 16, 32, 64, 128, 256, 512]
    for n in grid_sizes:
        bit_length = n * n
        for t in t_values:
            b = bch_overhead(bit_length, t)
            if b["correctable_bits"] > bit_length:
                continue
            ref_points.append({
                "scheme": f"BCH {n}\u00d7{n} t={t}",
                "grid_size": n,
                "overhead_ratio": round(b["overhead_ratio"], 4),
                "correction_threshold_ber": round(b["correctable_bits"] / b["data_bits"], 6),
                "correctable_bits": b["correctable_bits"],
                "source": "analytic",
            })

    # Hamming (single-error-correction) at each grid size
    hamming_points: list[dict[str, Any]] = []
    for n in grid_sizes:
        bit_length = n * n
        h = hamming_overhead(bit_length)
        hamming_points.append({
            "scheme": f"Hamming {n}\u00d7{n}",
            "grid_size": n,
            "overhead_ratio": round(h["overhead_ratio"], 4),
            "correction_threshold_ber": round(h["correctable_bits"] / bit_length, 6),
            "correctable_bits": h["correctable_bits"],
            "source": "analytic",
        })

    write_json(os.path.join(args.out_dir, "config.json"), {
        "grid_sizes": grid_sizes,
        "hash_bits": args.hash_bits,
        "threshold": args.threshold,
        "fig_c_csv": args.fig_c_csv,
    })
    write_csv(
        os.path.join(args.out_dir, "figure_d_ours.csv"),
        our_points,
        fieldnames=["grid_size", "bit_length", "scheme", "hash_bits",
                    "overhead_ratio", "correction_threshold_ber"],
    )
    write_csv(
        os.path.join(args.out_dir, "figure_d_reference.csv"),
        ref_points + hamming_points,
        fieldnames=["scheme", "grid_size", "overhead_ratio", "correction_threshold_ber",
                    "correctable_bits", "source"],
    )

    print("\nOur scheme:")
    for r in our_points:
        thr = r["correction_threshold_ber"]
        print(f"  {r['scheme']:30s}  overhead={r['overhead_ratio']:.1%}  "
              f"threshold_BER={f'{thr:.3%}' if thr is not None else '(run fig_c first)'}")

    if args.no_plot:
        return

    try:
        import matplotlib.pyplot as plt
    except ModuleNotFoundError as e:
        raise RuntimeError("matplotlib required; use --no-plot to skip") from e

    fig, ax = plt.subplots(figsize=(10, 7))

    # BCH reference curves — one per grid size, light/dashed
    bch_colors = ["#aec7e8", "#ffbb78", "#98df8a"]
    for gi, n in enumerate(grid_sizes):
        pts = sorted(
            [r for r in ref_points if r["grid_size"] == n],
            key=lambda r: r["overhead_ratio"],
        )
        if pts:
            xs = [r["overhead_ratio"] for r in pts]
            ys = [r["correction_threshold_ber"] for r in pts]
            ax.plot(xs, ys, color=bch_colors[gi], linewidth=1.5, linestyle="--",
                    label=f"BCH {n}\u00d7{n} (analytic)")

    # Hamming reference points
    hamming_colors = ["#d62728", "#d62728", "#d62728"]
    for gi, r in enumerate(hamming_points):
        ax.scatter(r["overhead_ratio"], r["correction_threshold_ber"],
                   marker="D", color="#d62728", s=70, zorder=5,
                   label=r["scheme"] if gi == 0 else "_nolegend_")

    # Our scheme points — one per grid size
    for gi, r in enumerate(our_points):
        if r["correction_threshold_ber"] is None:
            continue
        ax.scatter(
            r["overhead_ratio"],
            r["correction_threshold_ber"],
            marker=MARKERS[gi],
            color=COLORS[gi],
            s=150, zorder=6, linewidths=1.5,
            label=r["scheme"],
        )
        ax.annotate(
            f"  {r['grid_size']}\u00d7{r['grid_size']}\n  {r['overhead_ratio']:.0%} overhead",
            xy=(r["overhead_ratio"], r["correction_threshold_ber"]),
            fontsize=8, color=COLORS[gi],
        )

    ax.set_xlabel("ECC overhead ratio (parity bits / data bits)", fontsize=11)
    ax.set_ylabel(f"Correction threshold BER (success \u2265 {args.threshold:.0%})", fontsize=11)
    ax.set_title(
        f"Overhead vs. Correction Capability\n"
        f"Our scheme (group=1, {args.hash_bits}-bit hash) vs. BCH at each grid size",
        fontsize=12,
    )
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.xaxis.set_major_formatter(plt.FuncFormatter(
        lambda x, _: f"{x:.0%}" if x >= 0.01 else f"{x:.2%}"
    ))
    ax.yaxis.set_major_formatter(plt.FuncFormatter(
        lambda y, _: f"{y:.1%}" if y >= 0.001 else f"{y:.3%}"
    ))
    ax.grid(True, alpha=0.3, which="both")
    ax.legend(fontsize=9, loc="upper left")
    plt.tight_layout()

    out_png = os.path.join(args.out_dir, "figure_d_overhead.png")
    plt.savefig(out_png, dpi=200)
    plt.close()
    print(f"\nWrote plot: {out_png}")


if __name__ == "__main__":
    main()
