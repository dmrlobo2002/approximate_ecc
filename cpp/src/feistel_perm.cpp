#include "feistel_perm.hpp"
#include "picosha2.h"
#include <cmath>
#include <stdexcept>
#include <algorithm>

// Build SHA-256 payload: key || round_idx(4 bytes BE) || right(8 bytes BE)
static uint64_t round_function(uint64_t right, int round_idx,
                               const std::vector<uint8_t>& key, int out_bits) {
    std::vector<uint8_t> payload;
    payload.reserve(key.size() + 12);
    payload.insert(payload.end(), key.begin(), key.end());

    // round_idx as 4-byte big-endian
    payload.push_back((round_idx >> 24) & 0xFF);
    payload.push_back((round_idx >> 16) & 0xFF);
    payload.push_back((round_idx >>  8) & 0xFF);
    payload.push_back( round_idx        & 0xFF);

    // right as 8-byte big-endian
    payload.push_back((right >> 56) & 0xFF);
    payload.push_back((right >> 48) & 0xFF);
    payload.push_back((right >> 40) & 0xFF);
    payload.push_back((right >> 32) & 0xFF);
    payload.push_back((right >> 24) & 0xFF);
    payload.push_back((right >> 16) & 0xFF);
    payload.push_back((right >>  8) & 0xFF);
    payload.push_back( right        & 0xFF);

    std::vector<uint8_t> hash(picosha2::k_digest_size);
    picosha2::hash256(payload.begin(), payload.end(), hash.begin(), hash.end());

    // Python: int.from_bytes(digest, "big") & mask
    // The low bits of the 256-bit big-endian integer are the LAST bytes.
    // Use the last 8 bytes so we cover out_bits up to 64.
    uint64_t raw = 0;
    for (int i = 24; i < 32; i++) raw = (raw << 8) | hash[i];

    uint64_t mask = (out_bits >= 64) ? ~0ULL : ((1ULL << out_bits) - 1);
    return raw & mask;
}

static uint64_t feistel_forward(uint64_t block, int k_bits,
                                const std::vector<uint8_t>& key, int rounds) {
    int half = k_bits / 2;
    uint64_t mask = (half >= 64) ? ~0ULL : ((1ULL << half) - 1);
    uint64_t left  = (block >> half) & mask;
    uint64_t right =  block          & mask;

    for (int r = 0; r < rounds; r++) {
        uint64_t f = round_function(right, r, key, half);
        uint64_t new_left  = right;
        uint64_t new_right = (left ^ f) & mask;
        left  = new_left  & mask;
        right = new_right;
    }
    return (left << half) | right;
}

static uint64_t feistel_inverse(uint64_t block, int k_bits,
                                const std::vector<uint8_t>& key, int rounds) {
    int half = k_bits / 2;
    uint64_t mask = (half >= 64) ? ~0ULL : ((1ULL << half) - 1);
    uint64_t left  = (block >> half) & mask;
    uint64_t right =  block          & mask;

    for (int r = rounds - 1; r >= 0; r--) {
        uint64_t prev_right = left;
        uint64_t f = round_function(prev_right, r, key, half);
        uint64_t prev_left = (right ^ f) & mask;
        left  = prev_left;
        right = prev_right;
    }
    return (left << half) | right;
}

// ceil(log2(n)) for n >= 2; 0 for n <= 1
static int ceil_log2(int n) {
    if (n <= 1) return 0;
    int k = 0, v = n - 1;
    while (v > 0) { k++; v >>= 1; }
    return k;
}

static int compute_k_bits(int domain_size) {
    int k = std::max(2, ceil_log2(domain_size));
    if (k % 2 == 1) k++;
    return k;
}

int permute_index(int index, int domain_size, const std::vector<uint8_t>& key, int rounds) {
    if (index < 0 || index >= domain_size)
        throw std::invalid_argument("index out of domain");
    if (domain_size <= 1) return 0;
    if (rounds <= 0) throw std::invalid_argument("rounds must be positive");

    int k_bits = compute_k_bits(domain_size);
    uint64_t value = (uint64_t)index;
    while (true) {
        value = feistel_forward(value, k_bits, key, rounds);
        if ((int)value < domain_size) return (int)value;
    }
}

int invert_index(int index, int domain_size, const std::vector<uint8_t>& key, int rounds) {
    if (index < 0 || index >= domain_size)
        throw std::invalid_argument("index out of domain");
    if (domain_size <= 1) return 0;
    if (rounds <= 0) throw std::invalid_argument("rounds must be positive");

    int k_bits = compute_k_bits(domain_size);
    uint64_t value = (uint64_t)index;
    while (true) {
        value = feistel_inverse(value, k_bits, key, rounds);
        if ((int)value < domain_size) return (int)value;
    }
}
