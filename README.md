# Approximate ECC

A novel approximate error-correcting code scheme that outperforms BCH at high error rates. Bits are scattered onto a 2D grid via a keyed Feistel permutation, short CRC hashes are computed over rows and columns, and a DAG-guided solver corrects bit-flips by finding flip combinations that restore hash agreement.

At a 4096-bit block size with 32-bit CRC (100% overhead), the scheme corrects **200+ bit-flips (≥5% BER) at 100% success rate** — while BCH requires **174% overhead** to achieve the same correction capability. Decode complexity is roughly **47× lower** than BCH (hash checks vs. GF field operations).

---

## Table of Contents

- [Background and Motivation](#background-and-motivation)
- [How It Works](#how-it-works)
  - [Step 1 — Feistel Permutation](#step-1--feistel-permutation)
  - [Step 2 — 2D Grid Layout](#step-2--2d-grid-layout)
  - [Step 3 — Row/Column Hashing](#step-3--rowcolumn-hashing)
  - [Step 4 — Hash DAG / Graph](#step-4--hash-dag--graph)
  - [Step 5 — DAG-Guided Solver](#step-5--dag-guided-solver)
- [Key Results](#key-results)
  - [Fig 1: Correction vs Flip Count](#fig-1-correction-vs-flip-count)
  - [Fig 2: Overhead vs BCH](#fig-2-overhead-vs-bch)
  - [Fig 3: Scalability Across Block Sizes](#fig-3-scalability-across-block-sizes)
  - [Fig 4: Burst vs Random Errors](#fig-4-burst-vs-random-errors)
- [Comparison with BCH](#comparison-with-bch)
- [Module Reference](#module-reference)
- [Running Experiments](#running-experiments)
- [Quick Start / Demo](#quick-start--demo)
- [Project Structure](#project-structure)
- [Dependencies](#dependencies)

---

## Background and Motivation

Classical error-correcting codes like BCH are algebraically clean but have a fundamental overhead problem at high error rates: for a BCH code that corrects `t` errors in a block of length `n`, the required parity bits scale roughly as `2t · ceil(log2 n)`. Correcting 200 errors in a 4096-bit block demands ~5200 parity bits — 174% overhead.

This project explores a different trade-off: instead of algebraic decoding, we use **short checksums (CRC) over overlapping bit groups** and a **combinatorial search** to find which bits are wrong. The key insight is that row and column hashes over a 2D grid create a constraint system — a mismatched row hash and a mismatched column hash both "pointing at" the same cell strongly localizes the error. The Feistel permutation ensures that even contiguous burst errors appear uniformly distributed across the grid, making the scheme burst-resilient by construction.

The trade-off: we pay in **solver compute time** rather than overhead bits, and the decoding is *approximate* in the sense that success is probabilistic at high flip counts (though empirically 100% at ≤5% BER with 32-bit CRC).

---

## How It Works

### Step 1 — Feistel Permutation

**Module:** `feistel_perm.py`

Before any hashing, the flat bit array is permuted using a **cycle-walking Feistel network** over an arbitrary integer domain. The permutation is keyed (16-byte key) and invertible, with 8 rounds using SHA-256 as the round function.

```
permute_index(index, domain_size, key, rounds=8)
invert_index(index, domain_size, key, rounds=8)
```

The cycle-walking technique handles non-power-of-two domain sizes: if the Feistel output falls outside `[0, domain_size)`, the cipher is applied again until it lands in range. This guarantees a bijection over exactly `domain_size` elements.

**Why this matters:** A burst error (e.g., 200 contiguous flips in flash storage) gets scattered pseudo-randomly across the grid, becoming statistically identical to random errors from the solver's perspective. This is the property BCH codes fundamentally lack.

### Step 2 — 2D Grid Layout

**Module:** `grid_shuffle.py`

The permuted bit array is reshaped into an `N × N` grid where `N = ceil(sqrt(L))`. If `L` is not a perfect square, the grid is zero-padded to `N²` bits.

```python
grid, meta = bits_to_grid(bits, key=key, rounds=8)
# grid is an N×N list-of-lists of 0/1
# meta (GridMeta) stores the bidirectional source_to_grid / grid_to_source index maps
```

The `GridMeta` dataclass records the full index mapping so the permutation can be inverted exactly during recovery.

### Step 3 — Row/Column Hashing

**Module:** `group_hash.py`

CRC hashes are computed over non-overlapping groups of consecutive rows and columns. With `group_size=1` (the default for experiments), each row and each column gets its own hash — producing `2N` hash nodes for an `N × N` grid.

Supported hash functions:
- **CRC-8** (8-bit digest, 25% overhead at 4096 bits)
- **CRC-16** (16-bit digest, 50% overhead)
- **CRC-32** (32-bit digest, 100% overhead)
- **SimHash / GF(2) random linear hash** (alternative, same false-positive rate as CRC)

Each `HashNode` stores:
- `node_id` — e.g. `"row_3"` or `"col_7"`
- `axis` — `"row"` or `"col"`
- `digest` — the integer CRC value
- `source_indices` — frozenset of original source bit indices covered by this node

**Overhead formula:**

```
overhead = (num_row_nodes + num_col_nodes) × hash_bits / data_bits
         = (2 × ceil(N / group_size)) × hash_bits / L
```

For L=4096, N=64, group_size=1, hash_bits=32: overhead = (64+64)×32 / 4096 = **100%**.

### Step 4 — Hash DAG / Graph

**Module:** `hash_dag.py`

A bidirectional graph (`HashGraph`) is built from the hash nodes. An edge connects any two nodes whose `source_indices` sets overlap, weighted by the overlap count. For `group_size=1`, every row node overlaps with every column node at exactly one grid cell — giving a complete bipartite graph with `N²` edges.

This graph encodes the constraint structure: if a bit is flipped, it corrupts exactly one row node and one column node. The intersection of a mismatched row and mismatched column pinpoints the candidate cell. With multiple flips, the solver uses this structure to narrow its search.

### Step 5 — DAG-Guided Solver

**Module:** `bitflip_solver.py`

The solver (`correct_with_dag`) iterates nodes in order of ascending flip count (estimated from how many bits in the node differ from baseline), trying to find bit-flip combinations that restore each mismatched node's hash digest.

**Algorithm:**

1. Sort nodes by estimated number of flips they contain (fewest first).
2. For each mismatched node, collect candidate search indices in priority order:
   - **Intersection indices** — bits shared with other *mismatched* neighbor nodes (most likely candidates)
   - **Free indices** — bits not covered by any *matched* neighbor (safe to flip)
   - **All source indices** — fallback if no good fix found above
3. For each candidate set, enumerate combinations of size 1, 2, 3, … (up to `max_flips`). For each combination, tentatively apply the flips and count how many total nodes become matched across the whole grid.
4. Commit the combination that maximizes total matched nodes. If the committed fix resolves the last mismatch, halt early.
5. Repeat the full pass until no more progress is made.

The key optimization is that **matched neighbors act as pins** — bits covered by already-correct row/column nodes are excluded from the search space, dramatically reducing the combinatorial explosion.

**Metrics tracked per solve:**
- `total_combos_evaluated` — number of CRC evaluations (hash checks)
- `total_nodes_visited` — number of mismatched nodes processed
- `max_flip_level_reached` — highest flip count committed in any single step
- `solve_time_seconds` — wall-clock solve time
- `grid_hd_before` / `grid_hd_after` — Hamming distance before and after correction

A pure Python fallback is available; a C++ extension (`_ecc_cpp`) is used when built, providing significant speedups for large blocks.

---

## Key Results

### Fig 1: Correction vs Flip Count

*4096-bit block, single key, group_size=1*

| Configuration | Overhead | Corrects up to | Solve time at 200 flips |
|---|---|---|---|
| 8-bit CRC | 25% | ~65 flips (1.6% BER) | N/A (fails) |
| 16-bit CRC | 50% | ~130 flips (3.2% BER) | ~15 s (thrashing) |
| 32-bit CRC | 100% | **200+ flips (5% BER)** | **~730 ms** |

The 16-bit CRC exhibits a sharp solver collapse at its correction boundary — the solver evaluates millions of combinations without converging. The 32-bit CRC stays well-behaved because its longer digest provides enough constraint entropy to localize errors.

At 200 flips with 32-bit CRC: ~138,000 hash checks, ~730 ms median solve time.

### Fig 2: Overhead vs BCH

*Block size = 4096 bits*

| Scheme | To correct 50 flips | To correct 100 flips | To correct 200 flips |
|---|---|---|---|
| BCH (analytical) | 18.9% overhead | 46.5% overhead | **173.9% overhead** |
| Ours: 8-bit CRC | 25% overhead | fails | fails |
| Ours: 16-bit CRC | **50% overhead** | **50% overhead** | fails |
| Ours: 32-bit CRC | 100% overhead | 100% overhead | **100% overhead** |

**Correction efficiency** (flips corrected per 1% overhead):
- BCH at t=200: 200 / 174% ≈ **1.15 flips/%**
- Ours (32-bit CRC) at 200 flips: 200 / 100% = **2.0 flips/%** — **1.7× better**

**Decode complexity** at t=200:
- BCH: ~6.6M GF(2^m) field operations (syndrome + Berlekamp-Massey + Chien search + Forney)
- Ours (32-bit CRC): ~138K CRC hash checks — **~47× lower**

### Fig 3: Scalability Across Block Sizes

Our overhead ratio scales as O(1/√L):

```
overhead ≈ 2N × hash_bits / L  =  2 × ceil(√L) × hash_bits / L  ≈  2 × hash_bits / √L
```

At L=256 (N=16): 32-bit CRC → 400% overhead (impractical).
At L=4096 (N=64): 32-bit CRC → 100% overhead (competitive).
At L=16384 (N=128): 32-bit CRC → 50% overhead (attractive).

BCH overhead for fixed t stays constant regardless of block size. For t=200, BCH remains at ~174% at every block size, while ours improves monotonically.

### Fig 4: Burst vs Random Errors

*4096-bit block, 16-bit CRC, group_size=1*

The Feistel permutation distributes a contiguous burst of flips pseudo-randomly across the grid. The solver sees no statistical difference between a burst and a random error pattern. Success rate curves and combo count curves for "random" vs "burst" overlap almost exactly across all tested flip counts.

BCH codes assume an independent random error model. Burst errors that exceed the BCH design parameter `t` cause complete decode failure; our scheme handles them natively.

---

## Comparison with BCH

| Property | BCH | Approximate ECC (Ours) |
|---|---|---|
| Overhead for 200-flip correction (4096 bits) | **174%** | **100%** |
| Correction efficiency (flips per 1% overhead) | 1.15 | **2.0** |
| Decode operations at t=200 | ~6.6M GF ops | ~138K hash checks |
| Burst error resilience | Poor (assumes random errors) | **Excellent** (Feistel scatter) |
| Decode failure mode | Hard fail (algebraic decode fails) | Soft fail (returns best-effort) |
| Requires golden baseline | No (syndromes are self-contained) | Yes (baseline hashes stored) |
| Overhead scaling with block size | Constant for fixed t | **O(1/√L) — improves** |
| Asymptotic guarantee | Guaranteed for t ≤ design parameter | Probabilistic (false positive ≈ 2^{-hash_bits}) |

**When to prefer this scheme over BCH:**
- Large block sizes (≥ 2048 bits) where BCH parity overhead dominates
- High target BER (≥ 2–3%) where BCH overhead is impractical
- Environments with burst errors (flash, DRAM row hammer, network bursts)
- Applications where a fast approximate result is acceptable over a slow algebraic guarantee

---

## Module Reference

| Module | Responsibility |
|---|---|
| `feistel_perm.py` | Cycle-walking Feistel permutation. Public API: `permute_index`, `invert_index`. |
| `grid_shuffle.py` | Maps flat bit array ↔ N×N grid via the Feistel permutation. Public API: `bits_to_grid`, `grid_to_bits`. `GridMeta` stores bidirectional index maps. |
| `group_hash.py` | Computes CRC-8/16/32 or SimHash over non-overlapping row/column groups. Each `HashNode` carries its digest and `source_indices`. `build_hash_nodes` is the main entry point. |
| `hash_dag.py` | Builds a `HashGraph` connecting nodes with overlapping `source_indices`, weighted by overlap count. |
| `bitflip_solver.py` | Core solver. `correct_with_dag` uses the graph to guide flip search. `correct_without_golden` is a variant that only needs stored digests (not the original bits). `SolveResult` carries full diagnostics. |
| `experiments/common.py` | Shared utilities: `stable_key`, `stable_rng` (deterministic key/RNG derivation), `agg`/`Agg` (statistics), `compute_overhead_ratio`, CSV/JSON writers. |
| `experiments/ecc_comparison.py` | Analytical BCH/Hamming/LDPC overhead formulas. `bch_overhead(data_bits, t)` and `bch_decode_ops(data_bits, t)` for complexity comparisons. |
| `experiments/trial_runner.py` | Shared trial execution: `run_trial`, `run_trials_parallel`, `run_trials_serial`, `get_flip_indices`. |
| `fig1_headline.py` | Success rate, solve time, and hash comparisons vs flip count at 4096 bits. Outputs to `results/fig1/`. |
| `fig2_overhead_comparison.py` | Overhead vs correction capability, correction efficiency, and decode complexity vs BCH. Outputs to `results/fig2/`. |
| `fig3_scalability.py` | Overhead ratio and success rate across block sizes (256–4096+ bits). Outputs to `results/fig3/`. |
| `fig4_burst_resilience.py` | Success rate and search effort for random vs burst errors. Outputs to `results/fig4/`. |
| `visualize_dag.py` | Renders a `HashGraph` as a PNG via the `graphviz` package, nodes color-coded by mismatch status. |
| `demo.py` | End-to-end walkthrough with optional DAG visualization at each solver step. |

---

## Running Experiments

### Full runs at 4096-bit target block size

```bash
# Fig 1: Success rate, solve time, and hash comparisons vs flip count
python3 fig1_headline.py --bit-length 4096 --keys 30 --parallel

# Fig 2: Overhead and decode complexity vs BCH
python3 fig2_overhead_comparison.py --bit-length 4096 --keys 20 --parallel

# Fig 3: Scalability across block sizes (add more sizes for better coverage)
python3 fig3_scalability.py --bit-lengths 256,512,1024,2048,4096,8192 --keys 20 --parallel

# Fig 4: Burst vs random error resilience
python3 fig4_burst_resilience.py --bit-length 4096 --keys 30 --parallel
```

### Quick smoke tests (fast, no plots)

```bash
python3 fig1_headline.py --bit-length 4096 --keys 5 --no-plot --parallel
python3 fig2_overhead_comparison.py --bit-length 4096 --keys 5 --no-plot --parallel
python3 fig3_scalability.py --bit-lengths 256,1024,4096 --keys 5 --no-plot --parallel
python3 fig4_burst_resilience.py --bit-length 4096 --keys 5 --no-plot --parallel
```

### CLI flags common to all figure scripts

| Flag | Description |
|---|---|
| `--bit-length N` | Block size in bits (default: 4096) |
| `--keys K` | Number of independent keys to test (more = tighter confidence intervals) |
| `--parallel` | Distribute trials across all CPU cores using `ProcessPoolExecutor` |
| `--workers W` | Override worker count (default: `os.cpu_count()`) |
| `--no-plot` | Skip matplotlib rendering (useful on headless machines) |
| `--out-dir PATH` | Output directory for CSV/JSON/PNG (default: `results/figN/`) |
| `--seed S` | Global RNG seed for reproducibility (default: 0) |

### Output files

Each figure script writes to its output directory:

```
results/fig1/
  config.json          — run parameters
  fig1_data.csv        — per-trial: flip_count, ber, fully_corrected,
                         total_combos_evaluated, solve_time_ms, ...
  fig1_headline.png    — 3-panel figure

results/fig2/
  config.json
  fig2_bch.csv         — analytical BCH overhead per t value
  fig2_ours.csv        — empirical results per config + flip count,
                         including total_combos_evaluated
  fig2_operating_points.csv  — max correctable flips per config
  fig2_overhead_comparison.png  — 3-panel figure (overhead, efficiency, decode complexity)

results/fig3/
  fig3_overhead.csv
  fig3_empirical.csv
  fig3_scalability.png

results/fig4/
  fig4_data.csv        — per-trial: mode (random/burst), flip_count,
                         total_combos_evaluated, solve_time_ms, ...
  fig4_burst_resilience.png
```

---

## Quick Start / Demo

```bash
# Minimal end-to-end: 37-bit block, 16-bit CRC, 2 flips
python3 demo.py --bit-length 37 --hash-bits 16 --flip-count 2 --seed 1

# Larger block with DAG visualization (requires graphviz)
python3 demo.py --bit-length 1024 --hash-bits 16 \
    --row-group-size 1 --col-group-size 1 \
    --flip-count 2 --seed 1 --viz
# Outputs step-by-step PNG frames to dag_viz/

# Run unit and integration tests
python3 -m pytest test_pipeline.py

# Run a single test
python3 -m pytest test_pipeline.py::test_round_trip_bits
```

---

## Project Structure

```
approximate_ecc/
├── feistel_perm.py          # Keyed Feistel permutation (SHA-256 round function)
├── grid_shuffle.py          # Bit array ↔ N×N grid mapping
├── group_hash.py            # Row/column CRC hashing, HashNode, GroupHashContext
├── hash_dag.py              # HashGraph construction (overlap-weighted edges)
├── bitflip_solver.py        # DAG-guided exhaustive solver, SolveResult
├── visualize_dag.py         # Graphviz-based DAG renderer
├── demo.py                  # End-to-end interactive demo
├── test_pipeline.py         # pytest test suite
│
├── experiments/
│   ├── common.py            # Shared utilities (keys, RNG, stats, I/O)
│   ├── ecc_comparison.py    # BCH/Hamming/LDPC analytical models
│   └── trial_runner.py      # Parallel/serial trial execution harness
│
├── fig1_headline.py         # Success rate + solve time + hash checks vs flip count
├── fig2_overhead_comparison.py  # Overhead + efficiency + decode complexity vs BCH
├── fig3_scalability.py      # Overhead scaling across block sizes
├── fig4_burst_resilience.py # Burst vs random error comparison
│
├── results/
│   ├── fig1/                # fig1 outputs (CSV, JSON, PNG)
│   ├── fig2/                # fig2 outputs
│   ├── fig3/                # fig3 outputs
│   └── fig4/                # fig4 outputs
│
├── cpp/                     # C++ extension source (pybind11)
│   └── src/
│       ├── bindings.cpp
│       ├── bitflip_solver.cpp
│       ├── feistel_perm.cpp
│       ├── grid_shuffle.cpp
│       ├── group_hash.cpp
│       └── hash_dag.cpp
│
└── build/                   # CMake build output for C++ extension
```

---

## Dependencies

**Required:**
- Python 3.10+
- No third-party packages required for the core solver or trial runner

**Optional:**
```bash
pip install matplotlib    # for figure rendering (--no-plot skips this)
pip install graphviz      # for DAG visualization in demo.py
```

For the C++ extension (significant speedup on large blocks):
```bash
# Build the pybind11 extension
cd build && cmake .. && make -j$(nproc)
# The solver auto-detects _ecc_cpp and uses it when available
```
