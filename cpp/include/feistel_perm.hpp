#pragma once
#include <vector>
#include <cstdint>

int permute_index(int index, int domain_size, const std::vector<uint8_t>& key, int rounds = 8);
int invert_index(int index, int domain_size, const std::vector<uint8_t>& key, int rounds = 8);
