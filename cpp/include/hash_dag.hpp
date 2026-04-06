#pragma once
#include "group_hash.hpp"
#include <string>
#include <vector>
#include <unordered_map>

struct GraphEdge {
    std::string src;
    std::string dst;
    int weight;
};

struct HashGraph {
    std::unordered_map<std::string, HashNode> nodes;
    std::vector<GraphEdge> edges;
    std::unordered_map<std::string, std::vector<GraphEdge>> adj;
};

HashGraph build_hash_graph(const std::vector<HashNode>& nodes);
