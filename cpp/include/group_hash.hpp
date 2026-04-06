#pragma once
#include "grid_shuffle.hpp"
#include <string>
#include <vector>
#include <unordered_map>

struct HashNode {
    std::string node_id;
    std::string axis;  // "row" | "col"
    int group_index;
    int hash_bits;
    uint32_t digest;
    std::vector<int> source_indices;  // sorted

    int covered_bits() const { return (int)source_indices.size(); }
};

struct GroupHashContext {
    GridMeta meta;
    int row_group_size;
    int col_group_size;
    int hash_bits;
    std::string tail_policy;
    std::vector<std::pair<int, int>> row_groups;
    std::vector<std::pair<int, int>> col_groups;
    std::unordered_map<int, std::vector<std::string>> src_to_node_ids;
    std::string hash_type = "crc";
};

struct BlockHashResult {
    int block_index;
    uint32_t digest;
    std::vector<int> source_indices;
};

std::vector<HashNode> build_hash_nodes(
    const std::vector<std::vector<int>>& grid,
    const GridMeta& meta,
    int row_group_size,
    int col_group_size,
    int hash_bits,
    const std::string& tail_policy = "include_partial",
    const std::string& hash_type = "crc"
);

HashNode recompute_node(
    const HashNode& old_node,
    const std::vector<std::vector<int>>& grid,
    const GroupHashContext& ctx
);

GroupHashContext build_group_context(
    const GridMeta& meta,
    int row_group_size,
    int col_group_size,
    int hash_bits,
    const std::string& tail_policy = "include_partial",
    const std::string& hash_type = "crc"
);

std::vector<BlockHashResult> compute_block_hashes(
    const std::vector<std::vector<int>>& grid,
    const GridMeta& meta,
    int block_count,
    int hash_bits = 32
);
