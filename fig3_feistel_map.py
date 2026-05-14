"""Figure 3: Feistel shuffle effectiveness — 2D burst scatter maps.

For a contiguous burst of bits at position 0 in physical memory (source indices),
shows where those bits land in the N×N grid after the Feistel permutation.
White pixels = flipped positions; black = unflipped.

Layout: rows = block sizes, cols = BER levels (controls burst length).
"""
from __future__ import annotations

import argparse
import math
import os

from experiments.common import ensure_dir, stable_key
from grid_shuffle import bits_to_grid, source_index_to_grid_coord

DEFAULT_BIT_LENGTHS = [256, 1024, 4096]
DEFAULT_BER_VALUES = [0.01, 0.03, 0.05]
DEFAULT_ROUNDS = 8
DEFAULT_SEED = 42


def parse_float_list(spec: str) -> list[float]:
    return [float(x.strip()) for x in spec.split(",") if x.strip()]


def parse_int_list(spec: str) -> list[int]:
    return [int(x.strip()) for x in spec.split(",") if x.strip()]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Figure 3: Feistel shuffle 2D burst maps")
    p.add_argument("--bit-lengths", type=str, default=",".join(str(x) for x in DEFAULT_BIT_LENGTHS))
    p.add_argument("--ber-values", type=str, default=",".join(str(x) for x in DEFAULT_BER_VALUES))
    p.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS)
    p.add_argument("--seed", type=int, default=DEFAULT_SEED)
    p.add_argument("--out-dir", type=str, default="results/fig3")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    bit_lengths = parse_int_list(args.bit_lengths)
    ber_values = parse_float_list(args.ber_values)

    ensure_dir(args.out_dir)

    try:
        import matplotlib.pyplot as plt
        import matplotlib.colors as mcolors
    except ModuleNotFoundError as e:
        raise RuntimeError("matplotlib required for fig3_feistel_map.py") from e

    n_rows = len(bit_lengths)
    n_cols = len(ber_values)
    fig, axes = plt.subplots(n_rows, n_cols, figsize=(4 * n_cols, 4 * n_rows))
    fig.suptitle(
        "Feistel shuffle: burst error positions in physical memory → N×N grid\n"
        "(white = flipped, black = intact; burst starts at source index 0)",
        fontsize=12, fontweight="bold",
    )

    # Ensure axes is always 2D
    if n_rows == 1 and n_cols == 1:
        axes = [[axes]]
    elif n_rows == 1:
        axes = [axes]
    elif n_cols == 1:
        axes = [[ax] for ax in axes]

    for row_idx, bit_length in enumerate(bit_lengths):
        n = math.ceil(math.sqrt(bit_length))
        key = stable_key(args.seed, 0)
        bits = [0] * bit_length
        _, meta = bits_to_grid(bits, key=key, rounds=args.rounds)

        for col_idx, ber in enumerate(ber_values):
            burst_size = max(1, round(ber * bit_length))
            ax = axes[row_idx][col_idx]

            # Build n×n binary map: 1 = burst bit, 0 = intact
            grid_map = [[0.0] * n for _ in range(n)]
            for src_idx in range(burst_size):
                r, c = source_index_to_grid_coord(src_idx, meta)
                grid_map[r][c] = 1.0

            ax.imshow(grid_map, cmap="gray", vmin=0, vmax=1,
                      interpolation="nearest", origin="upper", aspect="equal")
            ax.set_title(
                f"L={bit_length}  BER={ber:.0%}  ({burst_size} bits)",
                fontsize=9,
            )
            ax.axis("off")

    plt.tight_layout()
    out_path = os.path.join(args.out_dir, "fig3_feistel_map.png")
    plt.savefig(out_path, dpi=200)
    plt.close()
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
