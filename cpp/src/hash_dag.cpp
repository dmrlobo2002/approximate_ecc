#include "hash_dag.hpp"
#include <algorithm>

HashGraph build_hash_graph(const std::vector<HashNode>& nodes) {
    std::unordered_map<std::string, HashNode> node_map;
    std::unordered_map<std::string, std::vector<GraphEdge>> adj;
    std::vector<GraphEdge> edges;

    node_map.reserve(nodes.size());
    adj.reserve(nodes.size());
    for (const auto& node : nodes) {
        node_map[node.node_id] = node;
        adj[node.node_id] = {};
    }

    for (int i = 0; i < (int)nodes.size(); i++) {
        for (int j = i + 1; j < (int)nodes.size(); j++) {
            const auto& a = nodes[i];
            const auto& b = nodes[j];

            // Both source_indices vectors are sorted; use set_intersection
            std::vector<int> isect;
            std::set_intersection(
                a.source_indices.begin(), a.source_indices.end(),
                b.source_indices.begin(), b.source_indices.end(),
                std::back_inserter(isect));

            int overlap = (int)isect.size();
            if (overlap <= 0) continue;

            GraphEdge edge{a.node_id, b.node_id, overlap};
            edges.push_back(edge);
            adj[a.node_id].push_back(edge);
            adj[b.node_id].push_back(edge);
        }
    }

    return HashGraph{std::move(node_map), std::move(edges), std::move(adj)};
}
