<!-- 82b04d57-5253-48c0-8d2b-707cc078b879 -->
---
todos:
  - id: "fig-a-script"
    content: "Create `experiments/figure_a_shuffle.py` to compute adjacency Euclidean distance on the shuffled grid across lengths {64,256,1024}, rounds {1,2,4,8,12}, keys=20; write CSV and generate PNG plot with 0.521405 baseline."
    status: pending
  - id: "fig-b-script"
    content: "Create `experiments/figure_b_efficiency.py` to run solver trials across lengths {64,256,1024}, flip_count 0..10, trials=10 per flip_count, keys=20, CRC {16,32}; write CSV and generate PNG plots (steps, success rate, runtime)."
    status: pending
  - id: "common-utils"
    content: "Add `experiments/common.py` with deterministic key generation, seeding utilities, and small plotting/CSV helpers (stdlib+matplotlib preferred)."
    status: pending
  - id: "docs-usage"
    content: "Add concise usage notes (script `--help` plus a short section in README or `experiments/README.md`) describing how to reproduce both figures."
    status: pending
isProject: false
---
## Scope
- Add reproducible experiment scripts (no core algorithm changes) that generate **CSV + PNG** outputs for two figures:
  - **Figure A**: Feistel shuffle quality on the **shuffled grid**.
  - **Figure B**: Correction efficiency of `correct_with_dag()` vs injected bitflips, comparing **CRC16** and **CRC32**.

## Figure A (Shuffle quality): Euclidean adjacency distance
- **Core mapping** (existing): use `grid_shuffle.bits_to_grid()` and `grid_shuffle.source_index_to_grid_coord()` to map each source index \(i\in[0,L)\) to shuffled grid coord `(r,c)`.
- **Unit-square points**:
  - \(x=(c+0.5)/n\), \(y=(r+0.5)/n\) where `n = meta.n`.
- **Metric**:
  - For each key, compute adjacency distances \(D_i=\sqrt{(x_{i+1}-x_i)^2+(y_{i+1}-y_i)^2}\) for \(i=0..L-2\).
  - Aggregate per key: mean (and optionally median/quantiles).
- **Baseline**:
  - Plot a reference line at \(\mathbb{E}[D]\approx 0.521405\) (expected distance between two random points in unit square). Optionally also estimate it via simulation in the script once.
- **Sweeps (per your choices)**:
  - bit-lengths `L ∈ {64, 256, 1024}`
  - keys: `20` random keys per configuration
  - rounds: a small sweep (proposed) `rounds ∈ {1, 2, 4, 8, 12}` (include `0` only if your Feistel perm supports identity)
- **Outputs**:
  - CSV: rows per `(L, rounds, key_id)` with columns `mean_adj_dist`, `median_adj_dist`, `n`, etc.
  - PNG: line plot of `mean_adj_dist` vs `rounds` with error bars over keys, faceted/colored by `L`.

## Figure B (Correction efficiency): steps vs flip-count, CRC16 vs CRC32
- **Core solver** (existing): `bitflip_solver.correct_with_dag()`.
- **Experimental procedure per trial**:
  - Construct baseline bits (fixed deterministic pattern, or random with seed) of length `L`.
  - Build `baseline_grid, meta = bits_to_grid(bits, key, rounds=<fixed>)`.
  - Copy to `current_grid`, inject `flip_count` flips by sampling unique source indices and flipping the corresponding shuffled cell via `source_index_to_grid_coord()` (same as `demo.py`).
  - Run `correct_with_dag(...)` with:
    - `hash_bits ∈ {16, 32}`
    - fixed group sizes (proposed initial default) `row_group_size=2`, `col_group_size=2`
    - fixed `tail_policy="include_partial"`
  - Record:
    - `steps_corrected = count of strings starting with "Corrected"` in `SolveResult.steps`
    - `total_flips_used = sum(best_flip_count extracted from those step strings)` (or, in implementation, return structured counts)
    - `mismatched_before = len(result.mismatched_before)`
    - `mismatched_after = len(result.mismatched_after)`
    - `recovered_bits_ok = (grid_to_bits(result.corrected_grid, meta, key) == original_bits)`
    - `runtime_sec` (wall clock)
- **Sweeps (per your choices)**:
  - bit-lengths `L ∈ {64, 256, 1024}`
  - keys: `20` random keys
  - flip-count: `0..10`
  - trials per flip-count: `10` (random flip sets per key)
  - CRC bits: `16` and `32`
  - rounds: keep fixed at `8` for efficiency comparisons (and optionally add a small rounds sweep later)
- **Outputs**:
  - CSV: one row per `(L, hash_bits, key_id, flip_count, trial_id)` with all recorded metrics.
  - PNGs (per `L` or combined):
    - median `steps_corrected` vs `flip_count` with CRC16/CRC32 as separate curves
    - success rate vs `flip_count`
    - runtime vs `flip_count` (optional but useful)

## Implementation details (files to add)
- Add a small `experiments/` or `analysis/` package with:
  - `experiments/figure_a_shuffle.py`
  - `experiments/figure_b_efficiency.py`
  - `experiments/common.py` (key generation, seeding, CSV writing, plotting helpers)
- Use existing project modules:
  - `grid_shuffle.py` (`bits_to_grid`, `grid_to_bits`, `source_index_to_grid_coord`)
  - `bitflip_solver.py` (`correct_with_dag`)
  - `group_hash.py` is used indirectly by solver.
- Add minimal dependencies only if needed for plotting:
  - Prefer stdlib `csv` + `matplotlib`.
  - Avoid pandas unless you want convenience.

## Reproducibility
- All scripts accept CLI args for `--seed`, `--keys`, `--trials`, `--flip-max`, `--lengths`, `--rounds-list`, and output directory.
- Log the full parameter configuration into the CSV header or a sidecar JSON.

## Run commands (to document in README or script help)
- Figure A: `python -m experiments.figure_a_shuffle --lengths 64,256,1024 --rounds 1,2,4,8,12 --keys 20 --out-dir results/fig_a`
- Figure B: `python -m experiments.figure_b_efficiency --lengths 64,256,1024 --rounds 8 --keys 20 --flip-max 10 --trials 10 --hash-bits 16,32 --out-dir results/fig_b`

## Acceptance criteria
- Running the scripts produces:
  - CSV files with expected row counts (keys × lengths × rounds × trials, etc.)
  - PNGs that clearly show:
    - Figure A adjacency-distance approaching ~0.5214 as rounds increase
    - Figure B steps/success curves differing between CRC16 and CRC32, and scaling with flip-count
