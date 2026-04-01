"""Bidirectional graph construction across hash nodes by shared input bits."""

from __future__ import annotations

from dataclasses import dataclass

from group_hash import HashNode


@dataclass(frozen=True)
class GraphEdge:
    src: str
    dst: str
    weight: int


@dataclass
class HashGraph:
    nodes: dict[str, HashNode]
    edges: list[GraphEdge]
    adj: dict[str, list[GraphEdge]]


def build_hash_graph(nodes: list[HashNode]) -> HashGraph:
    node_map = {node.node_id: node for node in nodes}
    edges: list[GraphEdge] = []
    adj: dict[str, list[GraphEdge]] = {node.node_id: [] for node in nodes}

    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            left = nodes[i]
            right = nodes[j]
            overlap = len(left.source_indices.intersection(right.source_indices))
            if overlap <= 0:
                continue
            edge = GraphEdge(src=left.node_id, dst=right.node_id, weight=overlap)
            edges.append(edge)
            adj[left.node_id].append(edge)
            adj[right.node_id].append(edge)

    return HashGraph(nodes=node_map, edges=edges, adj=adj)
