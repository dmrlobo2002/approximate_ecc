"""End-to-end demo for Feistel grid + CRC DAG bitflip correction."""

from __future__ import annotations

import argparse
import random

from bitflip_solver import correct_with_dag
from grid_shuffle import bits_to_grid, grid_to_bits, source_index_to_grid_coord
from group_hash import build_hash_nodes
from hash_dag import build_hash_graph


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Feistel-grid CRC DAG bitflip correction demo")
    parser.add_argument("--bit-length", type=int, default=37, help="Number of source bits L")
    parser.add_argument("--key", type=str, default="demo-key-123", help="Feistel key string")
    parser.add_argument("--rounds", type=int, default=8, help="Feistel rounds")
    parser.add_argument("--row-group-size", type=int, default=2, help="Non-overlapping row group size")
    parser.add_argument("--col-group-size", type=int, default=2, help="Non-overlapping column group size")
    parser.add_argument("--hash-bits", type=int, choices=[8, 16, 32], default=16, help="CRC bit-width")
    parser.add_argument("--tail-policy", choices=["include_partial", "pad_with_zeros", "drop_partial"], default="include_partial")
    parser.add_argument("--flip-count", type=int, default=2, help="Number of random source-bit flips to inject")
    parser.add_argument(
        "--flip-indices",
        type=str,
        default="",
        help="Comma-separated source indices to flip (overrides --flip-count), e.g. 0,11,24",
    )
    parser.add_argument("--seed", type=int, default=0, help="Random seed used for flip injection")
    parser.add_argument("--viz", action="store_true", help="Render DAG PNG(s) colored by mismatched nodes")
    parser.add_argument("--viz-dir", type=str, default="dag_viz", help="Output directory for DAG PNGs")
    parser.add_argument("--viz-prefix", type=str, default="dag", help="Prefix for generated DAG PNG filenames")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.bit_length <= 0:
        raise ValueError("--bit-length must be positive")

    key = args.key.encode("utf-8")
    bits = [(i * 3 + 1) % 2 for i in range(args.bit_length)]
    baseline_grid, meta = bits_to_grid(bits, key=key, rounds=args.rounds)

    current_grid = [row[:] for row in baseline_grid]
    if args.flip_indices.strip():
        source_flips = [int(x.strip()) for x in args.flip_indices.split(",") if x.strip()]
    else:
        rng = random.Random(args.seed)
        count = max(0, min(args.flip_count, args.bit_length))
        source_flips = rng.sample(range(args.bit_length), count)

    for src_idx in source_flips:
        if src_idx < 0 or src_idx >= args.bit_length:
            raise ValueError(f"flip index out of range: {src_idx}")
        r, c = source_index_to_grid_coord(src_idx, meta)
        current_grid[r][c] ^= 1

    print(f"Injected source flips: {source_flips}")

    baseline_hashes = build_hash_nodes(
        baseline_grid,
        meta,
        row_group_size=args.row_group_size,
        col_group_size=args.col_group_size,
        hash_bits=args.hash_bits,
        tail_policy=args.tail_policy,
    )
    current_hashes = build_hash_nodes(
        current_grid,
        meta,
        row_group_size=args.row_group_size,
        col_group_size=args.col_group_size,
        hash_bits=args.hash_bits,
        tail_policy=args.tail_policy,
    )
    mismatched = sum(1 for a, b in zip(baseline_hashes, current_hashes) if a.digest != b.digest)
    print(f"Initial mismatched hashes: {mismatched}")

    result = correct_with_dag(
        baseline_grid=baseline_grid,
        current_grid=current_grid,
        meta=meta,
        row_group_size=args.row_group_size,
        col_group_size=args.col_group_size,
        hash_bits=args.hash_bits,
        tail_policy=args.tail_policy,
        record_step_snapshots=args.viz,
    )
    print(f"Mismatched before: {len(result.mismatched_before)}")
    print(f"Mismatched after: {len(result.mismatched_after)}")
    for step in result.steps:
        print(step)

    restored_bits = grid_to_bits(result.corrected_grid, meta, key=key)
    print("Recovered original bits:", restored_bits == bits)

    if args.viz:
        try:
            from visualize_dag import render_hash_dag_png

            dag = build_hash_graph(baseline_hashes)
            if not result.step_snapshots:
                print("No successful correction steps were recorded; no DAG snapshots generated.")
                return

            import os

            viz_dir = args.viz_dir
            os.makedirs(viz_dir, exist_ok=True)
            for i, (corrected_node_id, mismatched_node_ids) in enumerate(result.step_snapshots):
                filename = f"{args.viz_prefix}_step_{i:02d}_{corrected_node_id}.png"
                out_path = str(os.path.join(viz_dir, filename))
                render_hash_dag_png(dag, out_path=out_path, mismatched_node_ids=mismatched_node_ids)
                print(f"Wrote: {out_path}")

        except RuntimeError as e:
            print(f"Viz rendering failed: {e}")


if __name__ == "__main__":
    main()

