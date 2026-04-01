# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run tests
python -m pytest test_pipeline.py

# Run a single test
python -m pytest test_pipeline.py::test_round_trip_bits

# Run end-to-end demo
python demo.py --bit-length 37 --hash-bits 16 --flip-count 2 --seed 1

# Run demo with DAG visualization (requires graphviz system binary + pip package)
python demo.py --bit-length 1024 --hash-bits 16 --row-group-size 1 --col-group-size 1 --flip-count 2 --seed 1 --viz

# Run Figure A experiment (Feistel shuffle quality)
python figure_a_shuffle.py --lengths 64,256,1024 --rounds 1,2,4,8,12 --keys 20

# Run Figure B experiment (solver effectiveness, requires matplotlib)
python figure_b_stress_test.py --hash-sizes 16,32 --flip-mode both --bit-length 256

# Skip plotting (CSV only)
python figure_a_shuffle.py --no-plot
python figure_b_stress_test.py --no-plot
```

Optional dependencies: `pip install graphviz matplotlib`

## Architecture

The system implements an approximate ECC scheme: bits are shuffled onto a 2D grid via a Feistel permutation, CRC hashes are computed over row/column groups, and a DAG-guided solver corrects bit-flips by finding flip combinations that restore hash agreement.

**Data flow:**

```
source bits  →  bits_to_grid()  →  NxN grid  →  build_hash_nodes()  →  HashNode list
                                                                              ↓
                                                                      build_hash_dag()
                                                                              ↓
baseline + damaged grids  →  correct_with_dag()  →  SolveResult (corrected grid)
```

**Module responsibilities:**

- **`feistel_perm.py`** — Cycle-walking Feistel permutation over arbitrary integer domains. `permute_index` / `invert_index` are the public API; both use SHA-256 as the round function.

- **`grid_shuffle.py`** — Maps a flat bit array to/from an NxN grid (N = ceil(sqrt(L)), padded). `GridMeta` stores the bidirectional `source_to_grid` / `grid_to_source` index maps. `bits_to_grid` / `grid_to_bits` are the public API.

- **`group_hash.py`** — Computes CRC8/16/32 hashes over non-overlapping groups of consecutive rows or columns. Each `HashNode` carries its `node_id`, `axis`, `digest`, and `source_indices` (the original source bit indices covered). `tail_policy` controls handling of groups that don't divide evenly.

- **`hash_dag.py`** — Builds a `HashDag` from a list of `HashNode`s. Edges connect any pair of nodes with overlapping `source_indices`, weighted by overlap count. Nodes sorted by `covered_bits` (smallest first) to guide repair order.

- **`bitflip_solver.py`** — Core solver. Iterates nodes in DAG order (fewest covered bits first). For each mismatched node, exhaustively tries all combinations of 0, 1, 2, … flips within that node's source indices until the node's digest matches baseline. Keeps the candidate that maximizes total matched nodes across the whole grid. Returns `SolveResult` with corrected grid and diagnostic metrics.

- **`experiments/common.py`** — Shared utilities: deterministic key derivation (`stable_key`), deterministic RNG (`stable_rng`), aggregation stats (`agg`, `median`, `Agg`), and CSV/JSON writers.

- **`figure_a_shuffle.py`** / **`figure_b_stress_test.py`** — Standalone experiment scripts that run many trials, write CSV to `results/fig_a/` and `results/fig_b/`, and optionally plot PNGs with matplotlib.

- **`visualize_dag.py`** — Renders a `HashDag` as a PNG via the `graphviz` package, with nodes color-coded by mismatch status.
