#include "grid_shuffle.hpp"
#include "feistel_perm.hpp"
#include <cmath>
#include <stdexcept>

std::vector<std::vector<int>> bits_to_grid(
    const std::vector<int>& bits,
    const std::vector<uint8_t>& key,
    int rounds,
    GridMeta& out_meta
) {
    int length = (int)bits.size();
    if (length == 0) throw std::invalid_argument("input bits cannot be empty");

    int n = (int)std::ceil(std::sqrt((double)length));
    int m = n * n;

    std::vector<int> padded = bits;
    padded.resize(m, 0);

    std::vector<int> grid_linear(m, 0);
    std::vector<int> source_to_grid(m, -1);
    std::vector<int> grid_to_source(m, -1);

    for (int src_idx = 0; src_idx < m; src_idx++) {
        int dst_idx = (rounds == 0) ? src_idx
                                    : permute_index(src_idx, m, key, rounds);
        grid_linear[dst_idx] = padded[src_idx];
        source_to_grid[src_idx] = dst_idx;
        grid_to_source[dst_idx] = src_idx;
    }

    std::vector<std::vector<int>> grid(n, std::vector<int>(n));
    for (int r = 0; r < n; r++)
        for (int c = 0; c < n; c++)
            grid[r][c] = grid_linear[r * n + c];

    out_meta = GridMeta{length, n, m, rounds,
                        std::move(source_to_grid),
                        std::move(grid_to_source)};
    return grid;
}

std::vector<int> grid_to_bits(
    const std::vector<std::vector<int>>& grid,
    const GridMeta& meta,
    const std::vector<uint8_t>& key
) {
    if ((int)grid.size() != meta.n)
        throw std::invalid_argument("grid shape does not match metadata");

    std::vector<int> grid_linear;
    grid_linear.reserve(meta.m);
    for (const auto& row : grid)
        for (int bit : row)
            grid_linear.push_back(bit);

    std::vector<int> restored(meta.m, 0);
    for (int dst_idx = 0; dst_idx < meta.m; dst_idx++) {
        int src_idx = (meta.rounds == 0)
                        ? dst_idx
                        : invert_index(dst_idx, meta.m, key, meta.rounds);
        restored[src_idx] = grid_linear[dst_idx];
    }
    return std::vector<int>(restored.begin(), restored.begin() + meta.original_length);
}

std::pair<int, int> source_index_to_grid_coord(int source_idx, const GridMeta& meta) {
    int dst = meta.source_to_grid[source_idx];
    return {dst / meta.n, dst % meta.n};
}
