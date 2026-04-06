#include "group_hash.hpp"
#include <algorithm>
#include <stdexcept>
#include <cmath>
#include <array>
#include <numeric>

// ---- CRC helpers -------------------------------------------------------

static uint8_t crc8(const std::vector<uint8_t>& data,
                    uint8_t poly = 0x07, uint8_t init = 0x00, uint8_t xor_out = 0x00) {
    uint8_t crc = init;
    for (uint8_t byte : data) {
        crc ^= byte;
        for (int i = 0; i < 8; i++) {
            crc = (crc & 0x80) ? (uint8_t)(((crc << 1) ^ poly) & 0xFF)
                               : (uint8_t)((crc << 1) & 0xFF);
        }
    }
    return crc ^ xor_out;
}

static std::array<uint16_t, 256> make_crc16_table(uint16_t poly = 0x1021) {
    std::array<uint16_t, 256> table;
    for (int b = 0; b < 256; b++) {
        uint16_t crc = (uint16_t)(b << 8);
        for (int i = 0; i < 8; i++) {
            crc = (crc & 0x8000) ? (uint16_t)(((crc << 1) ^ poly) & 0xFFFF)
                                 : (uint16_t)((crc << 1) & 0xFFFF);
        }
        table[b] = crc;
    }
    return table;
}

static const auto CRC16_TABLE = make_crc16_table();

static uint16_t crc16(const std::vector<uint8_t>& data,
                      uint16_t init = 0xFFFF, uint16_t xor_out = 0x0000) {
    uint16_t crc = init;
    for (uint8_t byte : data) {
        crc = (uint16_t)(((crc << 8) ^ CRC16_TABLE[(crc >> 8) ^ byte]) & 0xFFFF);
    }
    return crc ^ xor_out;
}

// Standard CRC-32/ISO-HDLC (matches Python binascii.crc32)
static uint32_t crc32_compute(const std::vector<uint8_t>& data) {
    static const auto make_table = []() {
        std::array<uint32_t, 256> t;
        for (uint32_t i = 0; i < 256; i++) {
            uint32_t crc = i;
            for (int j = 0; j < 8; j++)
                crc = (crc & 1) ? (0xEDB88320u ^ (crc >> 1)) : (crc >> 1);
            t[i] = crc;
        }
        return t;
    };
    static const auto TABLE = make_table();

    uint32_t crc = 0xFFFFFFFFu;
    for (uint8_t byte : data)
        crc = TABLE[(crc ^ byte) & 0xFF] ^ (crc >> 8);
    return (crc ^ 0xFFFFFFFFu) & 0xFFFFFFFFu;
}

static std::vector<uint8_t> pack_bits_to_bytes(const std::vector<int>& bits) {
    std::vector<uint8_t> out;
    uint8_t byte = 0;
    for (int i = 0; i < (int)bits.size(); i++) {
        byte = (uint8_t)((byte << 1) | (uint8_t)bits[i]);
        if ((i + 1) % 8 == 0) { out.push_back(byte); byte = 0; }
    }
    int rem = (int)bits.size() % 8;
    if (rem) { out.push_back((uint8_t)(byte << (8 - rem))); }
    return out;
}

static uint32_t crc_hash(const std::vector<int>& bits, int hash_bits) {
    auto data = pack_bits_to_bytes(bits);
    if (hash_bits ==  8) return crc8(data);
    if (hash_bits == 16) return crc16(data);
    if (hash_bits == 32) return crc32_compute(data);
    throw std::invalid_argument("hash_bits must be 8, 16, or 32");
}

static std::vector<std::pair<int,int>> iter_groups(
    int length, int group_size, const std::string& tail_policy)
{
    if (group_size <= 0) throw std::invalid_argument("group_size must be positive");
    std::vector<std::pair<int,int>> groups;
    for (int start = 0; start < length; start += group_size) {
        int end  = std::min(start + group_size, length);
        int size = end - start;
        if (size < group_size && tail_policy == "drop_partial") break;
        groups.emplace_back(start, end);
    }
    return groups;
}

// ---- SimHash helpers ---------------------------------------------------

static uint32_t node_seed(const std::string& node_id) {
    uint32_t h = 2166136261u;
    for (unsigned char c : node_id) { h ^= c; h *= 16777619u; }
    return h;
}

static uint32_t lcg_next(uint32_t s) {
    return 1664525u * s + 1013904223u;
}

static uint32_t simhash(const std::vector<int>& bits, int hash_bits, const std::string& node_id) {
    int n = (int)bits.size();
    if (n == 0) return 0;

    // GF(2) random linear hash: each output bit is the XOR of a random subset of input bits.
    // Every input bit contributes to every output bit with probability 0.5, so a single flip
    // changes each output bit independently with probability 0.5. This gives:
    //   - detection probability: 1 - 2^(-hash_bits)  (same as CRC)
    //   - false positive probability: 2^(-hash_bits) for any nonzero error pattern  (same as CRC)
    // Unlike hyperplane SimHash, the false positive rate does NOT increase for nearby vectors.
    uint32_t seed = node_seed(node_id);
    uint32_t result = 0;

    for (int j = 0; j < n; j++) {
        int b = bits[j];
        seed = lcg_next(seed);
        uint32_t mask = seed;
        // Each bit of mask selects whether this input bit XORs into the corresponding output bit.
        // Re-mix if hash_bits > 32.
        for (int i = 0; i < hash_bits && i < 32; i++) {
            if (i > 0 && i % 32 == 0) mask = lcg_next(mask);
            if ((mask >> (i % 32)) & 1u)
                result ^= (uint32_t)b << i;
        }
    }
    // Keep only hash_bits output bits.
    if (hash_bits < 32)
        result &= (1u << hash_bits) - 1u;
    return result;
}

static uint32_t compute_hash(const std::vector<int>& bits, int hash_bits,
                              const std::string& node_id, const std::string& hash_type) {
    if (hash_type == "simhash") return simhash(bits, hash_bits, node_id);
    return crc_hash(bits, hash_bits);
}

// ---- Public API --------------------------------------------------------

std::vector<HashNode> build_hash_nodes(
    const std::vector<std::vector<int>>& grid,
    const GridMeta& meta,
    int row_group_size,
    int col_group_size,
    int hash_bits,
    const std::string& tail_policy,
    const std::string& hash_type
) {
    int n = meta.n;
    std::vector<HashNode> nodes;

    // Row groups
    auto row_groups = iter_groups(n, row_group_size, tail_policy);
    for (int gi = 0; gi < (int)row_groups.size(); gi++) {
        auto [r0, r1] = row_groups[gi];
        std::vector<int> bits;
        std::vector<int> src_idx_vec;

        for (int r = r0; r < r1; r++) {
            for (int c = 0; c < n; c++) {
                bits.push_back(grid[r][c]);
                int si = meta.grid_to_source[r * n + c];
                if (si < meta.original_length) src_idx_vec.push_back(si);
            }
        }
        if (tail_policy == "pad_with_zeros" && (r1 - r0) < row_group_size) {
            int pad = (row_group_size - (r1 - r0)) * n;
            bits.insert(bits.end(), pad, 0);
        }

        std::sort(src_idx_vec.begin(), src_idx_vec.end());
        src_idx_vec.erase(std::unique(src_idx_vec.begin(), src_idx_vec.end()), src_idx_vec.end());

        std::string nid = "row_" + std::to_string(gi);
        nodes.push_back(HashNode{
            nid, "row", gi, hash_bits,
            compute_hash(bits, hash_bits, nid, hash_type), std::move(src_idx_vec)
        });
    }

    // Column groups
    auto col_groups = iter_groups(n, col_group_size, tail_policy);
    for (int gi = 0; gi < (int)col_groups.size(); gi++) {
        auto [c0, c1] = col_groups[gi];
        std::vector<int> bits;
        std::vector<int> src_idx_vec;

        for (int c = c0; c < c1; c++) {
            for (int r = 0; r < n; r++) {
                bits.push_back(grid[r][c]);
                int si = meta.grid_to_source[r * n + c];
                if (si < meta.original_length) src_idx_vec.push_back(si);
            }
        }
        if (tail_policy == "pad_with_zeros" && (c1 - c0) < col_group_size) {
            int pad = (col_group_size - (c1 - c0)) * n;
            bits.insert(bits.end(), pad, 0);
        }

        std::sort(src_idx_vec.begin(), src_idx_vec.end());
        src_idx_vec.erase(std::unique(src_idx_vec.begin(), src_idx_vec.end()), src_idx_vec.end());

        std::string nid = "col_" + std::to_string(gi);
        nodes.push_back(HashNode{
            nid, "col", gi, hash_bits,
            compute_hash(bits, hash_bits, nid, hash_type), std::move(src_idx_vec)
        });
    }

    return nodes;
}

HashNode recompute_node(
    const HashNode& old_node,
    const std::vector<std::vector<int>>& grid,
    const GroupHashContext& ctx
) {
    int n = ctx.meta.n;
    std::vector<int> bits;

    if (old_node.axis == "row") {
        auto [r0, r1] = ctx.row_groups[old_node.group_index];
        for (int r = r0; r < r1; r++)
            for (int c = 0; c < n; c++)
                bits.push_back(grid[r][c]);
        if (ctx.tail_policy == "pad_with_zeros" && (r1 - r0) < ctx.row_group_size) {
            int pad = (ctx.row_group_size - (r1 - r0)) * n;
            bits.insert(bits.end(), pad, 0);
        }
    } else {
        auto [c0, c1] = ctx.col_groups[old_node.group_index];
        for (int c = c0; c < c1; c++)
            for (int r = 0; r < n; r++)
                bits.push_back(grid[r][c]);
        if (ctx.tail_policy == "pad_with_zeros" && (c1 - c0) < ctx.col_group_size) {
            int pad = (ctx.col_group_size - (c1 - c0)) * n;
            bits.insert(bits.end(), pad, 0);
        }
    }

    HashNode result = old_node;
    result.digest = compute_hash(bits, ctx.hash_bits, old_node.node_id, ctx.hash_type);
    return result;
}

GroupHashContext build_group_context(
    const GridMeta& meta,
    int row_group_size,
    int col_group_size,
    int hash_bits,
    const std::string& tail_policy,
    const std::string& hash_type
) {
    auto row_groups = iter_groups(meta.n, row_group_size, tail_policy);
    auto col_groups = iter_groups(meta.n, col_group_size, tail_policy);

    std::unordered_map<int, std::vector<std::string>> src_to_node_ids;
    for (int si = 0; si < meta.original_length; si++) {
        int linear = meta.source_to_grid[si];
        int r = linear / meta.n;
        int c = linear % meta.n;

        std::vector<std::string> nids;
        int row_gidx = r / row_group_size;
        int col_gidx = c / col_group_size;
        if (row_gidx < (int)row_groups.size())
            nids.push_back("row_" + std::to_string(row_gidx));
        if (col_gidx < (int)col_groups.size())
            nids.push_back("col_" + std::to_string(col_gidx));
        src_to_node_ids[si] = std::move(nids);
    }

    return GroupHashContext{meta, row_group_size, col_group_size, hash_bits, tail_policy,
                            row_groups, col_groups, std::move(src_to_node_ids), hash_type};
}

std::vector<BlockHashResult> compute_block_hashes(
    const std::vector<std::vector<int>>& grid,
    const GridMeta& meta,
    int block_count,
    int hash_bits
) {
    int n = meta.n;
    int rows_per_block = (int)std::ceil((double)n / block_count);
    std::vector<BlockHashResult> results;

    for (int b = 0; b < block_count; b++) {
        int r0 = b * rows_per_block;
        int r1 = std::min(r0 + rows_per_block, n);
        std::vector<int> bits;
        std::vector<int> src_vec;

        for (int r = r0; r < r1; r++) {
            for (int c = 0; c < n; c++) {
                bits.push_back(grid[r][c]);
                int si = meta.grid_to_source[r * n + c];
                if (si < meta.original_length) src_vec.push_back(si);
            }
        }
        std::sort(src_vec.begin(), src_vec.end());
        src_vec.erase(std::unique(src_vec.begin(), src_vec.end()), src_vec.end());
        results.push_back(BlockHashResult{b, crc_hash(bits, hash_bits), std::move(src_vec)});
    }
    return results;
}
