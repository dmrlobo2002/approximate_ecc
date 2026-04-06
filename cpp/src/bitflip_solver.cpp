#include "bitflip_solver.hpp"
#include <algorithm>
#include <chrono>
#include <unordered_set>
#include <set>
#include <numeric>
#include <functional>

// ---- Helpers -----------------------------------------------------------

static int hamming_distance(uint32_t a, uint32_t b) {
    return __builtin_popcount(a ^ b);
}

// ---- Combination enumeration -------------------------------------------

// Calls callback(combo) for each size-k combination from pool.
// callback returns false to stop early.
static bool enumerate_combinations(
    const std::vector<int>& pool,
    int k,
    const std::function<bool(const std::vector<int>&)>& callback)
{
    int n = (int)pool.size();
    if (k < 0 || k > n) return true;
    if (k == 0) { return callback({}); }

    std::vector<int> indices(k);
    std::iota(indices.begin(), indices.end(), 0);  // 0,1,...,k-1

    std::vector<int> combo(k);
    while (true) {
        for (int i = 0; i < k; i++) combo[i] = pool[indices[i]];
        if (!callback(combo)) return false;

        // Advance to next combination (lexicographic)
        int i = k - 1;
        while (i >= 0 && indices[i] == n - k + i) i--;
        if (i < 0) break;
        indices[i]++;
        for (int j = i + 1; j < k; j++) indices[j] = indices[j - 1] + 1;
    }
    return true;
}

// ---- Inner loop helpers ------------------------------------------------

static void get_affected_ids(
    const std::vector<int>& combo,
    const GroupHashContext& ctx,
    std::vector<std::string>& affected_ids)
{
    affected_ids.clear();
    std::unordered_set<std::string> seen;
    for (int si : combo) {
        auto it = ctx.src_to_node_ids.find(si);
        if (it == ctx.src_to_node_ids.end()) continue;
        for (const auto& nid : it->second) {
            if (seen.insert(nid).second)
                affected_ids.push_back(nid);
        }
    }
}

// Apply combo, score it, then restore. Returns (score, did_fix_target).
// score == -1 if target was not fixed.
static std::pair<int, bool> apply_combo_and_score(
    const std::vector<int>& combo,
    const std::string& target_node_id,
    std::vector<std::vector<int>>& working_grid,
    std::unordered_map<std::string, HashNode>& live_nodes,
    int live_matched,
    const std::unordered_map<std::string, HashNode>& baseline_map,
    const GroupHashContext& ctx)
{
    std::vector<std::string> affected_ids;
    get_affected_ids(combo, ctx, affected_ids);

    // Save old nodes
    std::vector<std::pair<std::string, HashNode>> saved;
    saved.reserve(affected_ids.size());
    for (const auto& nid : affected_ids)
        saved.emplace_back(nid, live_nodes.at(nid));

    // Apply flips
    int n = ctx.meta.n;
    for (int si : combo) {
        int linear = ctx.meta.source_to_grid[si];
        int r = linear / n, c = linear % n;
        working_grid[r][c] ^= 1;
    }

    // Recompute affected nodes
    for (const auto& nid : affected_ids)
        live_nodes[nid] = recompute_node(live_nodes[nid], working_grid, ctx);

    // Check if target is fixed
    bool fixed = (live_nodes.at(target_node_id).digest ==
                  baseline_map.at(target_node_id).digest);

    if (!fixed) {
        // Restore nodes
        for (const auto& [nid, old_node] : saved) live_nodes[nid] = old_node;
        // Restore grid
        for (int si : combo) {
            int linear = ctx.meta.source_to_grid[si];
            int r = linear / n, c = linear % n;
            working_grid[r][c] ^= 1;
        }
        return {-1, false};
    }

    // Score delta
    int delta = 0;
    for (const auto& [nid, old_node] : saved) {
        bool was = (old_node.digest == baseline_map.at(nid).digest);
        bool now = (live_nodes.at(nid).digest == baseline_map.at(nid).digest);
        delta += (int)now - (int)was;
    }

    // Restore nodes and grid
    for (const auto& [nid, old_node] : saved) live_nodes[nid] = old_node;
    for (int si : combo) {
        int linear = ctx.meta.source_to_grid[si];
        int r = linear / n, c = linear % n;
        working_grid[r][c] ^= 1;
    }

    return {live_matched + delta, true};
}

// Commit a combo permanently.
static int commit_combo(
    const std::vector<int>& combo,
    std::vector<std::vector<int>>& working_grid,
    std::unordered_map<std::string, HashNode>& live_nodes,
    int live_matched,
    const std::unordered_map<std::string, HashNode>& baseline_map,
    const GroupHashContext& ctx)
{
    std::vector<std::string> affected_ids;
    get_affected_ids(combo, ctx, affected_ids);

    int n = ctx.meta.n;
    for (int si : combo) {
        int linear = ctx.meta.source_to_grid[si];
        int r = linear / n, c = linear % n;
        working_grid[r][c] ^= 1;
    }
    for (const auto& nid : affected_ids) {
        bool was = (live_nodes.at(nid).digest == baseline_map.at(nid).digest);
        live_nodes[nid] = recompute_node(live_nodes[nid], working_grid, ctx);
        bool now = (live_nodes.at(nid).digest == baseline_map.at(nid).digest);
        live_matched += (int)now - (int)was;
    }
    return live_matched;
}

// ---- Main solver -------------------------------------------------------

SolveResult correct_with_dag(
    const std::vector<std::vector<int>>& baseline_grid,
    const std::vector<std::vector<int>>& current_grid,
    const GridMeta& meta,
    int row_group_size,
    int col_group_size,
    int hash_bits,
    const std::string& tail_policy,
    bool /*record_step_snapshots*/,
    int max_combos,
    const std::unordered_set<int>& globally_pinned,
    const std::string& hash_type)
{
    auto t_start = std::chrono::steady_clock::now();

    // Build hash nodes
    auto baseline_nodes = build_hash_nodes(
        baseline_grid, meta, row_group_size, col_group_size, hash_bits, tail_policy, hash_type);
    auto current_nodes = build_hash_nodes(
        current_grid, meta, row_group_size, col_group_size, hash_bits, tail_policy, hash_type);

    HashGraph dag = build_hash_graph(baseline_nodes);

    // baseline_map
    std::unordered_map<std::string, HashNode> baseline_map;
    baseline_map.reserve(baseline_nodes.size());
    for (const auto& n : baseline_nodes) baseline_map[n.node_id] = n;

    // mismatched_before
    std::vector<std::string> mismatched_before;
    for (const auto& n : current_nodes)
        if (baseline_map.at(n.node_id).digest != n.digest)
            mismatched_before.push_back(n.node_id);

    // Working state
    auto working_grid = current_grid;  // copy

    std::unordered_map<std::string, HashNode> live_nodes;
    live_nodes.reserve(current_nodes.size());
    for (const auto& n : current_nodes) live_nodes[n.node_id] = n;

    int live_matched = 0;
    for (const auto& [nid, n] : live_nodes)
        if (baseline_map.at(nid).digest == n.digest) live_matched++;

    GroupHashContext ctx = build_group_context(
        meta, row_group_size, col_group_size, hash_bits, tail_policy, hash_type);

    // Compute per-node flip count from baseline vs current grid
    auto count_node_flips = [&](const HashNode& node) -> int {
        int n = meta.n;
        int count = 0;
        if (node.axis == "row") {
            auto [r0, r1] = ctx.row_groups[node.group_index];
            for (int r = r0; r < r1; r++)
                for (int c = 0; c < n; c++)
                    if (baseline_grid[r][c] != current_grid[r][c]) count++;
        } else {
            auto [c0, c1] = ctx.col_groups[node.group_index];
            for (int r = 0; r < n; r++)
                for (int c = c0; c < c1; c++)
                    if (baseline_grid[r][c] != current_grid[r][c]) count++;
        }
        return count;
    };

    // Sort nodes: fewest damage score first, then covered_bits, then node_id
    std::vector<HashNode> ordered_nodes;
    ordered_nodes.reserve(dag.nodes.size());
    for (const auto& [_, n] : dag.nodes) ordered_nodes.push_back(n);
    std::unordered_map<std::string, int> scores;
    scores.reserve(ordered_nodes.size());
    if (hash_type == "simhash") {
        // Deployment-safe: popcount of XOR digest estimates flip density
        std::unordered_map<std::string, HashNode> cur_map;
        for (const auto& n : current_nodes) cur_map[n.node_id] = n;
        for (const auto& node : ordered_nodes)
            scores[node.node_id] = hamming_distance(
                baseline_map.at(node.node_id).digest, cur_map.at(node.node_id).digest);
    } else {
        for (const auto& node : ordered_nodes)
            scores[node.node_id] = count_node_flips(node);
    }
    std::sort(ordered_nodes.begin(), ordered_nodes.end(),
              [&](const HashNode& a, const HashNode& b) {
                  int fa = scores[a.node_id], fb = scores[b.node_id];
                  if (fa != fb) return fa < fb;
                  if (a.covered_bits() != b.covered_bits())
                      return a.covered_bits() < b.covered_bits();
                  return a.node_id < b.node_id;
              });

    std::vector<std::string> steps;
    int total_combos_evaluated  = 0;
    int total_nodes_visited     = 0;
    int max_flip_level_reached  = 0;
    int nodes_with_no_correction = 0;

    for (const auto& node : ordered_nodes) {
        if (live_nodes.at(node.node_id).digest == baseline_map.at(node.node_id).digest)
            continue;

        total_nodes_visited++;

        // Collect neighbor bits
        std::unordered_set<int> good_neighbor_bits;
        std::unordered_set<int> mismatched_neighbor_bits;

        for (const auto& edge : dag.adj.at(node.node_id)) {
            const std::string& nbr_id = (edge.src == node.node_id) ? edge.dst : edge.src;
            const auto& nbr_bits = dag.nodes.at(nbr_id).source_indices;
            if (live_nodes.at(nbr_id).digest == baseline_map.at(nbr_id).digest) {
                good_neighbor_bits.insert(nbr_bits.begin(), nbr_bits.end());
            } else {
                mismatched_neighbor_bits.insert(nbr_bits.begin(), nbr_bits.end());
            }
        }

        // free_indices = node.source_indices - good_neighbor_bits - globally_pinned
        std::vector<int> free_indices;
        for (int si : node.source_indices)
            if (!good_neighbor_bits.count(si) && !globally_pinned.count(si))
                free_indices.push_back(si);

        // intersection_indices = free_indices ∩ mismatched_neighbor_bits
        std::vector<int> intersection_indices;
        for (int si : free_indices)
            if (mismatched_neighbor_bits.count(si))
                intersection_indices.push_back(si);

        const std::vector<int>& src_indices = node.source_indices;

        // Build search passes (match Python logic)
        std::vector<const std::vector<int>*> passes;
        if (!intersection_indices.empty() && intersection_indices != free_indices)
            passes.push_back(&intersection_indices);
        passes.push_back(&free_indices);
        if (free_indices != src_indices)
            passes.push_back(&src_indices);

        std::vector<int> best_combo;
        int best_match    = -1;
        int best_flip_cnt = -1;
        bool budget_exhausted = false;

        for (const auto* cand_ptr : passes) {
            const auto& cand = *cand_ptr;

            for (int flips = 0; flips <= (int)cand.size(); flips++) {
                bool found_for_level = false;

                bool stop = !enumerate_combinations(cand, flips,
                    [&](const std::vector<int>& combo) -> bool {
                        total_combos_evaluated++;
                        if (max_combos >= 0 && total_combos_evaluated > max_combos) {
                            budget_exhausted = true;
                            return false;  // stop enumeration
                        }
                        auto [score, fixed] = apply_combo_and_score(
                            combo, node.node_id, working_grid,
                            live_nodes, live_matched, baseline_map, ctx);
                        if (!fixed) return true;

                        found_for_level = true;
                        if (score > best_match ||
                            (score == best_match && (best_flip_cnt < 0 || flips < best_flip_cnt)))
                        {
                            best_match    = score;
                            best_combo    = combo;
                            best_flip_cnt = flips;
                        }
                        return true;
                    });

                if (budget_exhausted) break;
                if (found_for_level) {
                    if (flips > max_flip_level_reached) max_flip_level_reached = flips;
                    break;  // early exit: found a fix at this flip level
                }
            }
            if (budget_exhausted || !best_combo.empty()) break;
        }

        if (!best_combo.empty()) {
            live_matched = commit_combo(
                best_combo, working_grid, live_nodes, live_matched, baseline_map, ctx);
            steps.push_back("Corrected " + node.node_id +
                            " using " + std::to_string(best_flip_cnt) + " flips.");
            if (live_matched == (int)baseline_map.size()) break;
        } else {
            nodes_with_no_correction++;
            steps.push_back("No correction found for " + node.node_id +
                            " after full enumeration.");
        }
    }

    std::vector<std::string> mismatched_after;
    for (const auto& [nid, n] : live_nodes)
        if (n.digest != baseline_map.at(nid).digest)
            mismatched_after.push_back(nid);

    auto t_end = std::chrono::steady_clock::now();
    double elapsed = std::chrono::duration<double>(t_end - t_start).count();

    int grid_hd_before = 0, grid_hd_after = 0;
    int rows = (int)baseline_grid.size();
    int cols = rows > 0 ? (int)baseline_grid[0].size() : 0;
    for (int r = 0; r < rows; r++)
        for (int c = 0; c < cols; c++) {
            if (baseline_grid[r][c] != current_grid[r][c]) grid_hd_before++;
            if (baseline_grid[r][c] != working_grid[r][c]) grid_hd_after++;
        }

    return SolveResult{
        std::move(working_grid),
        std::move(mismatched_before),
        std::move(mismatched_after),
        std::move(steps),
        total_combos_evaluated,
        total_nodes_visited,
        max_flip_level_reached,
        nodes_with_no_correction,
        elapsed,
        grid_hd_before,
        grid_hd_after
    };
}
