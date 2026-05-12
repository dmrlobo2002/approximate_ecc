# DETAILED DESCRIPTION OF THE INVENTION

The following detailed description is presented to enable any person skilled in the art to make and use the invention. For purposes of explanation, specific details are set forth to provide a thorough understanding of the present invention. However, it will be apparent to one skilled in the art that these specific details are not required to practice the invention. Descriptions of specific applications and methods are provided only as examples. Various modifications to the preferred embodiments will be readily apparent to those skilled in the art, and the general principles defined herein may be applied to other embodiments and applications without departing from the spirit and scope of the invention.

The present invention is described primarily in terms of a software implementation executing on a general-purpose processor. Those skilled in the art will recognize that the same methods may be implemented in dedicated hardware (e.g., an ASIC or FPGA), as a firmware module embedded in a memory controller, or as a hybrid of hardware and software. All such implementations are within the scope of the invention.

---

## I. SYSTEM OVERVIEW

FIG. 1 illustrates the encoding pipeline of an embodiment of the present invention. A source data block **100** of L bits is provided as input. The data block 100 passes through a **Feistel permutation stage 102**, which produces a permuted bit ordering. The permuted bits are arranged into a **two-dimensional grid 104** of N rows and N columns, where N = ⌈√L⌉. A **hash computation stage 106** computes hash digests over groups of rows and groups of columns of the grid 104. The resulting hash digests, collectively referred to as **hash metadata 108**, are stored alongside the original data block 100 in a storage medium or transmitted alongside the data block 100 through a communication channel.

FIG. 2 illustrates the decoding pipeline. A **received data block 200** (which may contain bit-flip errors relative to the original data block 100) is arranged into a two-dimensional grid 202 using the same Feistel permutation used during encoding. A **hash recomputation stage 204** computes row and column digests over the received grid 202 and compares them against the stored hash metadata 108, producing a set of **mismatched hash nodes 206**. A **constraint graph construction stage 208** builds a graph whose nodes represent hash digest computations and whose edges connect nodes with overlapping bit coverage. A **constraint-guided search stage 210** performs the bit-flip correction search. The output is a **corrected data block 212**, from which the Feistel permutation is inverted to recover the corrected source bits.

---

## II. FEISTEL PERMUTATION

### A. Purpose

The Feistel permutation serves two purposes in the present invention. First, it provides keyed, deterministic bit reordering that is reproducible at both the encoder and decoder from a shared key. Second, and critically, it scatters contiguous burst errors across the two-dimensional grid, converting the burst correction problem into the statistically equivalent random-error problem. Without this scattering, a burst of b consecutive bit-flips would affect only a single row of the grid, overloading the correction capability of that row's hash node. After Feistel scattering, the same b flips are distributed approximately uniformly across O(b) distinct rows and columns, each node seeing approximately one flip on average.

### B. Construction

The permutation operates on the integer domain {0, 1, …, L-1}, where L is the number of bits in the data block. Because L is an arbitrary integer (not necessarily a power of two), the permutation cannot use a simple bitmask-based Feistel network. Instead, the invention uses the **cycle-walking** technique, which extends the standard Feistel construction to arbitrary domain sizes.

The permutation is parameterized by an R-round Feistel network, where R ≥ 4. In a preferred embodiment, R = 8. Each round of the Feistel network uses a keyed **round function** F_k(x) that maps an integer x to a pseudorandom output. In a preferred embodiment, the round function is SHA-256, truncated to the required bit width, and keyed using a 16-byte secret key K concatenated with a round index r.

**Forward permutation (encoding).** Given an index i ∈ {0, …, L-1}, the forward permutation proceeds as follows:

1. Split i into a left half L_i and a right half R_i using a balanced bit partition.
2. For each round r = 0, 1, …, R-1:
   - Compute new_R = L_i XOR F_k(R_i || r)
   - Set L_i = R_i, R_i = new_R
3. Combine the halves to form a candidate output index c.
4. If c ∉ {0, …, L-1} (i.e., c falls outside the domain), set i = c and repeat from step 1 (cycle-walking). Repeat until c ∈ {0, …, L-1}.
5. Return c as the permuted index π(i).

The cycle-walking step ensures that the function π is a bijection on {0, …, L-1} despite L not being a power of two. The expected number of iterations before a valid index is found is at most 2 for typical domain sizes. The Feistel network guarantees invertibility: the inverse permutation π⁻¹ is obtained by applying the Feistel rounds in reverse order using the same key.

**Inverse permutation (decoding).** The inverse permutation applies the R Feistel rounds in reverse (r = R-1, …, 0) with swapped halves, followed by the same cycle-walking procedure, to recover the original index from a permuted index.

### C. Application to Data Block

To encode a data block B = {b_0, b_1, …, b_{L-1}}, the permuted block B' is defined by B'[π(i)] = B[i] for all i ∈ {0, …, L-1}. Equivalently, the source bit at position i is placed at position π(i) in the permuted block. The permuted block B' is then arranged into the two-dimensional grid.

---

## III. TWO-DIMENSIONAL GRID LAYOUT

### A. Grid Dimensions

Given a data block of L bits, the grid dimension is N = ⌈√L⌉. The grid G is an N×N array of bits. If N² > L (i.e., L is not a perfect square), the grid is zero-padded: the first L positions of the row-major linearization of G are populated with the bits of B', and the remaining N²-L positions are set to zero. The zero-padding bits are fixed and known to both encoder and decoder; they do not contribute to correctable errors.

In a preferred embodiment:
- For L = 256 bits: N = 16, grid = 16×16
- For L = 1024 bits: N = 32, grid = 32×32
- For L = 4096 bits: N = 64, grid = 64×64

### B. Index Mappings

The encoder computes and stores two bidirectional index mappings:
- **source_to_grid[i]**: for source bit index i ∈ {0, …, L-1}, the corresponding (row, column) position in the grid G after permutation.
- **grid_to_source[(r, c)]**: for grid position (r, c), the corresponding source bit index.

These mappings are derived deterministically from the Feistel permutation and the grid dimensions; they need not be stored explicitly, as they can be recomputed from the shared key K and the block length L.

---

## IV. HASH NODE CONSTRUCTION

### A. Row Hash Nodes

The grid G is divided into groups of consecutive rows. With a group size parameter s ≥ 1, the rows are partitioned into groups {0, …, s-1}, {s, …, 2s-1}, etc. For each row group g, a **hash node** n_g is defined with the following attributes:

- **node_id**: a unique identifier (e.g., "row_g")
- **axis**: "row"
- **covered_source_indices**: the set of source bit indices i such that the corresponding grid bit G[r][c] belongs to a row r in the group g
- **digest**: the hash digest computed over the bits of all rows in the group g

In a preferred embodiment with s = 1 (one row per group), each of the N rows produces one row hash node, yielding N row hash nodes total.

### B. Column Hash Nodes

Analogously, the columns of the grid G are divided into groups of s consecutive columns. For each column group g, a column hash node n_g is defined with attributes analogous to the row hash nodes, with axis "column."

In a preferred embodiment with s = 1, each of the N columns produces one column hash node, yielding N column hash nodes total.

### C. Hash Function

In preferred embodiments, the hash digest for each node is computed as one of the following:

1. **CRC-8** (8-bit cyclic redundancy check): 8-bit digest, false positive probability 2⁻⁸ ≈ 0.39%
2. **CRC-16** (16-bit cyclic redundancy check): 16-bit digest, false positive probability 2⁻¹⁶ ≈ 0.0015%
3. **CRC-32** (32-bit cyclic redundancy check, polynomial 0xEDB88320): 32-bit digest, false positive probability 2⁻³² ≈ 2.3×10⁻¹⁰
4. **CRC-64**: 64-bit digest, false positive probability 2⁻⁶⁴
5. **GF(2) random linear hash (SimHash)**: A hash of configurable width h bits, computed as the XOR of h independently chosen random linear functions over GF(2) applied to the input bits. Each output bit is independently computed as a parity check over a random subset of input bits, yielding false positive probability 2⁻ʰ per bit and 2⁻ʰ overall. SimHash is equivalent to multiplication by a random binary matrix in GF(2).

In a preferred embodiment, CRC-32 is used with s = 1, yielding 2N = 128 hash digests of 32 bits each for a 4096-bit block, resulting in 128 × 32 = 4096 bits of metadata (100% overhead).

### D. Overhead Formula

The total metadata overhead in bits is:

    overhead_bits = (⌈N/s⌉ + ⌈N/s⌉) × h = 2·⌈N/s⌉ · h

where N = ⌈√L⌉, s is the group size, and h is the hash width in bits. The overhead ratio relative to the data block is:

    overhead_ratio = 2·⌈N/s⌉ · h / L ≈ 2h / (s·√L)

For fixed h and s, this scales as O(1/√L), decreasing as block size increases. This is in contrast to BCH overhead, which scales as O(t·log L) and, for a fixed target bit error rate (t = p·L), grows as O(p·L·log L), meaning the BCH overhead ratio remains approximately constant or grows with L.

---

## V. CONSTRAINT GRAPH CONSTRUCTION

### A. Graph Definition

After computing the hash nodes, the encoder or decoder constructs a **constraint graph** G_C = (V, E), where:

- **V** is the set of all hash nodes (row nodes and column nodes)
- **E** is the set of undirected edges, with an edge (u, v) ∈ E if and only if the covered source indices of nodes u and v have a non-empty intersection

Each edge (u, v) carries a weight equal to the size of the intersection |covered_source_indices(u) ∩ covered_source_indices(v)|.

### B. Structure for Default Configuration

In the preferred embodiment with s = 1 and N rows and N columns:

- There are N row nodes and N column nodes.
- Each row node r_i covers exactly the N source indices corresponding to row i of the grid.
- Each column node c_j covers exactly the N source indices corresponding to column j of the grid.
- Each row node r_i intersects exactly with each column node c_j at exactly one source index: the source index corresponding to grid position (i, j).
- There are no row-row or column-column edges (row groups and column groups do not share any bits within the same axis).
- The result is a **complete bipartite graph** K_{N,N} with N² edges, each of weight 1.

This bipartite structure means that for each bit at grid position (i, j), exactly one row node and one column node are "aware" of that bit. A bit-flip at position (i, j) corrupts exactly one row digest and one column digest, making the pair (r_i, c_j) of mismatched nodes a direct pointer to the flipped bit's location.

### C. FIG. 3 — Example Constraint Graph

FIG. 3 illustrates an example constraint graph for a 4×4 grid (N=4, L=16). Four row nodes R0–R3 and four column nodes C0–C3 are shown. Edges connect each row node to each column node. Nodes that are mismatched (i.e., their recomputed digest does not match the stored digest) are shown with a distinguishing visual indicator. In the example shown, nodes R1 and C2 are both mismatched, pointing to grid position (1, 2) as the location of a single bit-flip.

---

## VI. CONSTRAINT-GUIDED BIT-FLIP SEARCH (DECODER)

### A. Overview

The decoding procedure receives the constraint graph G_C with nodes labeled as either **matched** (recomputed digest equals stored digest) or **mismatched** (digests differ). The goal is to find and apply a set of bit-flips to the received grid that converts all nodes from mismatched to matched.

The decoder uses a **greedy flip-level climbing** approach: it iterates over mismatched nodes in a priority order, and for each mismatched node, exhaustively enumerates bit-flip combinations of increasing size within a pruned candidate set. The candidate set is pruned using the **matched-neighbor pinning** heuristic.

### B. Node Ordering

Mismatched nodes are sorted in ascending order of their **covered-bit count** (i.e., the number of source indices covered by the node). In the preferred embodiment with s = 1, all nodes have the same covered-bit count N, so a secondary sort is applied: nodes with fewer mismatched neighbors in the constraint graph are processed first, as they are statistically more likely to be fixed by a small number of flips.

### C. Matched-Neighbor Pinning

For a mismatched node u currently being processed, the decoder computes three disjoint sets of source indices from u's covered indices:

1. **Intersection indices (I)**: source indices covered by u that are also covered by at least one **mismatched** neighbor of u. These are the highest-priority candidates for flipping, as they are implicated by multiple constraint violations.

2. **Free indices (F)**: source indices covered by u that are **not** covered by any **matched** neighbor of u. These are safe to flip without disrupting already-correct constraints.

3. **Pinned indices (P)**: source indices covered by u that are covered by at least one **matched** neighbor of u. These are **excluded** from the search (pinned), because flipping a pinned bit would corrupt an already-correct constraint.

The candidate index set for the search is I ∪ F (intersection indices plus free indices). Pinned indices are never considered for flipping in the current iteration.

This matched-neighbor pinning is the key pruning mechanism that makes combinatorial search tractable. Without pinning, the search space for a node covering N bits at flip level k is C(N, k). With pinning, the effective search space is C(|I|+|F|, k), where |P| = N - |I| - |F| is the number of excluded indices. In the asymptotic regime of high error rates with many matched neighbors, |I|+|F| ≪ N, reducing the search space by orders of magnitude.

### D. Combination Enumeration and Scoring

For each mismatched node u being processed, the decoder enumerates combinations of candidate indices of increasing flip count k = 1, 2, 3, …, up to a configurable maximum flip level K_max. For each combination C of k indices:

1. **Tentatively apply** the k bit-flips to the working grid.
2. **Recompute** the hash digests for all nodes in V whose covered indices include any flipped bit. This recomputation is bounded by the number of affected nodes (at most 2k in the default bipartite configuration).
3. **Score** the flip combination as the total number of matched nodes in V after the tentative flip.
4. **Revert** the tentative flips (or maintain the working grid with flip deltas tracked separately).

After evaluating all combinations at the current flip level k, the decoder commits the combination that achieves the highest score (i.e., the maximum total matched nodes). If no combination achieves a higher score than the current baseline, the decoder advances to flip level k+1. If a combination is committed, the matched/mismatched labels of affected nodes are updated.

### E. Outer Iteration

The inner loop (node selection and flip enumeration) is embedded in an outer iteration that repeats until no mismatched nodes remain, or until no progress was made in the previous pass (i.e., no flip combination improved the total matched node count). When no progress is made at the current maximum flip level, the maximum flip level is incremented by one (flip-level climbing) and the iteration continues.

### F. Inversion

After correction is complete (all nodes matched, or the outer iteration terminates), the corrected working grid is converted back to a flat bit array. The Feistel inverse permutation π⁻¹ is then applied to recover the corrected source bits in their original order.

### G. FIG. 4 — Matched-Neighbor Pinning Illustration

FIG. 4 illustrates the matched-neighbor pinning concept for a mismatched row node R1 in a 4×4 grid with N=4. R1 covers source indices {s0, s1, s2, s3} corresponding to grid positions (1,0), (1,1), (1,2), (1,3) respectively. Column nodes C0 and C3 are matched (correct); column nodes C1 and C2 are mismatched. The categorization is:
- **Intersection indices**: {s1, s2} (covered by mismatched column neighbors C1 and C2)
- **Free indices**: {} (no bits are uncovered by matched columns in this example)
- **Pinned indices**: {s0, s3} (covered by matched column neighbors C0 and C3, excluded from search)

The decoder searches only combinations within {s1, s2}, reducing the search from C(4,k) to C(2,k) for each flip level k.

---

## VII. WORKED EXAMPLE

To illustrate the complete encoding and decoding pipeline, consider a block of L=16 bits with key K="example_key_000".

**Encoding:**
1. Source block: B = [1,0,1,1,0,0,1,0,1,1,0,0,0,1,1,0] (16 bits)
2. Feistel permutation produces permuted block B' (indices scrambled by π)
3. B' is arranged into a 4×4 grid G (N=4, no padding needed since 4²=16)
4. Row hash nodes R0–R3: each covers 4 bits; CRC-8 digest computed for each
5. Column hash nodes C0–C3: each covers 4 bits; CRC-8 digest computed for each
6. Hash metadata H = {R0.digest, R1.digest, R2.digest, R3.digest, C0.digest, C1.digest, C2.digest, C3.digest} — 8 bytes stored alongside the 16-bit data block (50% overhead for CRC-8)

**Injected errors:** two bit-flips at source indices 5 and 11.

**Decoding:**
1. Received block B_r differs from B at positions 5 and 11
2. Grid G_r constructed from B_r using same permutation π
3. Row and column digests recomputed over G_r:
   - Suppose the two flipped bits, after permutation, land in row 1 and column 2, and row 3 and column 0, respectively
   - Nodes R1, R3, C0, C2 are mismatched; nodes R0, R2, C1, C3 are matched
4. Constraint graph built: edges between each R and each C
5. Decoder selects mismatched node R1 (fewest mismatched neighbors: 2)
   - Intersection indices: {s_12} (position shared with mismatched C2)
   - Pinned indices: {s_10, s_11, s_13} (shared with matched C0, C1, C3)
   - Wait — C0 is mismatched, C1 and C3 are matched, C2 is mismatched
   - Intersection indices of R1: {s_10, s_12} (shared with mismatched C0 and C2)
   - Pinned indices of R1: {s_11, s_13} (shared with matched C1 and C3)
   - Search among {s_10, s_12}; try flip at s_10 → score improves; commit
6. After committing flip at s_10: R1 and C0 become matched
7. Decoder selects next mismatched node R3
   - Intersection indices: {s_32} (shared with still-mismatched C2)
   - Search; try flip at s_32 → score improves; commit
8. After committing flip at s_32: R3 and C2 become matched; all nodes now matched
9. Corrected grid G_c converted back to flat array, π⁻¹ applied to recover corrected B

---

## VIII. EMBODIMENTS

### A. Software Embodiment

In a software embodiment, the invention is implemented as a Python or C++ library. The encoding pipeline comprises the modules: (1) a Feistel permutation module implementing the cycle-walking multi-round Feistel network with SHA-256 as the round function; (2) a grid layout module mapping permuted bits to an N×N array and tracking index mappings; (3) a hash node construction module computing CRC digests over row and column groups; and (4) a serialization module packing hash digests into a compact binary metadata blob.

The decoding pipeline comprises: (1) the same grid layout and Feistel inversion modules; (2) a hash comparison module identifying mismatched nodes; (3) a constraint graph module building the overlap graph; and (4) a solver module implementing the greedy flip-level climbing search with matched-neighbor pinning.

A C++ accelerated implementation using the pybind11 framework provides significant speedup over the pure-Python implementation for large block sizes.

### B. Hardware Embodiment

In a hardware embodiment suitable for integration with a DRAM or flash memory controller, the invention is implemented as a digital logic circuit comprising:

- A **Feistel permutation unit** implementing the R-round SHA-256-keyed Feistel network in hardware, with a cycle-walking controller
- A **grid mapping unit** implementing the source-to-grid and grid-to-source index lookup tables
- A **CRC computation array** comprising N parallel CRC units, one per row, and N parallel CRC units, one per column, capable of computing all 2N digests simultaneously in a single pass over the grid data
- A **metadata register file** storing the 2N baseline digests
- A **mismatch detection unit** comparing stored and recomputed digests
- A **constraint graph register** maintaining the bipartite adjacency structure and matched/mismatched labels
- A **combinatorial search unit** implementing the candidate enumeration and scoring logic, including a matched-neighbor pin mask generator

FIG. 10 illustrates a system diagram of a hardware embodiment.

### C. Application: Memory Protection for AI Accelerator Weight Storage

In one application, the invention protects the weight matrices of a deep neural network (DNN) stored in on-chip SRAM or off-chip DRAM within an AI accelerator. Each weight matrix or submatrix of L bits is encoded into a hash-metadata protected block. At inference time, the weight block is read from memory, the hash digests are recomputed, and any detected mismatches trigger the decoder. Because the DNN weight values are relatively tolerant of small residual errors after correction (model accuracy degrades gracefully with small perturbations), the approximate nature of the correction is acceptable, and the reduced overhead compared to BCH codes translates directly into lower silicon area for the metadata storage and ECC engine.

### D. Application: NAND Flash Storage

In another application, the invention protects data pages in NAND flash storage, where increasing page sizes (4 KB to 16 KB) and aggressive multi-level cell (MLC/TLC) operation produce high and variable bit error rates with a significant burst component. The Feistel permutation neutralizes burst errors without requiring a separate interleaver. The O(1/√L) overhead scaling means that larger pages incur proportionally less metadata overhead.

---

## IX. VARIANTS AND EXTENSIONS

### A. Group Size Variants

Setting the group size parameter s > 1 combines multiple rows (or columns) into a single hash node. This reduces the total number of hash nodes from 2N to 2⌈N/s⌉, proportionally reducing metadata overhead at the cost of coarser error localization. With larger groups, the solver must search among a larger candidate index set per node, but the reduced number of constraints remains sufficient for correction at moderate error rates.

### B. Hash Function Variants

Any of the supported hash functions (CRC-8, CRC-16, CRC-32, CRC-64, SimHash) can be selected to tune the false-positive probability and per-node metadata cost. Wider hashes reduce false positive probability (a mismatched node whose digest accidentally matches after a wrong flip combination), improving correction reliability at the cost of increased overhead.

### C. Multi-Key Variant

In a multi-key variant, multiple Feistel permutations with distinct keys K₁, K₂, …, K_m are applied, each producing an independent grid with its own set of hash nodes. The union of all hash nodes is used as the constraint set. This increases metadata overhead by a factor of m while providing m independent constraint graphs, improving robustness against adversarial or correlated error patterns.

### D. Adaptive Group Size

In an adaptive variant, the group size s is selected at encoding time based on the expected bit error rate p and the block length L, so as to minimize metadata overhead for a given target correction success probability. Given an estimate of p, the optimal s can be computed analytically or looked up from a pre-computed table.

### E. Tail Policy Variants

When N is not divisible by the group size s, the final group may contain fewer than s rows (or columns). In a "discard" tail policy, the partial final group is omitted and no hash node is created for it. In an "include" tail policy, a hash node is created for the partial group. The "include" policy provides slightly higher coverage at the cost of one additional hash node with non-uniform group size.
