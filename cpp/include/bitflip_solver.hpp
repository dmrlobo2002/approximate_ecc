#pragma once
#include "group_hash.hpp"
#include "hash_dag.hpp"
#include <string>
#include <vector>
#include <unordered_set>

struct SolveResult {
    std::vector<std::vector<int>> corrected_grid;
    std::vector<std::string> mismatched_before;
    std::vector<std::string> mismatched_after;
    std::vector<std::string> steps;
    // step_snapshots omitted for now (debugging-only field)
    int total_combos_evaluated = 0;
    int total_nodes_visited = 0;
    int max_flip_level_reached = 0;
    int nodes_with_no_correction = 0;
    double solve_time_seconds = 0.0;
};

SolveResult correct_with_dag(
    const std::vector<std::vector<int>>& baseline_grid,
    const std::vector<std::vector<int>>& current_grid,
    const GridMeta& meta,
    int row_group_size,
    int col_group_size,
    int hash_bits,
    const std::string& tail_policy = "include_partial",
    bool record_step_snapshots = false,
    int max_combos = -1,    // -1 = no limit
    const std::unordered_set<int>& globally_pinned = {}
);
