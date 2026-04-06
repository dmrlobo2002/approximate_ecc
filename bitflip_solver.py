"""DAG-guided correction by exhaustive bit-flip enumeration."""
from __future__ import annotations
from dataclasses import dataclass, field
from itertools import combinations
from group_hash import GroupHashContext, HashNode, TailPolicy, build_group_context, build_hash_nodes, recompute_node
from grid_shuffle import GridMeta, source_index_to_grid_coord
from hash_dag import HashGraph, build_hash_graph
from experiments.common import Timer

try:
    from _ecc_cpp import correct_with_dag as _cpp_correct_with_dag
    _HAS_CPP = True
except ImportError:
    _HAS_CPP = False


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



def _apply_combo_and_score(
    combo: tuple[int, ...],
    target_node_id: str,
    working_grid: list[list[int]],
    live_nodes: dict[str, HashNode],
    live_matched: int,
    baseline_map: dict[str, HashNode],
    ctx: GroupHashContext,
) -> tuple[int, bool]:
    affected_ids: set[str] = set()
    for src_idx in combo:
        for nid in ctx.src_to_node_ids[src_idx]:
            affected_ids.add(nid)
    saved = {nid: live_nodes[nid] for nid in affected_ids}
    for src_idx in combo:
        r, c = source_index_to_grid_coord(src_idx, ctx.meta)
        working_grid[r][c] ^= 1
    for nid in affected_ids:
        live_nodes[nid] = recompute_node(live_nodes[nid], working_grid, ctx)
    if live_nodes[target_node_id].digest != baseline_map[target_node_id].digest:
        for nid, old_node in saved.items():
            live_nodes[nid] = old_node
        for src_idx in combo:
            r, c = source_index_to_grid_coord(src_idx, ctx.meta)
            working_grid[r][c] ^= 1
        return -1, False
    delta = sum(
        int(live_nodes[nid].digest == baseline_map[nid].digest) - int(saved[nid].digest == baseline_map[nid].digest)
        for nid in affected_ids
    )
    for nid, old_node in saved.items():
        live_nodes[nid] = old_node
    for src_idx in combo:
        r, c = source_index_to_grid_coord(src_idx, ctx.meta)
        working_grid[r][c] ^= 1
    return live_matched + delta, True


def _commit_combo(
    combo: tuple[int, ...],
    working_grid: list[list[int]],
    live_nodes: dict[str, HashNode],
    live_matched: int,
    baseline_map: dict[str, HashNode],
    ctx: GroupHashContext,
) -> int:
    affected_ids: set[str] = set()
    for src_idx in combo:
        for nid in ctx.src_to_node_ids[src_idx]:
            affected_ids.add(nid)
    for src_idx in combo:
        r, c = source_index_to_grid_coord(src_idx, ctx.meta)
        working_grid[r][c] ^= 1
    for nid in affected_ids:
        old_matched = live_nodes[nid].digest == baseline_map[nid].digest
        live_nodes[nid] = recompute_node(live_nodes[nid], working_grid, ctx)
        new_matched = live_nodes[nid].digest == baseline_map[nid].digest
        live_matched += int(new_matched) - int(old_matched)
    return live_matched


def _count_node_flips(
    node: HashNode,
    baseline_grid: list[list[int]],
    current_grid: list[list[int]],
    ctx: "GroupHashContext",
) -> int:
    n = ctx.meta.n
    if node.axis == "row":
        r0, r1 = ctx.row_groups[node.group_index]
        return sum(
            baseline_grid[r][c] != current_grid[r][c]
            for r in range(r0, r1) for c in range(n)
        )
    else:
        c0, c1 = ctx.col_groups[node.group_index]
        return sum(
            baseline_grid[r][c] != current_grid[r][c]
            for r in range(n) for c in range(c0, c1)
        )


def correct_with_dag(
    baseline_grid: list[list[int]],
    current_grid: list[list[int]],
    meta: GridMeta,
    row_group_size: int,
    col_group_size: int,
    hash_bits: int,
    tail_policy: TailPolicy = "include_partial",
    record_step_snapshots: bool = False,
    max_combos: int | None = None,
    globally_pinned: frozenset = frozenset(),
) -> SolveResult:
    if _HAS_CPP:
        raw = _cpp_correct_with_dag(
            baseline_grid, current_grid, meta,
            row_group_size, col_group_size, hash_bits,
            tail_policy, record_step_snapshots,
            max_combos, globally_pinned if globally_pinned else None,
        )
        return SolveResult(
            corrected_grid=raw["corrected_grid"],
            mismatched_before=raw["mismatched_before"],
            mismatched_after=raw["mismatched_after"],
            steps=raw["steps"],
            step_snapshots=list(raw["step_snapshots"]),
            total_combos_evaluated=raw["total_combos_evaluated"],
            total_nodes_visited=raw["total_nodes_visited"],
            max_flip_level_reached=raw["max_flip_level_reached"],
            nodes_with_no_correction=raw["nodes_with_no_correction"],
            solve_time_seconds=raw["solve_time_seconds"],
        )
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
    ctx = build_group_context(meta, row_group_size, col_group_size, hash_bits, tail_policy)
    flip_counts = {
        node.node_id: _count_node_flips(node, baseline_grid, current_grid, ctx)
        for node in dag.nodes.values()
    }
    ordered_nodes = sorted(dag.nodes.values(), key=lambda n: (flip_counts[n.node_id], n.covered_bits, n.node_id))
    live_nodes: dict[str, HashNode] = _node_map(current_nodes)
    live_matched = sum(1 for nid, n in live_nodes.items() if baseline_map[nid].digest == n.digest)

    # --- Metric counters ---
    total_combos_evaluated = 0
    total_nodes_visited = 0
    max_flip_level_reached = 0
    nodes_with_no_correction = 0

    _timer = Timer()
    _timer.__enter__()
    for node in ordered_nodes:
        if live_nodes[node.node_id].digest == baseline_map[node.node_id].digest:
            continue

        total_nodes_visited += 1
        src_indices = sorted(node.source_indices)

        # Single pass over neighbors: collect bits from matched neighbors (pinned)
        # and bits from mismatched neighbors (intersection candidates).
        good_neighbor_bits: set[int] = set()
        mismatched_neighbor_bits: set[int] = set()
        for edge in dag.adj[node.node_id]:
            neighbor_id = edge.dst if edge.src == node.node_id else edge.src
            neighbor_bits = dag.nodes[neighbor_id].source_indices
            if live_nodes[neighbor_id].digest == baseline_map[neighbor_id].digest:
                good_neighbor_bits |= neighbor_bits
            else:
                mismatched_neighbor_bits |= neighbor_bits
        free_indices = sorted(node.source_indices - good_neighbor_bits - globally_pinned)
        intersection_indices = sorted(node.source_indices & mismatched_neighbor_bits & set(free_indices))

        best_combo: tuple[int, ...] | None = None
        best_match = -1
        best_flip_count = None

        search_passes: list[list[int]] = []
        if intersection_indices and intersection_indices != free_indices:
            search_passes.append(intersection_indices)
        search_passes.append(free_indices)
        if free_indices != src_indices:
            search_passes.append(src_indices)

        budget_exhausted = False
        for candidate_indices in search_passes:
            for flips in range(len(candidate_indices) + 1):
                found_for_level = False
                for combo in combinations(candidate_indices, flips):
                    total_combos_evaluated += 1
                    if max_combos is not None and total_combos_evaluated > max_combos:
                        budget_exhausted = True
                        break
                    score, fixed = _apply_combo_and_score(
                        combo, node.node_id, working_grid, live_nodes, live_matched, baseline_map, ctx
                    )
                    if not fixed:
                        continue
                    found_for_level = True
                    if score > best_match:
                        best_match = score
                        best_combo = combo
                        best_flip_count = flips
                    elif score == best_match and best_flip_count is not None and flips < best_flip_count:
                        best_combo = combo
                        best_flip_count = flips
                if budget_exhausted:
                    break
                if found_for_level:
                    if flips > max_flip_level_reached:
                        max_flip_level_reached = flips
                    break
            if budget_exhausted or best_combo is not None:
                break

        if best_combo is not None:
            live_matched = _commit_combo(best_combo, working_grid, live_nodes, live_matched, baseline_map, ctx)
            steps.append(f"Corrected {node.node_id} using {best_flip_count} flips.")
            if live_matched == len(baseline_map):
                break
            if record_step_snapshots:
                step_mismatched = {nid for nid, n in live_nodes.items() if n.digest != baseline_map[nid].digest}
                step_snapshots.append((node.node_id, step_mismatched))
        else:
            nodes_with_no_correction += 1
            steps.append(f"No correction found for {node.node_id} after full enumeration.")

    mismatched_after = {nid for nid, n in live_nodes.items() if n.digest != baseline_map[nid].digest}
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