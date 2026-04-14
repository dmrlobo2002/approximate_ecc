# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Behavioral Guidelines

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

### 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it — don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

Every changed line should trace directly to the user's request.

### 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
```

---

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

# Figure 1: Headline — success rate & solve time vs flip count at 4096 bits
python fig1_headline.py --bit-length 4096 --keys 30 --parallel

# Figure 2: Overhead comparison — our scheme vs BCH
python fig2_overhead_comparison.py --bit-length 4096 --keys 20 --parallel

# Figure 3: Scalability — overhead and success across block sizes
python fig3_scalability.py --bit-lengths 256,512,1024,2048,4096 --keys 20 --parallel

# Figure 4: Burst resilience — Feistel shuffle equalizes burst vs random errors
python fig4_burst_resilience.py --bit-length 4096 --keys 30 --parallel

# Quick smoke tests (fast, few keys, no plots)
python fig1_headline.py --bit-length 4096 --keys 5 --no-plot --parallel
python fig2_overhead_comparison.py --bit-length 4096 --keys 5 --no-plot --parallel
python fig3_scalability.py --bit-lengths 256,1024,4096 --keys 5 --no-plot --parallel
python fig4_burst_resilience.py --bit-length 4096 --keys 5 --no-plot --parallel
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

- **`fig1_headline.py`** — Success rate and solve time vs flip count at 4096 bits. Shows the scheme corrects 200+ flips (BER ≥5%) with CRC-32 at 100% overhead. Outputs to `results/fig1/`.

- **`fig2_overhead_comparison.py`** — Overhead ratio vs correctable errors: our scheme vs BCH (analytical). Shows our scheme corrects more errors per overhead percent than BCH at any overhead budget. Outputs to `results/fig2/`.

- **`fig3_scalability.py`** — Overhead ratio and success rate across block sizes (256–4096 bits). Our overhead shrinks as O(1/√L) while BCH overhead for fixed t stays constant. Outputs to `results/fig3/`.

- **`fig4_burst_resilience.py`** — Success rate and solver effort for random vs burst errors. The Feistel shuffle equalization means burst errors are as easy to correct as random errors, unlike BCH which assumes a random error model. Outputs to `results/fig4/`.

- **`experiments/trial_runner.py`** — Shared trial execution utilities used by all figure scripts: `run_trial`, `_trial_task`, `get_flip_indices`, `run_trials_parallel`, `run_trials_serial`.

- **`visualize_dag.py`** — Renders a `HashDag` as a PNG via the `graphviz` package, with nodes color-coded by mismatch status.
