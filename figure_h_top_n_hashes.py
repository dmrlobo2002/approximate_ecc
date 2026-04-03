"""
For a given burst, rank hash nodes by how many of their input bits were flipped,
swept over multiple BER values.
"""
from __future__ import annotations

import argparse

from grid_shuffle import bits_to_grid, source_index_to_grid_coord
from group_hash import build_hash_nodes
from experiments.common import stable_key


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Top-N hash nodes by flipped input bits ? BER sweep")
    p.add_argument("--bit-length", type=int, default=256)
    p.add_argument("--rounds", type=int, default=8)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--key-id", type=int, default=0)
    p.add_argument("--ber-values", type=str,
                   default="0.001,0.01,0.015,0.02,0.025,0.03,0.035,0.04,0.045,0.05")
    p.add_argument("--burst-start", type=int, default=0)
    p.add_argument("--row-group-size", type=int, default=1)
    p.add_argument("--col-group-size", type=int, default=1)
    p.add_argument("--hash-bits", type=int, default=16)
    p.add_argument("--tail-policy", default="include_partial",
                   choices=["include_partial", "pad_with_zeros", "drop_partial"])
    p.add_argument("--top-n", type=int, default=10)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    ber_values = [float(x) for x in args.ber_values.split(",") if x.strip()]
    bits = [(i * 3 + 1) % 2 for i in range(args.bit_length)]

    key = stable_key(args.seed, args.key_id)
    _, meta = bits_to_grid(bits, key=key, rounds=args.rounds)

    # Build nodes once ? structure doesn't change across BER values
    nodes = build_hash_nodes(
        grid=[[0] * meta.n for _ in range(meta.n)],
        meta=meta,
        row_group_size=args.row_group_size,
        col_group_size=args.col_group_size,
        hash_bits=args.hash_bits,
        tail_policy=args.tail_policy,
    )

    for ber in ber_values:
        flip_count = max(1, round(ber * args.bit_length))
        burst_end = min(args.burst_start + flip_count, args.bit_length)
        flip_indices = set(range(args.burst_start, burst_end))

        ranked = []
        for node in nodes:
            flipped_in_node = node.source_indices & flip_indices
            ranked.append((node.node_id, len(flipped_in_node), len(node.source_indices), flipped_in_node))
        ranked.sort(key=lambda x: x[1], reverse=True)

        nodes_with_any_flip = sum(1 for _, n_flipped, _, _ in ranked if n_flipped > 0)

        print(f"\n{'='*80}")
        print(f"BER={ber:.1%}  |  Burst: [{args.burst_start}:{burst_end}]  ({flip_count} flips)")
        print(f"Group size: {args.row_group_size}x{args.col_group_size}  Hash bits: {args.hash_bits}")
        print(f"Total nodes: {len(nodes)}  |  Nodes with >=1 flip: {nodes_with_any_flip}  "
              f"|  Ideal: flips spread across many nodes with <=1 flip each")
        print(f"\n{'Rank':<6}{'Node ID':<20}{'Flipped':<10}{'Total bits':<12}{'Flipped indices'}")
        print("-" * 80)
        for rank, (nid, n_flipped, n_total, flipped_set) in enumerate(ranked[:args.top_n], 1):
            preview = str(sorted(flipped_set)[:8])
            if len(flipped_set) > 8:
                preview = preview[:-1] + ", ...]"
            print(f"{rank:<6}{nid:<20}{n_flipped:<10}{n_total:<12}{preview}")


if __name__ == "__main__":
    main()