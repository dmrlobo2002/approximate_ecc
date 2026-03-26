from bitflip_solver import correct_with_dag
from grid_shuffle import bits_to_grid, grid_to_bits
from group_hash import build_hash_nodes
from hash_dag import build_hash_dag


def test_round_trip_bits():
    key = b"k1"
    bits = [1 if i % 3 == 0 else 0 for i in range(53)]
    grid, meta = bits_to_grid(bits, key=key, rounds=8)
    restored = grid_to_bits(grid, meta, key=key)
    assert restored == bits


def test_hash_dag_has_weighted_overlaps():
    key = b"k2"
    bits = [i % 2 for i in range(49)]
    grid, meta = bits_to_grid(bits, key=key, rounds=8)
    nodes = build_hash_nodes(grid, meta, row_group_size=2, col_group_size=3, hash_bits=16)
    dag = build_hash_dag(nodes)
    assert len(dag.nodes) == len(nodes)
    assert all(edge.weight > 0 for edge in dag.edges)


def test_solver_reduces_mismatches():
    key = b"k3"
    bits = [1 if i % 5 in (0, 1) else 0 for i in range(36)]
    baseline_grid, meta = bits_to_grid(bits, key=key, rounds=8)
    damaged = [row[:] for row in baseline_grid]
    damaged[0][0] ^= 1
    damaged[0][1] ^= 1

    baseline_nodes = build_hash_nodes(baseline_grid, meta, row_group_size=2, col_group_size=2, hash_bits=16)
    damaged_nodes = build_hash_nodes(damaged, meta, row_group_size=2, col_group_size=2, hash_bits=16)
    mismatched_before = sum(1 for a, b in zip(baseline_nodes, damaged_nodes) if a.digest != b.digest)

    result = correct_with_dag(
        baseline_grid=baseline_grid,
        current_grid=damaged,
        meta=meta,
        row_group_size=2,
        col_group_size=2,
        hash_bits=16,
    )
    corrected_nodes = build_hash_nodes(result.corrected_grid, meta, row_group_size=2, col_group_size=2, hash_bits=16)
    mismatched_after = sum(1 for a, b in zip(baseline_nodes, corrected_nodes) if a.digest != b.digest)

    assert mismatched_after <= mismatched_before

