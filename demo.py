"""End-to-end demo for Feistel grid + CRC DAG bitflip correction."""

from __future__ import annotations

import argparse
import random

from bitflip_solver import correct_with_dag, correct_without_golden
from grid_shuffle import bits_to_grid, grid_to_bits, source_index_to_grid_coord
from group_hash import build_hash_nodes
from hash_dag import build_hash_graph


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Feistel-grid CRC DAG bitflip correction demo")
    parser.add_argument("--bit-length", type=int, default=4096, help="Number of source bits L")
    parser.add_argument("--key", type=str, default="demo-key-123", help="Feistel key string")
    parser.add_argument("--rounds", type=int, default=8, help="Feistel rounds")
    parser.add_argument("--row-group-size", type=int, default=1, help="Non-overlapping row group size")
    parser.add_argument("--col-group-size", type=int, default=1, help="Non-overlapping column group size")
    parser.add_argument("--row-splits", type=int, default=1, help="Split each row hash node into N column sub-ranges")
    parser.add_argument("--col-splits", type=int, default=1, help="Split each col hash node into N row sub-ranges")
    parser.add_argument("--hash-bits", type=int, default=16, help="Hash bit-width (8/16/32 for CRC; any positive int for simhash)")
    parser.add_argument("--hash-type", choices=["crc", "simhash"], default="crc", help="Hash scheme")
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
    parser.add_argument("--golden-bits", action="store_true", help="Use original (golden) bits for solver scoring; without this flag the solver uses only stored hashes")
    parser.add_argument("--max-flips", type=int, default=2, help="Max flips tried per node (correct_without_golden path only)")
    parser.add_argument("--max-combos", type=int, default=None, help="Global combo budget cap (correct_with_dag path only; None = unlimited)")
    parser.add_argument("--max-flips-ceiling", type=int, default=8, help="Max flip depth the iterative solver climbs to (correct_with_dag/--golden-bits path only; triggers Python solver)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.bit_length <= 0:
        raise ValueError("--bit-length must be positive")
    if args.hash_type == "crc" and args.hash_bits not in {8, 16, 32}:
        raise ValueError("--hash-bits must be 8, 16, or 32 for CRC")

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
        hash_type=args.hash_type,
        row_splits=args.row_splits,
        col_splits=args.col_splits,
    )
    current_hashes = build_hash_nodes(
        current_grid,
        meta,
        row_group_size=args.row_group_size,
        col_group_size=args.col_group_size,
        hash_bits=args.hash_bits,
        tail_policy=args.tail_policy,
        hash_type=args.hash_type,
        row_splits=args.row_splits,
        col_splits=args.col_splits,
    )
    mismatched = sum(1 for a, b in zip(baseline_hashes, current_hashes) if a.digest != b.digest)
    print(f"Initial mismatched hashes: {mismatched}")

    if args.golden_bits:
        result = correct_with_dag(
            baseline_grid=baseline_grid,
            current_grid=current_grid,
            meta=meta,
            row_group_size=args.row_group_size,
            col_group_size=args.col_group_size,
            hash_bits=args.hash_bits,
            tail_policy=args.tail_policy,
            record_step_snapshots=args.viz,
            max_combos=args.max_combos,
            hash_type=args.hash_type,
            max_flips_ceiling=args.max_flips_ceiling,
            row_splits=args.row_splits,
            col_splits=args.col_splits,
        )
    else:
        result = correct_without_golden(
            baseline_nodes=baseline_hashes,
            current_grid=current_grid,
            meta=meta,
            row_group_size=args.row_group_size,
            col_group_size=args.col_group_size,
            hash_bits=args.hash_bits,
            tail_policy=args.tail_policy,
            record_step_snapshots=args.viz,
            max_flips=args.max_flips,
            hash_type=args.hash_type,
            row_splits=args.row_splits,
            col_splits=args.col_splits,
        )
    print(f"Mismatched before: {len(result.mismatched_before)}")
    print(f"Mismatched after: {len(result.mismatched_after)}")
    for step in result.steps:
        print(step)

    # Compute grid HD against baseline for display (available in demo even without --golden-bits)
    rows, cols = len(baseline_grid), len(baseline_grid[0]) if baseline_grid else 0
    grid_hd_before = sum(
        baseline_grid[r][c] != current_grid[r][c]
        for r in range(rows) for c in range(cols)
    )
    grid_hd_after = sum(
        baseline_grid[r][c] != result.corrected_grid[r][c]
        for r in range(rows) for c in range(cols)
    )
    print(f"Grid HD before repair (bits damaged): {grid_hd_before}")
    print(f"Grid HD after repair  (bits remaining wrong): {grid_hd_after}")
    bits_recovered = grid_hd_before - grid_hd_after
    print(f"Bits recovered: {bits_recovered}/{grid_hd_before}")

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

