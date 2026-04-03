"""
Two figures comparing hash node saturation and ECC overhead
at 32x32, 64x64, and 128x128 grid sizes.

Outputs (to --out-dir):
  figure_h_saturation.png  — saturation curve + max flips per node vs BER
  figure_h_overhead.png    — overhead % grouped by hash_bits

Text output (per-BER node ranking) is printed unless --no-text is given.
"""
from __future__ import annotations

import argparse
import math
import os

import matplotlib.pyplot as plt
import numpy as np

from grid_shuffle import bits_to_grid
from group_hash import build_hash_nodes
from experiments.common import stable_key, compute_overhead_ratio


GRID_SIZES = [32, 64, 128]
COLORS = ["#1f77b4", "#ff7f0e", "#2ca02c"]
MARKERS = ["o", "s", "^"]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Figure H: hash node saturation & overhead")
    p.add_argument("--grid-sizes", type=str, default="32,64,128")
    p.add_argument("--rounds", type=int, default=8)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--key-id", type=int, default=0)
    p.add_argument("--ber-values", type=str,
                   default="0.001,0.005,0.01,0.015,0.02,0.025,0.03,0.035,0.04,0.045,0.05")
    p.add_argument("--burst-start", type=int, default=0)
    p.add_argument("--row-group-size", type=int, default=1)
    p.add_argument("--col-group-size", type=int, default=1)
    p.add_argument("--hash-bits", type=int, default=16,
                   help="Hash bits used for the saturation figure")
    p.add_argument("--hash-bits-list", type=str, default="8,16,32",
                   help="Hash bit widths for the overhead figure")
    p.add_argument("--tail-policy", default="include_partial",
                   choices=["include_partial", "pad_with_zeros", "drop_partial"])
    p.add_argument("--top-n", type=int, default=10,
                   help="Rows shown in text output per BER")
    p.add_argument("--out-dir", type=str, default="results/fig_h")
    p.add_argument("--no-text", action="store_true",
                   help="Suppress per-BER text table output")
    return p.parse_args()


def build_meta_and_nodes(n: int, args):
    bit_length = n * n
    bits = [(i * 3 + 1) % 2 for i in range(bit_length)]
    key = stable_key(args.seed, args.key_id)
    _, meta = bits_to_grid(bits, key=key, rounds=args.rounds)
    nodes = build_hash_nodes(
        grid=[[0] * meta.n for _ in range(meta.n)],
        meta=meta,
        row_group_size=args.row_group_size,
        col_group_size=args.col_group_size,
        hash_bits=args.hash_bits,
        tail_policy=args.tail_policy,
    )
    return meta, nodes


def compute_saturation_data(grid_sizes, ber_values, args):
    """Returns dict: n -> list of (ber, frac_hit, max_flips, nodes_hit, total_nodes)."""
    results = {}
    for n in grid_sizes:
        meta, nodes = build_meta_and_nodes(n, args)
        bit_length = meta.original_length
        row = []
        for ber in ber_values:
            flip_count = max(1, round(ber * bit_length))
            burst_end = min(args.burst_start + flip_count, bit_length)
            flip_set = set(range(args.burst_start, burst_end))

            ranked = []
            for node in nodes:
                n_flipped = len(node.source_indices & flip_set)
                ranked.append((node.node_id, n_flipped, len(node.source_indices), node.source_indices & flip_set))
            ranked.sort(key=lambda x: x[1], reverse=True)

            nodes_hit = sum(1 for _, nf, _, _ in ranked if nf > 0)
            max_flips = ranked[0][1] if ranked else 0
            frac_hit = nodes_hit / len(nodes)
            row.append((ber, frac_hit, max_flips, nodes_hit, len(nodes)))
        results[n] = row
    return results


# ---------------------------------------------------------------------------
# Text output (existing behaviour)
# ---------------------------------------------------------------------------

def print_text(grid_sizes, ber_values, args):
    for n in grid_sizes:
        meta, nodes = build_meta_and_nodes(n, args)
        bit_length = meta.original_length
        print(f"\n{'#'*80}")
        print(f"# Grid {n}x{n}  ({bit_length} bits)  group={args.row_group_size}x{args.col_group_size}  hash_bits={args.hash_bits}")

        for ber in ber_values:
            flip_count = max(1, round(ber * bit_length))
            burst_end = min(args.burst_start + flip_count, bit_length)
            flip_set = set(range(args.burst_start, burst_end))

            ranked = []
            for node in nodes:
                flipped = node.source_indices & flip_set
                ranked.append((node.node_id, len(flipped), len(node.source_indices), flipped))
            ranked.sort(key=lambda x: x[1], reverse=True)

            nodes_hit = sum(1 for _, nf, _, _ in ranked if nf > 0)
            print(f"\n{'='*80}")
            print(f"BER={ber:.1%}  |  Burst: [{args.burst_start}:{burst_end}]  ({flip_count} flips)")
            print(f"Group size: {args.row_group_size}x{args.col_group_size}  Hash bits: {args.hash_bits}")
            print(f"Total nodes: {len(nodes)}  |  Nodes with >=1 flip: {nodes_hit}  "
                  f"|  Ideal: flips spread across many nodes with <=1 flip each")
            print(f"\n{'Rank':<6}{'Node ID':<20}{'Flipped':<10}{'Total bits':<12}{'Flipped indices'}")
            print("-" * 80)
            for rank, (nid, nf, ntotal, fset) in enumerate(ranked[:args.top_n], 1):
                preview = str(sorted(fset)[:8])
                if len(fset) > 8:
                    preview = preview[:-1] + ", ...]"
                print(f"{rank:<6}{nid:<20}{nf:<10}{ntotal:<12}{preview}")


# ---------------------------------------------------------------------------
# Figure 4 — saturation curve + max flips per node
# ---------------------------------------------------------------------------

def plot_saturation(grid_sizes, ber_values, sat_data, args, out_dir):
    fig, (ax_top, ax_bot) = plt.subplots(2, 1, figsize=(8, 8), sharex=True)

    for i, n in enumerate(grid_sizes):
        rows = sat_data[n]
        bers = [r[0] * 100 for r in rows]
        fracs = [r[1] for r in rows]
        maxf = [r[2] for r in rows]
        total_nodes = rows[0][4]
        label = f"{n}\u00d7{n}  ({total_nodes} nodes)"

        ax_top.plot(bers, fracs, color=COLORS[i], marker=MARKERS[i],
                    markersize=5, label=label)
        ax_bot.plot(bers, maxf, color=COLORS[i], marker=MARKERS[i],
                    markersize=5, label=label)

    ax_top.axhline(1.0, color="black", linestyle="--", linewidth=1,
                   label="Full saturation")
    ax_top.set_ylabel("Fraction of nodes hit")
    ax_top.set_ylim(0, 1.08)
    ax_top.set_title(f"Saturation: fraction of hash nodes with \u22651 flipped bit\n"
                     f"(group={args.row_group_size}\u00d7{args.col_group_size}, "
                     f"hash_bits={args.hash_bits}, rounds={args.rounds})")
    ax_top.legend(fontsize=9)
    ax_top.grid(True, alpha=0.3)

    ax_bot.set_xlabel("BER (%)")
    ax_bot.set_ylabel("Max flips in any single node")
    ax_bot.set_title("Worst-case node exposure: max flips per hash node")
    ax_bot.legend(fontsize=9)
    ax_bot.grid(True, alpha=0.3)

    plt.tight_layout()
    path = os.path.join(out_dir, "figure_h_saturation.png")
    plt.savefig(path, dpi=200)
    plt.close()
    print(f"Wrote {path}")


# ---------------------------------------------------------------------------
# Figure 5 — overhead bar chart
# ---------------------------------------------------------------------------

def plot_overhead(grid_sizes, hash_bits_list, args, out_dir):
    fig, ax = plt.subplots(figsize=(8, 5))

    n_groups = len(grid_sizes)
    n_bars = len(hash_bits_list)
    width = 0.7 / n_bars
    x = np.arange(n_groups)

    bar_colors = ["#aec7e8", "#1f77b4", "#08306b"]

    for bi, hb in enumerate(hash_bits_list):
        overheads = []
        for n in grid_sizes:
            bit_length = n * n
            ratio = compute_overhead_ratio(
                bit_length=bit_length,
                row_group_size=args.row_group_size,
                col_group_size=args.col_group_size,
                hash_bits=hb,
            )
            overheads.append(ratio * 100)

        offsets = x + (bi - n_bars / 2 + 0.5) * width
        bars = ax.bar(offsets, overheads, width=width * 0.9,
                      color=bar_colors[bi], label=f"{hb}-bit hash")
        for bar, pct in zip(bars, overheads):
            ax.text(bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + 0.5,
                    f"{pct:.0f}%", ha="center", va="bottom", fontsize=9)

    ax.set_xticks(x)
    ax.set_xticklabels([f"{n}\u00d7{n}\n({n*n:,} bits)" for n in grid_sizes])
    ax.set_ylabel("ECC overhead (%)")
    ax.set_title(f"Hash overhead vs grid size  "
                 f"(group={args.row_group_size}\u00d7{args.col_group_size}, rows+cols nodes)")
    ax.legend()
    ax.grid(True, axis="y", alpha=0.3)
    ax.set_ylim(0, max(
        compute_overhead_ratio(n*n, args.row_group_size, args.col_group_size, max(hash_bits_list)) * 100
        for n in grid_sizes
    ) * 1.2)

    plt.tight_layout()
    path = os.path.join(out_dir, "figure_h_overhead.png")
    plt.savefig(path, dpi=200)
    plt.close()
    print(f"Wrote {path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    args = parse_args()
    grid_sizes = [int(x) for x in args.grid_sizes.split(",") if x.strip()]
    ber_values = [float(x) for x in args.ber_values.split(",") if x.strip()]
    hash_bits_list = [int(x) for x in args.hash_bits_list.split(",") if x.strip()]

    os.makedirs(args.out_dir, exist_ok=True)

    if not args.no_text:
        print_text(grid_sizes, ber_values, args)

    sat_data = compute_saturation_data(grid_sizes, ber_values, args)
    plot_saturation(grid_sizes, ber_values, sat_data, args, args.out_dir)
    plot_overhead(grid_sizes, hash_bits_list, args, args.out_dir)


if __name__ == "__main__":
    main()
