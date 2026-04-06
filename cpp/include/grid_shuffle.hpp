#pragma once
#include <vector>
#include <utility>
#include <cstdint>

struct GridMeta {
    int original_length;
    int n;
    int m;
    int rounds;
    std::vector<int> source_to_grid;
    std::vector<int> grid_to_source;
};

std::vector<std::vector<int>> bits_to_grid(
    const std::vector<int>& bits,
    const std::vector<uint8_t>& key,
    int rounds,
    GridMeta& out_meta
);

std::vector<int> grid_to_bits(
    const std::vector<std::vector<int>>& grid,
    const GridMeta& meta,
    const std::vector<uint8_t>& key
);

std::pair<int, int> source_index_to_grid_coord(int source_idx, const GridMeta& meta);
