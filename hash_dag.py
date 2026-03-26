"""DAG construction across hash nodes by shared input bits."""

from __future__ import annotations

from dataclasses import dataclass

from group_hash import HashNode


@dataclass(frozen=True)
class DagEdge:
    src: str
    dst: str
    weight: int


@dataclass
class HashDag:
    nodes: dict[str, HashNode]
    edges: list[DagEdge]
    out_adj: dict[str, list[DagEdge]]


def build_hash_dag(nodes: list[HashNode]) -> HashDag:
    node_map = {node.node_id: node for node in nodes}
    sorted_nodes = sorted(nodes, key=lambda n: (n.covered_bits, n.node_id))
    edges: list[DagEdge] = []
    out_adj: dict[str, list[DagEdge]] = {node.node_id: [] for node in nodes}

    for i in range(len(sorted_nodes)):
        for j in range(i + 1, len(sorted_nodes)):
            left = sorted_nodes[i]
            right = sorted_nodes[j]
            overlap = len(left.source_indices.intersection(right.source_indices))
            if overlap <= 0:
                continue
            edge = DagEdge(src=left.node_id, dst=right.node_id, weight=overlap)
            edges.append(edge)
            out_adj[left.node_id].append(edge)

    return HashDag(nodes=node_map, edges=edges, out_adj=out_adj)

