"""Shared trial execution utilities for figure scripts."""
from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any

from bitflip_solver import correct_with_dag
from grid_shuffle import bits_to_grid, grid_to_bits, source_index_to_grid_coord
from group_hash import build_hash_nodes, compute_block_hashes
from hash_dag import build_hash_graph


def get_flip_indices(flip_count: int, bit_length: int, mode: str, rng) -> list[int]:
    if mode == "random":
        return rng.sample(range(bit_length), flip_count)
    elif mode == "burst":
        max_start = bit_length - flip_count
        start = rng.randint(0, max_start)
        return list(range(start, start + flip_count))
    else:
        raise ValueError(f"Unknown flip mode: {mode}")


def run_trial(
    bits: list[int],
    key: bytes,
    rounds: int,
    flip_indices: list[int],
    row_group_size: int,
    col_group_size: int,
    hash_bits: int,
    tail_policy: str = "include_partial",
    max_combos: int | None = None,
    block_count: int = 0,
    hash_type: str = "crc",
    row_splits: int = 1,
    col_splits: int = 1,
) -> dict[str, Any]:
    baseline_grid, meta = bits_to_grid(bits, key=key, rounds=rounds)
    current_grid = [row[:] for row in baseline_grid]

    for src_idx in flip_indices:
        r, c = source_index_to_grid_coord(src_idx, meta)
        current_grid[r][c] ^= 1

    globally_pinned: frozenset = frozenset()
    if block_count > 0:
        baseline_blocks = compute_block_hashes(baseline_grid, meta, block_count)
        current_blocks = compute_block_hashes(current_grid, meta, block_count)
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
        record_step_snapshots=False,
        max_combos=max_combos,
        globally_pinned=globally_pinned,
        hash_type=hash_type,
        row_splits=row_splits,
        col_splits=col_splits,
    )

    restored_bits = grid_to_bits(result.corrected_grid, meta, key=key)
    fully_corrected = restored_bits == bits
    # True when the solver committed a wrong combination that passed the CRC check by collision
    crc_false_positive = (len(result.mismatched_after) == 0 and not fully_corrected)

    return {
        "fully_corrected": fully_corrected,
        "crc_false_positive": crc_false_positive,
        "mismatched_before": len(result.mismatched_before),
        "mismatched_after": len(result.mismatched_after),
        "total_combos_evaluated": result.total_combos_evaluated,
        "total_nodes_visited": result.total_nodes_visited,
        "max_flip_level_reached": result.max_flip_level_reached,
        "nodes_with_no_correction": result.nodes_with_no_correction,
        "solve_time_ms": round(result.solve_time_seconds * 1000, 3),
    }


def _trial_task(task: tuple) -> dict[str, Any]:
    bits, key, rounds, flip_indices, rgs, cgs, hb, tp, mc, bc, ht, rs, cs = task
    return run_trial(bits, key, rounds, flip_indices, rgs, cgs, hb, tp, mc, bc, ht, rs, cs)


def run_trials_parallel(tasks: list[tuple], n_workers: int = 0) -> list[dict[str, Any]]:
    total = len(tasks)
    workers = n_workers if n_workers > 0 else min(total, os.cpu_count() or 1)
    results: list[dict[str, Any] | None] = [None] * total
    done = 0
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(_trial_task, t): i for i, t in enumerate(tasks)}
        for fut in as_completed(futures):
            results[futures[fut]] = fut.result()
            done += 1
            print(f"\r  Progress: {done}/{total} ({100 * done / total:.1f}%)", end="", flush=True)
    print()
    return results  # type: ignore[return-value]


def run_batch(tasks: list[tuple], parallel: bool = False, n_workers: int = 0) -> list[dict[str, Any]]:
    """Run a small batch of tasks (e.g. one flip-count × all keys) without progress reporting."""
    if not parallel or len(tasks) <= 1:
        return [_trial_task(t) for t in tasks]
    workers = n_workers if n_workers > 0 else min(len(tasks), os.cpu_count() or 1)
    results: list[dict[str, Any] | None] = [None] * len(tasks)
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(_trial_task, t): i for i, t in enumerate(tasks)}
        for fut in as_completed(futures):
            results[futures[fut]] = fut.result()
    return results  # type: ignore[return-value]


def run_trials_serial(tasks: list[tuple]) -> list[dict[str, Any]]:
    total = len(tasks)
    results = []
    for i, t in enumerate(tasks):
        results.append(_trial_task(t))
        print(f"\r  Progress: {i + 1}/{total} ({100 * (i + 1) / total:.1f}%)", end="", flush=True)
    print()
    return results
