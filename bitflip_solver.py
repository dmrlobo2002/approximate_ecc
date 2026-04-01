"""DAG-guided correction by exhaustive bit-flip enumeration."""
from __future__ import annotations
from dataclasses import dataclass, field
from itertools import combinations
from group_hash import HashNode, TailPolicy, build_hash_nodes
from grid_shuffle import GridMeta, source_index_to_grid_coord
from hash_dag import HashGraph, build_hash_graph
from experiments.common import Timer


@dataclass
class SolveResult:
    corrected_grid: list[list[int]]
    mismatched_before: set[str]
    mismatched_after: set[str]
    steps: list[str]
    step_snapshots: list[tuple[str, set[str]]] = field(default_factory=list)
    # --- New metrics ---
    total_combos_evaluated: int = 0
    total_nodes_visited: int = 0
    max_flip_level_reached: int = 0
    nodes_with_no_correction: int = 0
    solve_time_seconds: float = 0.0


def _node_map(nodes: list[HashNode]) -> dict[str, HashNode]:
    return {node.node_id: node for node in nodes}


def _mismatched_ids(current_nodes: list[HashNode], baseline_nodes: list[HashNode]) -> set[str]:
    current = _node_map(current_nodes)
    baseline = _node_map(baseline_nodes)
    return {nid for nid, node in current.items() if nid in baseline and node.digest != baseline[nid].digest}


def _copy_grid(grid: list[list[int]]) -> list[list[int]]:
    return [row[:] for row in grid]


def _flip_sources(grid: list[list[int]], source_indices: tuple[int, ...], meta: GridMeta) -> None:
    for src_idx in source_indices:
        r, c = source_index_to_grid_coord(src_idx, meta)
        grid[r][c] ^= 1


def _score_candidate(
    candidate_grid: list[list[int]],
    baseline_nodes: list[HashNode],
    meta: GridMeta,
    row_group_size: int,
    col_group_size: int,
    hash_bits: int,
    tail_policy: TailPolicy,
) -> tuple[int, list[HashNode]]:
    candidate_nodes = build_hash_nodes(
        grid=candidate_grid,
        meta=meta,
        row_group_size=row_group_size,
        col_group_size=col_group_size,
        hash_bits=hash_bits,
        tail_policy=tail_policy,
    )
    baseline_map = _node_map(baseline_nodes)
    matched = sum(1 for node in candidate_nodes if baseline_map[node.node_id].digest == node.digest)
    return matched, candidate_nodes


def correct_with_dag(
    baseline_grid: list[list[int]],
    current_grid: list[list[int]],
    meta: GridMeta,
    row_group_size: int,
    col_group_size: int,
    hash_bits: int,
    tail_policy: TailPolicy = "include_partial",
    record_step_snapshots: bool = False,
) -> SolveResult:
    baseline_nodes = build_hash_nodes(
        grid=baseline_grid,
        meta=meta,
        row_group_size=row_group_size,
        col_group_size=col_group_size,
        hash_bits=hash_bits,
        tail_policy=tail_policy,
    )
    current_nodes = build_hash_nodes(
        grid=current_grid,
        meta=meta,
        row_group_size=row_group_size,
        col_group_size=col_group_size,
        hash_bits=hash_bits,
        tail_policy=tail_policy,
    )
    dag: HashGraph = build_hash_graph(baseline_nodes)
    mismatched_before = _mismatched_ids(current_nodes, baseline_nodes)

    steps: list[str] = []
    step_snapshots: list[tuple[str, set[str]]] = []

    if record_step_snapshots:
        step_snapshots.append(("initial", set(mismatched_before)))

    working_grid = _copy_grid(current_grid)
    baseline_map = _node_map(baseline_nodes)
    ordered_nodes = sorted(dag.nodes.values(), key=lambda n: (n.covered_bits, n.node_id))

    # --- Metric counters ---
    total_combos_evaluated = 0
    total_nodes_visited = 0
    max_flip_level_reached = 0
    nodes_with_no_correction = 0

    _timer = Timer()
    _timer.__enter__()
    for node in ordered_nodes:
        latest_nodes = build_hash_nodes(
            grid=working_grid,
            meta=meta,
            row_group_size=row_group_size,
            col_group_size=col_group_size,
            hash_bits=hash_bits,
            tail_policy=tail_policy,
        )
        latest_map = _node_map(latest_nodes)
        if latest_map[node.node_id].digest == baseline_map[node.node_id].digest:
            continue

        total_nodes_visited += 1
        src_indices = sorted(node.source_indices)

        # Neighbor-pinning: bits shared with currently-matched neighbors are
        # known correct, so restrict the flip search to the remaining "free" bits.
        good_neighbor_bits: set[int] = set()
        for edge in dag.adj[node.node_id]:
            neighbor_id = edge.dst if edge.src == node.node_id else edge.src
            if latest_map[neighbor_id].digest == baseline_map[neighbor_id].digest:
                good_neighbor_bits |= dag.nodes[neighbor_id].source_indices
        free_indices = sorted(node.source_indices - good_neighbor_bits)

        best_grid: list[list[int]] | None = None
        best_nodes: list[HashNode] | None = None
        best_match = -1
        best_flip_count = None

        # Pass 1: search only over free (unpinned) bits.
        # Pass 2 (fallback): if pass 1 found nothing and pinning excluded bits,
        #                     retry over all source bits.
        search_passes = [free_indices]
        if free_indices != src_indices:
            search_passes.append(src_indices)

        for candidate_indices in search_passes:
            for flips in range(len(candidate_indices) + 1):
                found_for_level = False
                for combo in combinations(candidate_indices, flips):
                    total_combos_evaluated += 1
                    candidate = _copy_grid(working_grid)
                    _flip_sources(candidate, combo, meta)
                    score, cand_nodes = _score_candidate(
                        candidate,
                        baseline_nodes=baseline_nodes,
                        meta=meta,
                        row_group_size=row_group_size,
                        col_group_size=col_group_size,
                        hash_bits=hash_bits,
                        tail_policy=tail_policy,
                    )
                    cand_map = _node_map(cand_nodes)
                    if cand_map[node.node_id].digest != baseline_map[node.node_id].digest:
                        continue
                    found_for_level = True
                    if score > best_match:
                        best_match = score
                        best_grid = candidate
                        best_nodes = cand_nodes
                        best_flip_count = flips
                    elif score == best_match and best_flip_count is not None and flips < best_flip_count:
                        best_grid = candidate
                        best_nodes = cand_nodes
                        best_flip_count = flips
                if found_for_level:
                    if flips > max_flip_level_reached:
                        max_flip_level_reached = flips
                    break
            if best_grid is not None:
                break

        if best_grid is not None and best_nodes is not None:
            working_grid = best_grid
            steps.append(f"Corrected {node.node_id} using {best_flip_count} flips.")
            if record_step_snapshots:
                step_mismatched = _mismatched_ids(best_nodes, baseline_nodes)
                step_snapshots.append((node.node_id, step_mismatched))
        else:
            nodes_with_no_correction += 1
            steps.append(f"No correction found for {node.node_id} after full enumeration.")

    final_nodes = build_hash_nodes(
        grid=working_grid,
        meta=meta,
        row_group_size=row_group_size,
        col_group_size=col_group_size,
        hash_bits=hash_bits,
        tail_policy=tail_policy,
    )
    mismatched_after = _mismatched_ids(final_nodes, baseline_nodes)
    _timer.__exit__(None, None, None)

    return SolveResult(
        corrected_grid=working_grid,
        mismatched_before=mismatched_before,
        mismatched_after=mismatched_after,
        steps=steps,
        step_snapshots=step_snapshots,
        total_combos_evaluated=total_combos_evaluated,
        total_nodes_visited=total_nodes_visited,
        max_flip_level_reached=max_flip_level_reached,
        nodes_with_no_correction=nodes_with_no_correction,
        solve_time_seconds=_timer.elapsed,
    )