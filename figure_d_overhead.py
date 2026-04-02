"""Figure D: ECC overhead ratio vs. correction threshold (BER at 90% success).

Plots our scheme (various configs) alongside analytic Hamming, BCH, and LDPC
reference points on a (overhead_ratio, correction_threshold_BER) scatter plot.

The correction threshold is read from Figure C's CSV (results/fig_c/figure_c_ber.csv).
If that file does not exist, only the reference codes are plotted.
"""
from __future__ import annotations

import argparse
import math
import os
from typing import Any

from experiments.common import compute_overhead_ratio, ensure_dir, write_csv, write_json
from experiments.ecc_comparison import bch_overhead, hamming_overhead, ldpc_overhead


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Figure D: Overhead vs. correction capability")
    p.add_argument("--bit-length", type=int, default=256)
    p.add_argument("--fig-c-csv", type=str, default="results/fig_c/figure_c_ber.csv",
                   help="Path to Figure C CSV to extract correction thresholds")
    p.add_argument("--threshold", type=float, default=0.90,
                   help="Success rate threshold defining 'correction threshold BER'")
    p.add_argument("--out-dir", type=str, default="results/fig_d")
    p.add_argument("--no-plot", action="store_true")
    return p.parse_args()


def load_fig_c(csv_path: str) -> list[dict]:
    import csv
    if not os.path.exists(csv_path):
        return []
    with open(csv_path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def correction_threshold_ber(fig_c_rows: list[dict], hash_bits: int, cfg_label: str, threshold: float) -> float | None:
    """Largest BER where success_rate >= threshold, for the given config."""
    subset = sorted(
        [r for r in fig_c_rows if int(r["hash_bits"]) == hash_bits and r["group_config"] == cfg_label],
        key=lambda r: float(r["ber_actual"]),
    )
    best = None
    for r in subset:
        if float(r["success_rate"]) >= threshold:
            best = float(r["ber_actual"])
    return best


def main() -> None:
    args = parse_args()
    ensure_dir(args.out_dir)
    fig_c_rows = load_fig_c(args.fig_c_csv)

    GROUP_CONFIGS = [
        (1, 1, "g=1"),
        (2, 2, "g=2"),
        (4, 4, "g=4"),
    ]

    # --- Our scheme data points ---
    our_points: list[dict[str, Any]] = []
    for hash_bits in [16, 32]:
        for row_gs, col_gs, cfg_label in GROUP_CONFIGS:
            overhead = compute_overhead_ratio(args.bit_length, row_gs, col_gs, hash_bits)
            threshold_ber = correction_threshold_ber(fig_c_rows, hash_bits, cfg_label, args.threshold)
            our_points.append({
                "scheme": f"Ours ({cfg_label}, {hash_bits}b)",
                "hash_bits": hash_bits,
                "group_config": cfg_label,
                "overhead_ratio": round(overhead, 4),
                "correction_threshold_ber": round(threshold_ber, 5) if threshold_ber else None,
                "data_bits": args.bit_length,
            })

    # --- Classical ECC reference points ---
    ref_points: list[dict[str, Any]] = []

    h = hamming_overhead(args.bit_length)
    ref_points.append({
        "scheme": h["scheme"],
        "overhead_ratio": round(h["overhead_ratio"], 4),
        "correction_threshold_ber": round(h["correctable_bits"] / args.bit_length, 5),
        "correctable_bits": h["correctable_bits"],
        "source": "analytic",
    })

    for t in [2, 4, 8, 16, 32, 64, 128, 256, 512, 1024]:
        b = bch_overhead(args.bit_length, t)
        ref_points.append({
            "scheme": b["scheme"],
            "overhead_ratio": round(b["overhead_ratio"], 4),
            "correction_threshold_ber": round(b["correctable_bits"] / b["data_bits"], 5),
            "correctable_bits": b["correctable_bits"],
            "source": "analytic",
        })

    for rate in [0.75, 0.5]:
        ld = ldpc_overhead(args.bit_length, rate)
        ref_points.append({
            "scheme": ld["scheme"],
            "overhead_ratio": round(ld["overhead_ratio"], 4),
            "correction_threshold_ber": None,  # channel-dependent
            "correctable_bits": None,
            "source": "analytic",
        })

    write_json(os.path.join(args.out_dir, "config.json"), {
        "bit_length": args.bit_length,
        "threshold": args.threshold,
        "fig_c_csv": args.fig_c_csv,
    })
    write_csv(
        os.path.join(args.out_dir, "figure_d_ours.csv"),
        our_points,
        fieldnames=["scheme", "hash_bits", "group_config", "overhead_ratio",
                    "correction_threshold_ber", "data_bits"],
    )
    write_csv(
        os.path.join(args.out_dir, "figure_d_reference.csv"),
        ref_points,
        fieldnames=["scheme", "overhead_ratio", "correction_threshold_ber",
                    "correctable_bits", "source"],
    )
    print("Reference ECC points:")
    for r in ref_points:
        print(f"  {r['scheme']:30s}  overhead={r['overhead_ratio']:.4f}  "
              f"threshold_BER={r['correction_threshold_ber']}")
    print("Our scheme points:")
    for r in our_points:
        thr = r["correction_threshold_ber"]
        print(f"  {r['scheme']:30s}  overhead={r['overhead_ratio']:.4f}  "
              f"threshold_BER={thr if thr else '(run fig_c first)'}")

    if args.no_plot:
        return

    try:
        import matplotlib.pyplot as plt
    except ModuleNotFoundError as e:
        raise RuntimeError("matplotlib required for plotting; use --no-plot to skip") from e

    fig, ax = plt.subplots(figsize=(9, 6))

    # Reference codes
    ref_markers = {"Hamming": "D", "BCH": "s", "LDPC": "^"}
    ref_colors = {"Hamming": "#d62728", "BCH": "#9467bd", "LDPC": "#8c564b"}
    for r in ref_points:
        if r["correction_threshold_ber"] is None:
            continue
        label_prefix = r["scheme"].split("(")[0].strip()
        ax.scatter(
            r["overhead_ratio"],
            r["correction_threshold_ber"],
            marker=ref_markers.get(label_prefix, "x"),
            color=ref_colors.get(label_prefix, "gray"),
            s=80, zorder=5,
            label=r["scheme"],
        )

    # Our scheme
    config_markers = {"g=1": "o", "g=2": "o", "g=4": "o"}
    config_colors_16 = "#1f77b4"
    config_colors_32 = "#ff7f0e"
    for r in our_points:
        if r["correction_threshold_ber"] is None:
            continue
        color = config_colors_16 if r["hash_bits"] == 16 else config_colors_32
        ax.scatter(
            r["overhead_ratio"],
            r["correction_threshold_ber"],
            marker="o",
            color=color,
            s=100, zorder=6,
            label=r["scheme"],
        )

    ax.set_xlabel("ECC overhead ratio (parity bits / data bits)")
    ax.set_ylabel(f"Correction threshold BER (success ≥ {args.threshold:.0%})")
    ax.set_title(f"Overhead vs. Correction Capability — {args.bit_length}-bit data word")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:.0%}" if x >= 0.01 else f"{x:.2%}"))
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f"{y:.1%}" if y >= 0.001 else f"{y:.3%}"))
    ax.grid(True, alpha=0.3, which="both")
    ax.legend(fontsize=8, loc="upper left")
    plt.tight_layout()
    out_png = os.path.join(args.out_dir, "figure_d_overhead.png")
    plt.savefig(out_png, dpi=200)
    plt.close()
    print(f"Wrote plot: {out_png}")


if __name__ == "__main__":
    main()
