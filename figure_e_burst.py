"""Figure E: Burst vs. random errors, with and without Feistel shuffle.

Three conditions:
  random + shuffle   — random flip positions, Feistel permutation active (normal)
  burst  + shuffle   — contiguous burst, Feistel permutation active
  burst  + no shuffle — contiguous burst, identity permutation (rounds=0)

Shows that the Feistel shuffle neutralizes burst errors, making them
indistinguishable from random errors at the hash-node level.
"""
from __future__ import annotations

import argparse
import os
from concurrent.futures import ProcessPoolExecutor
from typing import Any

from bitflip_solver import correct_with_dag
from grid_shuffle import bits_to_grid, grid_to_bits, source_index_to_grid_coord
from group_hash import compute_block_hashes

from experiments.common import (
    agg,
    ensure_dir,
    stable_key,
    stable_rng,
    write_csv,
    write_json,
)

CONDITIONS = [
    ("random", 8,  "random + shuffle"),
    ("burst",  8,  "burst  + shuffle"),
    ("burst",  0,  "burst  + no shuffle"),
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Figure E: Burst vs. random, with/without Feistel shuffle")
    p.add_argument("--bit-length", type=int, default=256)
    p.add_argument("--hash-bits", type=int, default=16, choices=[8, 16, 32])
    p.add_argument("--row-group-size", type=int, default=1)
    p.add_argument("--col-group-size", type=int, default=1)
    p.add_argument("--ber-min", type=float, default=0.001)
    p.add_argument("--ber-max", type=float, default=0.10)
    p.add_argument("--ber-steps", type=int, default=20)
    p.add_argument("--keys", type=int, default=30)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--tail-policy", default="include_partial",
                   choices=["include_partial", "pad_with_zeros", "drop_partial"])
    p.add_argument("--out-dir", type=str, default="results/fig_e")
    p.add_argument("--no-plot", action="store_true")
    p.add_argument("--max-combos", type=int, default=None,
                   help="Per-trial combo budget cap (None = unlimited)")
    p.add_argument("--block-count", type=int, default=0,
                   help="Sector hashes for tiered localization (0=disabled, 32-bit per sector)")
    p.add_argument("--parallel", action="store_true",
                   help="Run trials in parallel using multiple processes")
    p.add_argument("--workers", type=int, default=0,
                   help="Number of parallel workers (0 = one per task, up to cpu_count)")
    return p.parse_args()


def get_flip_indices(flip_count: int, bit_length: int, mode: str, rng) -> list[int]:
    if mode == "random":
        return rng.sample(range(bit_length), min(flip_count, bit_length))
    elif mode == "burst":
        max_start = max(0, bit_length - flip_count)
        start = rng.randint(0, max_start)
        return list(range(start, min(start + flip_count, bit_length)))
    raise ValueError(f"unknown mode: {mode}")


def run_trial(
    bits: list[int],
    key: bytes,
    rounds: int,
    flip_indices: list[int],
    row_group_size: int,
    col_group_size: int,
    hash_bits: int,
    tail_policy: str,
    max_combos: int | None = None,
    block_count: int = 0,
) -> dict[str, Any]:
    baseline_grid, meta = bits_to_grid(bits, key=key, rounds=rounds)
    current_grid = [row[:] for row in baseline_grid]
    for src_idx in flip_indices:
        r, c = source_index_to_grid_coord(src_idx, meta)
        current_grid[r][c] ^= 1

    globally_pinned: frozenset = frozenset()
    if block_count > 0:
        baseline_blocks = compute_block_hashes(baseline_grid, meta, block_count)
        current_blocks  = compute_block_hashes(current_grid,  meta, block_count)
        for bbase, bcurr in zip(baseline_blocks, current_blocks):
            if bbase.digest == bcurr.digest:
                globally_pinned |= bbase.source_indices

    result = correct_with_dag(
        baseline_grid=baseline_grid,
        current_grid=current_grid,
        meta=meta,
        row_group_size=row_group_size,
        col_group_size=col_group_size,
        hash_bits=hash_bits,
        tail_policy=tail_policy,
        max_combos=max_combos,
        globally_pinned=globally_pinned,
    )
    restored = grid_to_bits(result.corrected_grid, meta, key=key)
    return {
        "fully_corrected": restored == bits,
        "mismatched_before": len(result.mismatched_before),
        "mismatched_after": len(result.mismatched_after),
        "total_combos_evaluated": result.total_combos_evaluated,
        "solve_time_seconds": result.solve_time_seconds,
    }


def _trial_task(task: tuple) -> dict:
    """Top-level wrapper so ProcessPoolExecutor can pickle the work unit."""
    bits, key, rounds, flip_indices, row_group_size, col_group_size, hash_bits, tail_policy, max_combos, block_count = task
    return run_trial(bits, key, rounds, flip_indices, row_group_size, col_group_size, hash_bits, tail_policy, max_combos, block_count)


def main() -> None:
    args = parse_args()
    ensure_dir(args.out_dir)

    ber_points = [
        args.ber_min * ((args.ber_max / args.ber_min) ** (i / max(1, args.ber_steps - 1)))
        for i in range(args.ber_steps)
    ]
    bits = [(i * 3 + 1) % 2 for i in range(args.bit_length)]

    write_json(os.path.join(args.out_dir, "config.json"), {
        "bit_length": args.bit_length,
        "hash_bits": args.hash_bits,
        "row_group_size": args.row_group_size,
        "col_group_size": args.col_group_size,
        "ber_min": args.ber_min,
        "ber_max": args.ber_max,
        "ber_steps": args.ber_steps,
        "keys": args.keys,
        "seed": args.seed,
        "tail_policy": args.tail_policy,
        "conditions": CONDITIONS,
    })

    all_tasks: list[tuple] = []
    for flip_mode, rounds, label in CONDITIONS:
        for ber in ber_points:
            flip_count = max(1, round(ber * args.bit_length))
            for key_id in range(args.keys):
                key = stable_key(args.seed, key_id)
                rng = stable_rng(args.seed, key_id, flip_count, flip_mode, rounds)
                flip_indices = get_flip_indices(flip_count, args.bit_length, flip_mode, rng)
                all_tasks.append((
                    bits, key, rounds, flip_indices,
                    args.row_group_size, args.col_group_size,
                    args.hash_bits, args.tail_policy, args.max_combos, args.block_count,
                ))

    if args.parallel:
        n_workers = args.workers if args.workers > 0 else min(len(all_tasks), os.cpu_count() or 1)
        print(f"Running {len(all_tasks)} trials across {n_workers} workers...")
        with ProcessPoolExecutor(max_workers=n_workers) as executor:
            flat_results = list(executor.map(_trial_task, all_tasks))
    else:
        flat_results = [_trial_task(t) for t in all_tasks]

    rows: list[dict[str, Any]] = []
    idx = 0
    for flip_mode, rounds, label in CONDITIONS:
        for ber in ber_points:
            flip_count = max(1, round(ber * args.bit_length))
            actual_ber = flip_count / args.bit_length
            trial_results = flat_results[idx: idx + args.keys]
            idx += args.keys

            success_rate = sum(1 for t in trial_results if t["fully_corrected"]) / len(trial_results)
            combos_a = agg([float(t["total_combos_evaluated"]) for t in trial_results])
            time_a = agg([t["solve_time_seconds"] for t in trial_results])

            rows.append({
                "condition": label,
                "flip_mode": flip_mode,
                "rounds": rounds,
                "ber_target": round(ber, 6),
                "ber_actual": round(actual_ber, 6),
                "flip_count": flip_count,
                "success_rate": round(success_rate, 4),
                "mean_combos": round(combos_a.mean, 2),
                "mean_solve_time_s": round(time_a.mean, 6),
                "n_trials": args.keys,
            })
            print(
                f"{label:26s}  BER={actual_ber:.3f}  flips={flip_count:3d}  "
                f"success={success_rate:.3f}  combos={combos_a.mean:.1f}"
            )

    csv_path = os.path.join(args.out_dir, "figure_e_burst.csv")
    write_csv(
        csv_path, rows,
        fieldnames=["condition", "flip_mode", "rounds", "ber_target", "ber_actual",
                    "flip_count", "success_rate", "mean_combos", "mean_solve_time_s", "n_trials"],
    )
    print(f"Wrote CSV: {csv_path}")

    if args.no_plot:
        return

    try:
        import matplotlib.pyplot as plt
    except ModuleNotFoundError as e:
        raise RuntimeError("matplotlib required for plotting; use --no-plot to skip") from e

    linestyles = {
        "random + shuffle":  ("-",  "o", "#1f77b4"),
        "burst  + shuffle":  ("--", "s", "#ff7f0e"),
        "burst  + no shuffle": (":", "^", "#d62728"),
    }

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    fig.suptitle(
        f"Burst vs. Random Errors: Impact of Feistel Shuffle\n"
        f"({args.bit_length} bits, {args.hash_bits}-bit hash, "
        f"group {args.row_group_size}×{args.col_group_size})",
        fontsize=13,
    )

    ax_l, ax_r = axes
    for label in [c[2] for c in CONDITIONS]:
        ls, mk, col = linestyles[label]
        subset = sorted([r for r in rows if r["condition"] == label], key=lambda r: r["ber_actual"])
        xs = [r["ber_actual"] for r in subset]
        ax_l.plot(xs, [r["success_rate"] for r in subset],
                  linestyle=ls, marker=mk, color=col, linewidth=2, label=label)
        ax_r.plot(xs, [r["mean_combos"] for r in subset],
                  linestyle=ls, marker=mk, color=col, linewidth=2, label=label)

    ax_l.set_title("Correction success rate vs. BER")
    ax_l.set_xlabel("BER"); ax_l.set_ylabel("Success rate")
    ax_l.set_xscale("log"); ax_l.set_ylim(-0.05, 1.05)
    ax_l.grid(True, alpha=0.3); ax_l.legend()

    ax_r.set_title("Decoder complexity vs. BER")
    ax_r.set_xlabel("BER"); ax_r.set_ylabel("Mean combinations evaluated")
    ax_r.set_xscale("log"); ax_r.set_yscale("log")
    ax_r.grid(True, alpha=0.3); ax_r.legend()

    plt.tight_layout()
    out_png = os.path.join(args.out_dir, "figure_e_burst.png")
    plt.savefig(out_png, dpi=200)
    plt.close()
    print(f"Wrote plot: {out_png}")


if __name__ == "__main__":
    main()
