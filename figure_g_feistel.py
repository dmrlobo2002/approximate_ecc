"""
Three figures comparing Feistel shuffle quality and burst dispersion
at 32x32, 64x64, and 128x128 grid sizes.

Outputs (to --out-dir):
  figure_g_shuffle.png  — source-position heatmap (shuffle quality)
  figure_g_burst.png    — burst dispersion at several BER values
  figure_g_rowcol.png   — flips-per-row and flips-per-col at --ref-ber
"""
from __future__ import annotations

import argparse
import math
import os

import numpy as np
import matplotlib.pyplot as plt

from grid_shuffle import bits_to_grid, source_index_to_grid_coord
from experiments.common import stable_key


GRID_SIZES = [32, 64, 128]
GRID_TO_BITS = {n: n * n for n in GRID_SIZES}
COLORS = ["#1f77b4", "#ff7f0e", "#2ca02c"]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Figure G: Feistel shuffle & burst dispersion")
    p.add_argument("--grid-sizes", type=str, default="32,64,128",
                   help="Grid side-lengths to compare (default: 32,64,128)")
    p.add_argument("--rounds", type=int, default=8)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--key-id", type=int, default=0)
    p.add_argument("--burst-ber", type=str, default="0.01,0.02,0.03,0.05",
                   help="BER values for the burst dispersion figure")
    p.add_argument("--ref-ber", type=float, default=0.02,
                   help="BER used for the flips-per-row/col figure")
    p.add_argument("--burst-start", type=int, default=0)
    p.add_argument("--out-dir", type=str, default="results/fig_g")
    return p.parse_args()


def build_meta(n: int, seed: int, key_id: int, rounds: int):
    bit_length = n * n
    bits = [(i * 3 + 1) % 2 for i in range(bit_length)]
    key = stable_key(seed, key_id)
    _, meta = bits_to_grid(bits, key=key, rounds=rounds)
    return meta


# ---------------------------------------------------------------------------
# Figure 1 — shuffle quality
# ---------------------------------------------------------------------------

def plot_shuffle(grid_sizes, args, out_dir):
    ncols = len(grid_sizes)
    fig, axes = plt.subplots(1, ncols, figsize=(5 * ncols, 5))
    if ncols == 1:
        axes = [axes]

    for ax, n in zip(axes, grid_sizes):
        meta = build_meta(n, args.seed, args.key_id, args.rounds)
        bit_length = meta.original_length
        color_map = np.full((n, n), np.nan)
        for src_idx in range(bit_length):
            r, c = source_index_to_grid_coord(src_idx, meta)
            color_map[r, c] = src_idx / (bit_length - 1)

        im = ax.imshow(color_map, cmap="plasma", interpolation="nearest",
                       vmin=0, vmax=1)
        ax.set_title(f"{n}\u00d7{n} grid ({bit_length:,} bits)")
        ax.set_xlabel("Grid col")
        ax.set_ylabel("Grid row")
        plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04,
                     label="Source position (normalized)")

    fig.suptitle(
        f"Feistel shuffle: source bit position mapped onto grid  "
        f"(rounds={args.rounds})",
        fontsize=12,
    )
    plt.tight_layout()
    path = os.path.join(out_dir, "figure_g_shuffle.png")
    plt.savefig(path, dpi=200)
    plt.close()
    print(f"Wrote {path}")


# ---------------------------------------------------------------------------
# Figure 2 — burst dispersion BER sweep
# ---------------------------------------------------------------------------

def plot_burst(grid_sizes, ber_values, args, out_dir):
    nrows = len(grid_sizes)
    ncols = len(ber_values)
    fig, axes = plt.subplots(nrows, ncols, figsize=(4 * ncols, 4 * nrows))
    axes = np.array(axes).reshape(nrows, ncols)

    for row_i, n in enumerate(grid_sizes):
        meta = build_meta(n, args.seed, args.key_id, args.rounds)
        bit_length = meta.original_length
        for col_i, ber in enumerate(ber_values):
            flip_count = max(1, round(ber * bit_length))
            burst_end = min(args.burst_start + flip_count, bit_length)
            flip_indices = list(range(args.burst_start, burst_end))

            flip_map = np.zeros((n, n), dtype=float)
            for src_idx in flip_indices:
                r, c = source_index_to_grid_coord(src_idx, meta)
                flip_map[r, c] += 1

            ax = axes[row_i, col_i]
            im = ax.imshow(flip_map, cmap="hot", interpolation="nearest",
                           vmin=0, vmax=max(1, flip_map.max()))
            ax.set_title(f"{n}\u00d7{n}  BER={ber:.1%}  ({len(flip_indices)} flips)")
            ax.set_xlabel("Grid col")
            ax.set_ylabel("Grid row")
            plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)

    fig.suptitle(
        f"Burst dispersion: contiguous burst \u2192 grid  "
        f"(burst start={args.burst_start}, rounds={args.rounds})",
        fontsize=12,
    )
    plt.tight_layout()
    path = os.path.join(out_dir, "figure_g_burst.png")
    plt.savefig(path, dpi=200)
    plt.close()
    print(f"Wrote {path}")


# ---------------------------------------------------------------------------
# Figure 3 — flips per row / col
# ---------------------------------------------------------------------------

def plot_rowcol(grid_sizes, ref_ber, args, out_dir):
    nrows = len(grid_sizes)
    fig, axes = plt.subplots(nrows, 2, figsize=(12, 4 * nrows))
    axes = np.array(axes).reshape(nrows, 2)

    for row_i, n in enumerate(grid_sizes):
        meta = build_meta(n, args.seed, args.key_id, args.rounds)
        bit_length = meta.original_length
        flip_count = max(1, round(ref_ber * bit_length))
        burst_end = min(args.burst_start + flip_count, bit_length)
        flip_indices = list(range(args.burst_start, burst_end))

        row_counts = np.zeros(n, dtype=int)
        col_counts = np.zeros(n, dtype=int)
        for src_idx in flip_indices:
            r, c = source_index_to_grid_coord(src_idx, meta)
            row_counts[r] += 1
            col_counts[c] += 1

        expected = len(flip_indices) / n

        for col_i, (counts, label) in enumerate([
            (row_counts, "Row index"),
            (col_counts, "Col index"),
        ]):
            ax = axes[row_i, col_i]
            ax.barh(range(n), counts, color=COLORS[row_i], alpha=0.75)
            ax.axvline(expected, color="black", linestyle="--", linewidth=1,
                       label=f"Uniform ({expected:.1f})")
            ax.set_xlabel("Flip count")
            ax.set_ylabel(label)
            kind = "row" if col_i == 0 else "col"
            ax.set_title(f"{n}\u00d7{n}: flips per {kind}  (BER={ref_ber:.1%}, {len(flip_indices)} flips)")
            ax.legend(fontsize=8)

    fig.suptitle(
        f"Flips per row and column after Feistel shuffle  "
        f"(burst start={args.burst_start}, rounds={args.rounds})",
        fontsize=12,
    )
    plt.tight_layout()
    path = os.path.join(out_dir, "figure_g_rowcol.png")
    plt.savefig(path, dpi=200)
    plt.close()
    print(f"Wrote {path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    args = parse_args()
    grid_sizes = [int(x) for x in args.grid_sizes.split(",") if x.strip()]
    ber_values = [float(x) for x in args.burst_ber.split(",") if x.strip()]

    os.makedirs(args.out_dir, exist_ok=True)

    plot_shuffle(grid_sizes, args, args.out_dir)
    plot_burst(grid_sizes, ber_values, args, args.out_dir)
    plot_rowcol(grid_sizes, args.ref_ber, args, args.out_dir)


if __name__ == "__main__":
    main()
