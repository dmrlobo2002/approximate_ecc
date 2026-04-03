"""
Heatmap: contiguous burst in physical memory -> logical grid, swept over BER values.
"""
from __future__ import annotations

import argparse
import math
import numpy as np
import matplotlib.pyplot as plt

from grid_shuffle import bits_to_grid, source_index_to_grid_coord
from experiments.common import stable_key


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Burst flip dispersion heatmap ? BER sweep")
    p.add_argument("--bit-length", type=int, default=256)
    p.add_argument("--rounds", type=int, default=8)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--key-id", type=int, default=0, help="Which key to use")
    p.add_argument("--ber-values", type=str, default="0.001,0.01,0.015,0.02,0.025,0.03,0.035,0.04,0.045,0.05",
                   help="Comma-separated BER values to sweep")
    p.add_argument("--burst-start", type=int, default=0)
    p.add_argument("--out", type=str, default="burst_ber_sweep.png")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    ber_values = [float(x) for x in args.ber_values.split(",") if x.strip()]
    bits = [(i * 3 + 1) % 2 for i in range(args.bit_length)]
    key = stable_key(args.seed, args.key_id)
    _, meta = bits_to_grid(bits, key=key, rounds=args.rounds)
    n = meta.n

    ncols = min(len(ber_values), 4)
    nrows = math.ceil(len(ber_values) / ncols)
    fig, axes = plt.subplots(nrows, ncols, figsize=(4 * ncols, 4 * nrows))
    axes = np.array(axes).reshape(-1)

    for i, ber in enumerate(ber_values):
        flip_count = max(1, round(ber * args.bit_length))
        burst_end = min(args.burst_start + flip_count, args.bit_length)
        flip_indices = list(range(args.burst_start, burst_end))

        flip_map = np.zeros((n, n), dtype=float)
        for src_idx in flip_indices:
            r, c = source_index_to_grid_coord(src_idx, meta)
            flip_map[r, c] += 1

        ax = axes[i]
        im = ax.imshow(flip_map, cmap="hot", interpolation="nearest",
                       vmin=0, vmax=max(1, flip_map.max()))
        ax.set_title(f"BER={ber:.1%}  ({len(flip_indices)} flips)")
        ax.set_xlabel("Grid col")
        ax.set_ylabel("Grid row")
        plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)

    for ax in axes[len(ber_values):]:
        ax.set_visible(False)

    fig.suptitle(
        f"Burst dispersion BER sweep: burst start={args.burst_start}, "
        f"{n}×{n} grid, rounds={args.rounds}",
        fontsize=11,
    )
    plt.tight_layout()
    plt.savefig(args.out, dpi=200)
    plt.close()
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()