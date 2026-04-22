"""Re-plot fig2 from existing CSVs, 2-panel version (no decoder complexity panel).

Reads results/fig2/ CSVs — no new trials needed.
"""
from __future__ import annotations

import argparse
import csv
import os

from experiments.common import ensure_dir


IN_DIR = "results/fig2"
OUT_DIR = "results/fig2"


def read_csv(path: str) -> list[dict]:
    with open(path) as f:
        return list(csv.DictReader(f))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--in-dir", default=IN_DIR)
    p.add_argument("--out-dir", default=OUT_DIR)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    ensure_dir(args.out_dir)

    bch_rows = read_csv(os.path.join(args.in_dir, "fig2_bch.csv"))
    bch_honest_rows = read_csv(os.path.join(args.in_dir, "fig2_bch_honest.csv"))
    our_ops = read_csv(os.path.join(args.in_dir, "fig2_operating_points.csv"))

    # Cast numeric fields
    for r in bch_rows:
        r["correctable_bits"] = int(r["correctable_bits"])
        r["overhead_pct"] = float(r["overhead_pct"])
        r["t"] = int(r["t"])
    for r in bch_honest_rows:
        r["correctable_bits"] = int(r["correctable_bits"])
        r["overhead_pct"] = float(r["overhead_pct"])
    for r in our_ops:
        r["max_correctable"] = int(r["max_correctable"])
        r["overhead_pct"] = float(r["overhead_pct"])

    try:
        import matplotlib.pyplot as plt
        import matplotlib.ticker as ticker
    except ModuleNotFoundError as e:
        raise RuntimeError("matplotlib required") from e

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 7))
    fig.suptitle(
        "Overhead vs Correction Capability: Our Scheme vs BCH  (block size = 4096 bits)",
        fontsize=13, fontweight="bold",
    )

    marker_styles = ["o", "^", "D", "v"]
    colors = ["#377eb8", "#4daf4a", "#984ea3", "#ff7f00"]

    # ── Panel A: overhead % vs correctable errors ──────────────────────────
    bch_xs = [r["correctable_bits"] for r in bch_rows]
    bch_ys = [r["overhead_pct"] for r in bch_rows]
    ax1.plot(bch_xs, bch_ys, "s--", color="#d62728", linewidth=2, markersize=7,
             label="BCH (theoretical upper bound)")

    bch_honest_xs = [r["correctable_bits"] for r in bch_honest_rows]
    bch_honest_ys = [r["overhead_pct"] for r in bch_honest_rows]
    ax1.plot(bch_honest_xs, bch_honest_ys, "^-", color="#4a1486", linewidth=2, markersize=7,
             label="BCH (honest t for 95% success under random errors)")

    for i, op in enumerate(our_ops):
        if op["max_correctable"] == 0:
            continue
        label_clean = op["label"].replace("\n", ", ")
        ax1.scatter([op["max_correctable"]], [op["overhead_pct"]],
                    s=140, marker=marker_styles[i], color=colors[i], zorder=5,
                    label=f"Ours: {label_clean}  ({op['overhead_pct']:.0f}% overhead)")

    ax1.set_xlabel("Correctable bit-flips (at ≥95% success rate)")
    ax1.set_ylabel("Overhead (%)")
    ax1.set_title("Overhead vs correction capability")
    ax1.grid(True, alpha=0.3)
    ax1.legend(fontsize=9)
    ax1.yaxis.set_major_formatter(ticker.PercentFormatter())

    # ── Panel B: correction efficiency ─────────────────────────────────────
    bch_eff_xs = [r["correctable_bits"] for r in bch_rows]
    bch_eff_ys = [r["correctable_bits"] / r["overhead_pct"] for r in bch_rows]
    ax2.plot(bch_eff_xs, bch_eff_ys, "s--", color="#d62728", linewidth=2, markersize=7,
             label="BCH (theoretical upper bound)")

    bch_honest_eff_ys = [r["correctable_bits"] / r["overhead_pct"] if r["overhead_pct"] > 0 else 0
                         for r in bch_honest_rows]
    ax2.plot(bch_honest_xs, bch_honest_eff_ys, "^-", color="#4a1486", linewidth=2, markersize=7,
             label="BCH (honest t, 95% success)")

    for i, op in enumerate(our_ops):
        if op["max_correctable"] == 0 or op["overhead_pct"] == 0:
            continue
        eff = op["max_correctable"] / op["overhead_pct"]
        label_clean = op["label"].replace("\n", ", ")
        ax2.scatter([op["max_correctable"]], [eff],
                    s=140, marker=marker_styles[i], color=colors[i], zorder=5,
                    label=f"Ours: {label_clean}")

    ax2.set_xlabel("Correctable bit-flips")
    ax2.set_ylabel("Flips corrected per 1% overhead")
    ax2.set_title("Correction efficiency (higher is better)")
    ax2.grid(True, alpha=0.3)
    ax2.legend(fontsize=9)

    plt.tight_layout()
    out_path = os.path.join(args.out_dir, "fig2_overhead_comparison.png")
    plt.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close()
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
