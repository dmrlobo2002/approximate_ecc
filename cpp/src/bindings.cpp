#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include "feistel_perm.hpp"
#include "grid_shuffle.hpp"
#include "group_hash.hpp"
#include "hash_dag.hpp"
#include "bitflip_solver.hpp"

namespace py = pybind11;

// Extract C++ GridMeta from a Python GridMeta dataclass object.
static GridMeta extract_meta(py::object meta_obj) {
    GridMeta m;
    m.original_length = meta_obj.attr("original_length").cast<int>();
    m.n               = meta_obj.attr("n").cast<int>();
    m.m               = meta_obj.attr("m").cast<int>();
    m.rounds          = meta_obj.attr("rounds").cast<int>();
    m.source_to_grid  = meta_obj.attr("source_to_grid").cast<std::vector<int>>();
    m.grid_to_source  = meta_obj.attr("grid_to_source").cast<std::vector<int>>();
    return m;
}

PYBIND11_MODULE(_ecc_cpp, mod) {
    mod.doc() = "Approximate ECC — C++ accelerated backend";

    // ------------------------------------------------------------------
    // High-level solver entry point
    // ------------------------------------------------------------------
    mod.def("correct_with_dag",
        [](py::list baseline_grid,
           py::list current_grid,
           py::object meta_obj,
           int row_group_size,
           int col_group_size,
           int hash_bits,
           const std::string& tail_policy,
           bool record_step_snapshots,
           py::object max_combos_obj,
           py::object globally_pinned_obj,
           const std::string& hash_type) -> py::dict
        {
            GridMeta meta = extract_meta(meta_obj);

            auto cpp_baseline = baseline_grid.cast<std::vector<std::vector<int>>>();
            auto cpp_current  = current_grid.cast<std::vector<std::vector<int>>>();

            int max_combos = -1;
            if (!max_combos_obj.is_none())
                max_combos = max_combos_obj.cast<int>();

            std::unordered_set<int> globally_pinned;
            if (!globally_pinned_obj.is_none()) {
                for (auto item : globally_pinned_obj)
                    globally_pinned.insert(item.cast<int>());
            }

            SolveResult res = correct_with_dag(
                cpp_baseline, cpp_current, meta,
                row_group_size, col_group_size, hash_bits,
                tail_policy, record_step_snapshots,
                max_combos, globally_pinned, hash_type);

            py::dict out;
            out["corrected_grid"]           = res.corrected_grid;
            out["mismatched_before"]        = py::set(py::cast(res.mismatched_before));
            out["mismatched_after"]         = py::set(py::cast(res.mismatched_after));
            out["steps"]                    = res.steps;
            out["step_snapshots"]           = py::list();  // empty — not populated
            out["total_combos_evaluated"]   = res.total_combos_evaluated;
            out["total_nodes_visited"]      = res.total_nodes_visited;
            out["max_flip_level_reached"]   = res.max_flip_level_reached;
            out["nodes_with_no_correction"] = res.nodes_with_no_correction;
            out["solve_time_seconds"]       = res.solve_time_seconds;
            out["grid_hd_before"]           = res.grid_hd_before;
            out["grid_hd_after"]            = res.grid_hd_after;
            return out;
        },
        py::arg("baseline_grid"),
        py::arg("current_grid"),
        py::arg("meta"),
        py::arg("row_group_size"),
        py::arg("col_group_size"),
        py::arg("hash_bits"),
        py::arg("tail_policy")           = "include_partial",
        py::arg("record_step_snapshots") = false,
        py::arg("max_combos")            = py::none(),
        py::arg("globally_pinned")       = py::none(),
        py::arg("hash_type")             = "crc",
        "C++ accelerated correct_with_dag. Returns a dict matching Python SolveResult fields."
    );

    // ------------------------------------------------------------------
    // bits_to_grid / grid_to_bits  (useful for testing Feistel port)
    // ------------------------------------------------------------------
    mod.def("bits_to_grid",
        [](py::object bits_obj, py::bytes key_obj, int rounds) -> py::tuple {
            std::string key_str = key_obj;
            std::vector<uint8_t> key(key_str.begin(), key_str.end());

            std::vector<int> bits;
            for (auto item : bits_obj) bits.push_back(item.cast<int>());

            GridMeta meta;
            auto grid = bits_to_grid(bits, key, rounds, meta);

            py::dict py_meta;
            py_meta["original_length"] = meta.original_length;
            py_meta["n"]               = meta.n;
            py_meta["m"]               = meta.m;
            py_meta["rounds"]          = meta.rounds;
            py_meta["source_to_grid"]  = meta.source_to_grid;
            py_meta["grid_to_source"]  = meta.grid_to_source;

            return py::make_tuple(grid, py_meta);
        },
        py::arg("bits"), py::arg("key"), py::arg("rounds") = 8
    );

    mod.def("grid_to_bits",
        [](py::list grid_obj, py::object meta_obj, py::bytes key_obj) -> std::vector<int> {
            std::string key_str = key_obj;
            std::vector<uint8_t> key(key_str.begin(), key_str.end());
            GridMeta meta = extract_meta(meta_obj);
            auto grid = grid_obj.cast<std::vector<std::vector<int>>>();
            return grid_to_bits(grid, meta, key);
        },
        py::arg("grid"), py::arg("meta"), py::arg("key")
    );

    // ------------------------------------------------------------------
    // build_hash_nodes  (useful for testing CRC correctness)
    // ------------------------------------------------------------------
    mod.def("build_hash_nodes",
        [](py::list grid_obj, py::object meta_obj,
           int row_group_size, int col_group_size,
           int hash_bits, const std::string& tail_policy) -> py::list
        {
            GridMeta meta = extract_meta(meta_obj);
            auto grid = grid_obj.cast<std::vector<std::vector<int>>>();
            auto nodes = build_hash_nodes(
                grid, meta, row_group_size, col_group_size, hash_bits, tail_policy);

            py::list result;
            for (const auto& n : nodes) {
                py::dict d;
                d["node_id"]        = n.node_id;
                d["axis"]           = n.axis;
                d["group_index"]    = n.group_index;
                d["hash_bits"]      = n.hash_bits;
                d["digest"]         = n.digest;
                d["source_indices"] = n.source_indices;
                result.append(d);
            }
            return result;
        },
        py::arg("grid"), py::arg("meta"),
        py::arg("row_group_size"), py::arg("col_group_size"),
        py::arg("hash_bits"), py::arg("tail_policy") = "include_partial"
    );
}
