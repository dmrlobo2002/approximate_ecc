"""DAG-guided correction by exhaustive bit-flip enumeration."""
from __future__ import annotations
from dataclasses import dataclass, field
from itertools import combinations


def hamming_distance(a: int, b: int) -> int:
    return bin(a ^ b).count('1')
from group_hash import GroupHashContext, HashNode, TailPolicy, build_group_context, build_hash_nodes, recompute_node
from grid_shuffle import GridMeta, source_index_to_grid_coord
from hash_dag import HashGraph, build_hash_graph
from experiments.common import Timer

try:
    from _ecc_cpp import correct_with_dag as _cpp_correct_with_dag
    from _ecc_cpp import correct_without_golden as _cpp_correct_without_golden
    _HAS_CPP = True
    print("Found C++ files...")
except ImportError:
    _HAS_CPP = False
    print("[WARNING] No C++ files found...")


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
    grid_hd_before: int = 0
    grid_hd_after: int = 0


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
    if node.axis == "row":
        r0, r1 = ctx.row_groups[node.group_index // ctx.row_splits]
        c0, c1 = ctx.row_node_col_ranges[node.group_index]
        return sum(
            baseline_grid[r][c] != current_grid[r][c]
            for r in range(r0, r1) for c in range(c0, c1)
        )
    else:
        c0, c1 = ctx.col_groups[node.group_index // ctx.col_splits]
        r0, r1 = ctx.col_node_row_ranges[node.group_index]
        return sum(
            baseline_grid[r][c] != current_grid[r][c]
            for r in range(r0, r1) for c in range(c0, c1)
        )


def correct_without_golden(
    baseline_nodes: list[HashNode],
    current_grid: list[list[int]],
    meta: GridMeta,
    row_group_size: int,
    col_group_size: int,
    hash_bits: int,
    tail_policy: TailPolicy = "include_partial",
    record_step_snapshots: bool = False,
    max_flips: int = 8,
    hash_type: str = "crc",
    row_splits: int = 1,
    col_splits: int = 1,
) -> SolveResult:
    """Solver that requires only stored hash digests, not the original (golden) bits.

    Iteratively climbs flip levels 1..max_flips.  At each level, makes repeated
    passes over all mismatched nodes until no further progress, then advances to
    the next level.  Fixing a node cascades: shared bits between row and column
    nodes mean a fix in one reduces the effective flip count in its neighbors,
    often making them solvable at a lower level on the next pass.

    Within each pass, nodes are sorted by the number of currently-mismatched
    neighbors (fewest first) as a proxy for ease — a node whose neighbors are
    mostly already fixed has more of its bits pinned, making it a simpler target.
    """
    current_nodes = build_hash_nodes(
        grid=current_grid,
        meta=meta,
        row_group_size=row_group_size,
        col_group_size=col_group_size,
        hash_bits=hash_bits,
        tail_policy=tail_policy,
        hash_type=hash_type,
        row_splits=row_splits,
        col_splits=col_splits,
    )
    baseline_map = _node_map(baseline_nodes)
    ctx = build_group_context(meta, row_group_size, col_group_size, hash_bits, tail_policy, hash_type, row_splits, col_splits)
    live_nodes = _node_map(current_nodes)
    mismatched_before = _mismatched_ids(current_nodes, baseline_nodes)

    steps: list[str] = []
    step_snapshots: list[tuple[str, set[str]]] = []
    if record_step_snapshots:
        step_snapshots.append(("initial", set(mismatched_before)))

    working_grid = _copy_grid(current_grid)
    live_matched = sum(1 for nid, n in live_nodes.items() if baseline_map[nid].digest == n.digest)

    total_combos_evaluated = 0
    total_nodes_visited = 0
    max_flip_level_reached = 0
    nodes_with_no_correction = 0

    def _mismatched_neighbor_count(node: HashNode) -> int:
        """Proxy for difficulty: how many intersecting nodes are still mismatched."""
        neighbors: set[str] = set()
        for src_idx in node.source_indices:
            for nid in ctx.src_to_node_ids[src_idx]:
                if nid != node.node_id:
                    neighbors.add(nid)
        return sum(1 for nid in neighbors if live_nodes[nid].digest != baseline_map[nid].digest)

    _timer = Timer()
    _timer.__enter__()

    all_done = False
    for current_max_flips in range(1, max_flips + 1):
        # Exhaust everything fixable at this flip depth before moving on.
        while True:
            # Re-sort each pass: fewest mismatched neighbors first (easiest targets).
            all_node_list = list(live_nodes.values())
            ordered_nodes = sorted(
                all_node_list,
                key=lambda n: (_mismatched_neighbor_count(n), n.covered_bits, n.node_id),
            )

            any_fixed = False
            for node in ordered_nodes:
                if live_nodes[node.node_id].digest == baseline_map[node.node_id].digest:
                    continue

                total_nodes_visited += 1
                src_indices = sorted(node.source_indices)
                committed = False

                for flips in range(1, current_max_flips + 1):
                    if committed:
                        break
                    for combo in combinations(src_indices, flips):
                        total_combos_evaluated += 1
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

                        if live_nodes[node.node_id].digest == baseline_map[node.node_id].digest:
                            live_matched += sum(
                                int(live_nodes[nid].digest == baseline_map[nid].digest)
                                - int(saved[nid].digest == baseline_map[nid].digest)
                                for nid in affected_ids
                            )
                            if flips > max_flip_level_reached:
                                max_flip_level_reached = flips
                            steps.append(f"[lvl={current_max_flips}] Corrected {node.node_id} with {flips} flip(s).")
                            if record_step_snapshots:
                                step_mismatched = {nid for nid, n in live_nodes.items() if n.digest != baseline_map[nid].digest}
                                step_snapshots.append((node.node_id, step_mismatched))
                            committed = True
                            any_fixed = True
                            break
                        else:
                            for nid, old_node in saved.items():
                                live_nodes[nid] = old_node
                            for src_idx in combo:
                                r, c = source_index_to_grid_coord(src_idx, ctx.meta)
                                working_grid[r][c] ^= 1

                if not committed:
                    nodes_with_no_correction += 1
                elif live_matched == len(baseline_map):
                    all_done = True
                    break

            if all_done or not any_fixed:
                break  # no progress at this level — advance to next flip depth

        if all_done:
            break

    _timer.__exit__(None, None, None)
    mismatched_after = {nid for nid, n in live_nodes.items() if n.digest != baseline_map[nid].digest}

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
        grid_hd_before=0,
        grid_hd_after=0,
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
    hash_type: str = "crc",
    max_flips_ceiling: int | None = None,
    row_splits: int = 1,
    col_splits: int = 1,
) -> SolveResult:
    # Use C++ fast path only when splits=1 and the iterative algorithm is not requested.
    # The C++ extension does not support row_splits/col_splits.
    if _HAS_CPP and max_flips_ceiling is None and row_splits == 1 and col_splits == 1 and hash_bits <= 32:
        raw = _cpp_correct_with_dag(
            baseline_grid, current_grid, meta,
            row_group_size, col_group_size, hash_bits,
            tail_policy, record_step_snapshots,
            max_combos, globally_pinned if globally_pinned else None,
            hash_type,
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
            grid_hd_before=raw["grid_hd_before"],
            grid_hd_after=raw["grid_hd_after"],
        )
    baseline_nodes = build_hash_nodes(
        grid=baseline_grid,
        meta=meta,
        row_group_size=row_group_size,
        col_group_size=col_group_size,
        hash_bits=hash_bits,
        tail_policy=tail_policy,
        hash_type=hash_type,
        row_splits=row_splits,
        col_splits=col_splits,
    )
    current_nodes = build_hash_nodes(
        grid=current_grid,
        meta=meta,
        row_group_size=row_group_size,
        col_group_size=col_group_size,
        hash_bits=hash_bits,
        tail_policy=tail_policy,
        hash_type=hash_type,
        row_splits=row_splits,
        col_splits=col_splits,
    )
    dag: HashGraph = build_hash_graph(baseline_nodes)
    mismatched_before = _mismatched_ids(current_nodes, baseline_nodes)

    steps: list[str] = []
    step_snapshots: list[tuple[str, set[str]]] = []

    if record_step_snapshots:
        step_snapshots.append(("initial", set(mismatched_before)))

    working_grid = _copy_grid(current_grid)
    baseline_map = _node_map(baseline_nodes)
    ctx = build_group_context(meta, row_group_size, col_group_size, hash_bits, tail_policy, hash_type, row_splits, col_splits)
    if hash_type == "simhash":
        b_map = _node_map(baseline_nodes)
        c_map = _node_map(current_nodes)
        scores = {
            nid: hamming_distance(b_map[nid].digest, c_map[nid].digest)
            for nid in b_map
        }
    else:
        scores = {
            node.node_id: _count_node_flips(node, baseline_grid, current_grid, ctx)
            for node in dag.nodes.values()
        }
    ordered_nodes = sorted(dag.nodes.values(), key=lambda n: (scores[n.node_id], n.covered_bits, n.node_id))
    live_nodes: dict[str, HashNode] = _node_map(current_nodes)
    live_matched = sum(1 for nid, n in live_nodes.items() if baseline_map[nid].digest == n.digest)

    # --- Metric counters ---
    total_combos_evaluated = 0
    total_nodes_visited = 0
    max_flip_level_reached = 0
    nodes_with_no_correction = 0

    _timer = Timer()
    _timer.__enter__()

    _ceiling = max_flips_ceiling if max_flips_ceiling is not None else 8
    # Iterative flip-level climbing:
    # At level k, exhaust every node fixable with <= k flips (making multiple passes
    # until no more progress), then advance to k+1.  Fixing a node at level k reduces
    # the effective flip count in its intersecting neighbors, so previously-stuck nodes
    # often become solvable at a lower level on the next pass.
    all_done = False
    for current_max_flips in range(1, _ceiling + 1):
        while True:
            # Re-score and re-sort at the start of every pass so nodes with the
            # fewest remaining flips (easiest targets) are always attempted first.
            if hash_type == "simhash":
                scores = {
                    nid: hamming_distance(baseline_map[nid].digest, live_nodes[nid].digest)
                    for nid in baseline_map
                }
            else:
                scores = {
                    node.node_id: _count_node_flips(node, baseline_grid, working_grid, ctx)
                    for node in dag.nodes.values()
                }
            ordered_nodes = sorted(
                dag.nodes.values(),
                key=lambda n: (scores[n.node_id], n.covered_bits, n.node_id),
            )

            any_fixed = False
            budget_exhausted = False

            for node in ordered_nodes:
                if live_nodes[node.node_id].digest == baseline_map[node.node_id].digest:
                    continue

                total_nodes_visited += 1
                src_indices = sorted(node.source_indices)

                # Neighbor pruning: bits covered by matched neighbors are pinned (untouchable);
                # bits shared with mismatched neighbors are the most likely flip sites.
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

                for candidate_indices in search_passes:
                    for flips in range(min(current_max_flips, len(candidate_indices)) + 1):
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
                    steps.append(f"[lvl={current_max_flips}] Corrected {node.node_id} with {best_flip_count} flip(s).")
                    any_fixed = True
                    if record_step_snapshots:
                        step_mismatched = {nid for nid, n in live_nodes.items() if n.digest != baseline_map[nid].digest}
                        step_snapshots.append((node.node_id, step_mismatched))
                    if live_matched == len(baseline_map):
                        all_done = True
                        break
                else:
                    nodes_with_no_correction += 1

                if budget_exhausted:
                    all_done = True
                    break

            if all_done or not any_fixed:
                break  # no progress at this level — advance to next flip depth

        if all_done:
            break

    mismatched_after = {nid for nid, n in live_nodes.items() if n.digest != baseline_map[nid].digest}
    _timer.__exit__(None, None, None)

    rows, cols = len(baseline_grid), len(baseline_grid[0]) if baseline_grid else 0
    grid_hd_before = sum(
        baseline_grid[r][c] != current_grid[r][c]
        for r in range(rows) for c in range(cols)
    )
    grid_hd_after = sum(
        baseline_grid[r][c] != working_grid[r][c]
        for r in range(rows) for c in range(cols)
    )

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
        grid_hd_before=grid_hd_before,
        grid_hd_after=grid_hd_after,
    )