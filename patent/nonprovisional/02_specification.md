# SPECIFICATION

---

## CROSS-REFERENCE TO RELATED APPLICATIONS

This application claims the benefit of U.S. Provisional Patent Application No. [PROVISIONAL NUMBER], filed [PROVISIONAL FILING DATE], the disclosure of which is incorporated herein by reference in its entirety.

---

## TECHNICAL FIELD

The present invention relates to error detection and correction in digital storage and communication systems, and more particularly to a method and system for correcting bit-flip errors in data blocks using two-dimensional hash constraint grid encoding, Feistel-based error diffusion, and constraint-graph-guided combinatorial decoding, without requiring Galois field arithmetic.

---

## BACKGROUND

Modern digital storage and communication systems are susceptible to bit-flip errors arising from physical phenomena including ionizing radiation, dynamic random-access memory (DRAM) row-hammer disturbance, NAND flash cell wear-out, and high-energy particle strikes. As device geometries decrease and supply voltages are scaled to reduce power consumption, bit-flip error rates increase and the distribution of error counts per block becomes wider. In safety-critical applications such as autonomous vehicle inference, aerospace computing, and medical imaging, uncorrected bit-flip errors can produce silent data corruption with potentially catastrophic consequences.

Traditional error-correcting codes (ECCs) address bit-flip errors through algebraic redundancy. Bose-Chaudhuri-Hocquenghem (BCH) codes are widely deployed binary linear codes that correct up to t arbitrary bit errors in a codeword of length n using approximately 2t·⌈log₂(n+1)⌉ parity bits. BCH decoding requires the Berlekamp-Massey algorithm and Chien search over a Galois field GF(2^m), necessitating dedicated finite-field arithmetic hardware or software libraries. Reed-Solomon codes provide multi-symbol error correction at the cost of even greater Galois field complexity. Low-density parity-check (LDPC) codes approach the Shannon capacity but require iterative belief-propagation decoding with hundreds of message-passing iterations, lengthy offline parity-matrix design, and fixed code rates.

A significant practical limitation of BCH codes in high-reliability applications is the "honest-t problem": because errors are distributed statistically, a BCH code must be parameterized at a correction capacity t substantially larger than the mean error count — typically the 95th or 99th percentile of the error distribution — to guarantee the required success rate. This inflates the parity overhead by a factor of two to five over what would be required for the mean error count alone.

Further, BCH codes are designed for independent random error models. Burst errors — contiguous sequences of bit-flips arising from a single physical event such as a flash memory cell disturb or a DRAM row activation — require substantially higher t values if they fall within a single codeword block. Handling burst errors with BCH codes requires either a separate burst-error-correcting code design or memory interleaving, adding system complexity and latency.

Additionally, the metadata overhead of BCH codes scales as Θ(t·log L) bits for a block of L bits. For a fixed bit error rate p (so t = p·L), the overhead ratio relative to the data block scales as Θ(p·log L), which grows with block size. There is no natural advantage from processing larger blocks.

Accordingly, there is a need in the art for an error correction approach that achieves lower overhead than BCH codes at equivalent correction capability for high bit error rates, handles burst errors natively, does not require Galois field arithmetic, and provides overhead that decreases as block size increases.

---

## SUMMARY OF EMBODIMENTS

The present invention provides a method and system for approximate bit-flip error correction using two-dimensional hash constraint grid encoding and graph-guided combinatorial decoding.

In a first embodiment, a computer-implemented method of encoding a data block for error correction comprises: applying a keyed, invertible permutation to bit indices of the data block to produce a permuted ordering; arranging the bits in the permuted ordering into a two-dimensional grid of N rows and N columns, wherein N = ⌈√L⌉ and L is the block length in bits; computing hash digests over non-overlapping groups of rows of the grid and over non-overlapping groups of columns of the grid; and storing the hash digests as error-correction metadata associated with the data block.

In a second embodiment, a computer-implemented method of correcting bit-flip errors in a received data block comprises: reconstructing a two-dimensional grid from the received data block using the same permutation; recomputing and comparing row and column hash digests against stored metadata to identify mismatched hash nodes; constructing a constraint graph in which nodes represent hash digest computations and edges connect nodes with overlapping bit coverage; and performing a greedy, constraint-guided bit-flip search that selects mismatched nodes in order of ascending covered-bit count, collects candidate indices while excluding bits pinned by matched neighboring nodes, enumerates bit-flip combinations of increasing size, scores each combination by total matched nodes, and commits the best combination.

In a third embodiment, a system for error-correctable data storage comprises one or more processors and a non-transitory computer-readable medium storing instructions for performing the encoding and decoding methods.

---

## BRIEF DESCRIPTION OF THE DRAWINGS

*(See 05_drawings_list.md)*

---

## DETAILED DESCRIPTION OF EMBODIMENTS

The following detailed description is presented to enable any person skilled in the art to make and use the invention. For purposes of explanation, specific details are set forth to provide a thorough understanding of the present invention. However, it will be apparent to one skilled in the art that these specific details are not required to practice the invention. Descriptions of specific applications are provided only as examples. Various modifications to the described embodiments will be readily apparent to those skilled in the art, and the principles defined herein may be applied to other embodiments without departing from the spirit and scope of the invention. Thus, the present invention is not intended to be limited to the embodiments shown, but is to be accorded the widest scope consistent with the principles and features disclosed herein.

### I. System Overview

Referring to FIG. 1, an encoding pipeline 100 according to an embodiment of the present invention is shown. A source data block 102 of L bits is provided as input. The data block 102 passes through a Feistel permutation stage 104, which reorders the bit indices according to a keyed, invertible permutation π. The permuted bits are arranged into a two-dimensional grid 106 comprising N rows and N columns, where N = ⌈√L⌉. A hash computation stage 108 computes hash digests over non-overlapping groups of rows and groups of columns of the grid 106. The resulting hash digests, collectively referred to as hash metadata 110, are stored in a metadata storage region associated with the data block 102.

Referring to FIG. 2, a decoding pipeline 200 according to an embodiment is shown. A received data block 202, which may contain bit-flip errors relative to the original data block 102, is arranged into a two-dimensional grid 204 using the same permutation π applied during encoding. A hash recomputation and comparison stage 206 computes row and column digests over the received grid 204 and compares them against the stored hash metadata 110. Nodes for which the recomputed digest differs from the stored digest are identified as mismatched hash nodes 208. A constraint graph construction stage 210 builds a graph from the hash nodes and their bit-coverage overlaps. A constraint-guided search stage 212 performs the bit-flip correction search using the constraint graph. The output is a corrected data block 214, obtained by applying the inverse permutation π⁻¹ to the corrected grid.

### II. Feistel Permutation

#### A. Purpose and Properties

The permutation π serves dual purposes. First, it provides deterministic, keyed reordering reproducible from a shared key K at both the encoder and decoder. Second, it scatters contiguous burst errors uniformly across the two-dimensional grid. A burst of b consecutive bit-flips at source positions {i, i+1, …, i+b−1} is mapped by π to b approximately uniformly distributed positions in the grid, converting the burst correction problem into the statistically equivalent random-error problem. Without this scattering, b consecutive flips would affect only one or two adjacent rows of the grid, overloading those row hash nodes while leaving column nodes with minimal mismatch signal.

The permutation π: {0,…,L−1} → {0,…,L−1} is a bijection (one-to-one and onto), ensuring that no bits are duplicated or lost in the reordering. The inverse permutation π⁻¹ is efficiently computable from the same key K.

#### B. Feistel Network Construction

The permutation is implemented as an R-round balanced Feistel network, where R ≥ 4. In a preferred embodiment, R = 8. Each round uses a keyed round function F_K: Z → Z, where Z = {0, 1}^(⌈log₂(L)⌉/2). In a preferred embodiment, the round function is SHA-256, wherein the input to SHA-256 is the concatenation of: the right-half value, the round index r encoded as a 4-byte integer, and the 16-byte secret key K. The SHA-256 output is truncated to the required bit width for the right half.

For an index i ∈ {0,…,L−1}, the forward Feistel permutation proceeds as follows. The index i is represented in binary and split into a left half L_i comprising the most significant ⌈log₂(L)⌉/2 bits and a right half R_i comprising the remaining bits. For each round r from 0 to R−1:

    new_R_i = L_i XOR truncate(F_K(R_i || r), |L_i|)
    L_i = R_i
    R_i = new_R_i

After R rounds, the left and right halves are concatenated to form a candidate index c. If c ∈ {0,…,L−1}, then π(i) = c. If c ∉ {0,…,L−1} (i.e., the candidate falls outside the domain), the cycle-walking technique is applied: the index i is replaced by c and the Feistel cipher is applied again to c, repeating until a valid index is obtained. The expected number of applications before a valid index is found is at most L/(L−{invalid range size}) ≤ 2 for typical L values. This cycle-walking technique guarantees that π is a bijection on {0,…,L−1} for arbitrary L.

The inverse permutation π⁻¹ is computed by applying the R Feistel rounds in reverse order (r = R−1, …, 0) with left and right halves swapped at each round, followed by the same cycle-walking procedure. The Feistel structure guarantees that π⁻¹ correctly recovers i from π(i) for all i ∈ {0,…,L−1}.

Referring to FIG. 5, a flowchart 500 illustrates the forward Feistel permutation steps 502–508 and the inverse permutation steps 510.

#### C. Application to Data Block

The permuted data block B' is defined by B'[π(i)] = B[i] for all i ∈ {0,…,L−1}. That is, the source bit at position i in the original data block B is placed at position π(i) in the permuted block B'. The permuted block B' is then arranged into the two-dimensional grid G as described in Section III.

### III. Two-Dimensional Grid Layout

The permuted block B' of L bits is arranged into a two-dimensional array G of N rows and N columns, where N = ⌈√L⌉. The grid G is populated in row-major order: G[r][c] = B'[r·N + c] for r·N + c < L, and G[r][c] = 0 for r·N + c ≥ L. The zero-padding bits at positions L through N²−1 are fixed and known to both encoder and decoder; they are treated as non-flippable during decoding.

The encoder maintains two index mappings: source_to_grid[i] = (r, c) such that G[r][c] = B'[π(i)], and grid_to_source[(r, c)] = i such that B[i] = G[r][c] before permutation. These mappings are derived deterministically from π and N and do not require explicit storage.

In exemplary embodiments:

- L = 256 bits: N = 16, grid dimensions 16×16
- L = 1,024 bits: N = 32, grid dimensions 32×32
- L = 4,096 bits: N = 64, grid dimensions 64×64
- L = 16,384 bits: N = 128, grid dimensions 128×128

### IV. Hash Node Construction

#### A. Row Hash Nodes

The rows of grid G are partitioned into non-overlapping groups of s consecutive rows, where s ≥ 1 is a configurable group size parameter. For each group g ∈ {0, 1, …, ⌈N/s⌉−1}, a row hash node n_g^(row) is defined with the following attributes:

- **node_id**: a unique string identifier (e.g., "row_g")
- **axis**: "row"
- **group_rows**: the set of row indices {g·s, g·s+1, …, min((g+1)·s−1, N−1)} belonging to group g
- **covered_source_indices**: the set of source bit indices i ∈ {0,…,L−1} such that the grid position grid_to_source(r, c) ∈ group_rows for some column c; equivalently, the set of source bits whose permuted positions lie in the rows of group g
- **digest**: the hash digest computed over the bits {G[r][c] : r ∈ group_rows, c ∈ {0,…,N−1}}, with the bits serialized in row-major order into bytes and the hash function applied to the resulting byte sequence

In a preferred embodiment with s = 1, each of the N rows of the grid produces one row hash node, yielding N row hash nodes. The covered_source_indices of each row hash node consists of exactly N source bit indices.

#### B. Column Hash Nodes

Analogously, the columns of grid G are partitioned into groups of s consecutive columns. For each group g ∈ {0, 1, …, ⌈N/s⌉−1}, a column hash node n_g^(col) is defined with attributes analogous to those of the row hash nodes, with axis "column" and covered_source_indices comprising the source bits whose permuted positions lie in the columns of group g.

In a preferred embodiment with s = 1, N column hash nodes are produced. The total number of hash nodes is 2N.

#### C. Hash Functions

In preferred embodiments, the hash function used to compute digests is one of:

1. **CRC-8**: An 8-bit cyclic redundancy check with generator polynomial 0x07 (CCITT). The false positive probability — the probability that a corrupted digest accidentally equals the stored digest — is 2⁻⁸ ≈ 0.39%.

2. **CRC-16**: A 16-bit cyclic redundancy check. False positive probability: 2⁻¹⁶ ≈ 1.5×10⁻³%.

3. **CRC-32**: A 32-bit cyclic redundancy check with generator polynomial 0xEDB88320 (IEEE 802.3). False positive probability: 2⁻³² ≈ 2.3×10⁻¹⁰.

4. **CRC-64**: A 64-bit cyclic redundancy check. False positive probability: 2⁻⁶⁴ ≈ 5.4×10⁻²⁰.

5. **GF(2) Random Linear Hash (SimHash)**: A hash of configurable width h bits computed as a random linear map over GF(2). Each of the h output bits is computed as the bitwise XOR of a random subset of the input bits, equivalently as a matrix-vector product over GF(2). The random subsets are derived deterministically from a seed (which may be the same key K used for the Feistel permutation). The false positive probability per hash node is 2⁻ʰ, identical to that of a CRC of width h.

One of ordinary skill in the art will recognize that other hash functions providing similar false-positive probability guarantees may be substituted, including MurmurHash, xxHash, and SHA-256 truncated to h bits.

#### D. Overhead Formula

The total error-correction metadata overhead in bits is:

    overhead_bits = 2 · ⌈N/s⌉ · h

where N = ⌈√L⌉, s is the group size, and h is the hash width in bits. The overhead ratio relative to the data block of L bits is:

    overhead_ratio = 2 · ⌈N/s⌉ · h / L ≈ 2h / (s · √L)         (Equation 1)

For fixed h and s, this scales as O(1/√L), decreasing as block size L increases. In contrast, BCH overhead for a target bit error rate p scales as Θ(p · L · log L) bits, yielding an overhead ratio of Θ(p · log L), which grows with L.

In a preferred embodiment with L = 4,096, N = 64, s = 1, and h = 32 (CRC-32):

    overhead_bits = 2 · 64 · 32 = 4,096 bits = 100% overhead

Empirical results show this configuration achieves full correction of 200 or more bit-flips (bit error rate ≥ 5%) with ≥ 95% success rate. BCH codes require approximately 5,200 parity bits (174% overhead) for equivalent correction capability at this block size and error rate.

### V. Constraint Graph

#### A. Definition

After computing the hash nodes, the encoder or decoder constructs a constraint graph G_C = (V, E), where V is the set of all 2·⌈N/s⌉ hash nodes. An undirected edge (u, v) ∈ E exists if and only if:

    covered_source_indices(u) ∩ covered_source_indices(v) ≠ ∅

Each edge (u, v) carries a weight w(u,v) = |covered_source_indices(u) ∩ covered_source_indices(v)|.

#### B. Structure in the Preferred Embodiment

In the preferred embodiment with s = 1, the constraint graph G_C is a complete bipartite graph K_{N,N} with N row nodes and N column nodes. Each row node r_i has covered_source_indices = {source bits in row i} and each column node c_j has covered_source_indices = {source bits in column j}. The intersection of r_i and c_j consists of exactly one source bit index: the bit whose permuted position is (i, j) in the grid. Thus, each edge has weight 1, and there are N² edges total.

This bipartite structure has the key property that a single bit-flip at grid position (i, j) corrupts exactly one row digest (row node r_i) and one column digest (column node c_j). The mismatched pair (r_i, c_j) is directly connected by an edge of weight 1, pointing the decoder to the single candidate flip position at the intersection.

Referring to FIG. 3, a constraint graph 300 for a 4×4 grid embodiment is illustrated, showing row nodes R0–R3 (302) and column nodes C0–C3 (304) connected by 16 edges 306. In the example shown, nodes R1 and C2 are mismatched 308, indicating a single flip at grid position (1, 2). Matched nodes 310 are R0, R2, R3, C0, C1, and C3.

### VI. Decoding: Constraint-Guided Bit-Flip Search

#### A. Overview

The decoding procedure operates on the received grid G_r, the stored hash metadata 110, and the constraint graph G_C. Each hash node is labeled as either matched (recomputed digest equals stored digest) or mismatched (digests differ). The decoder's goal is to find a set of bit-flip positions that, when applied to G_r, converts all mismatched nodes to matched. Because the decoder cannot enumerate all 2^L possible bit patterns, it uses a greedy, constraint-guided search with the matched-neighbor pinning pruning heuristic.

Referring to FIG. 6, a flowchart 600 illustrates the decoding steps.

#### B. Node Processing Order (Step 602)

The decoder sorts the mismatched nodes in ascending order of their covered-bit count |covered_source_indices|. In the preferred embodiment with s = 1, all nodes cover exactly N bits, so the tiebreaker sorts by ascending count of mismatched neighbors in the constraint graph: nodes with fewer mismatched neighbors are processed first, as they are statistically more likely to be the last constraint affected by a small number of residual flips.

#### C. Candidate Index Collection and Matched-Neighbor Pinning (Steps 604)

For each mismatched node u selected for processing, the decoder computes the following disjoint subsets of covered_source_indices(u):

1. **Intersection indices I(u)**: source bit indices in covered_source_indices(u) that are also in covered_source_indices(v) for at least one mismatched neighbor v ∈ neighbors(u). These bits are implicated by multiple constraint violations and are the primary search candidates.

2. **Free indices F(u)**: source bit indices in covered_source_indices(u) that are not in covered_source_indices(v) for any matched neighbor v. These bits can be flipped without corrupting any already-correct constraint.

3. **Pinned indices P(u)**: source bit indices in covered_source_indices(u) that are in covered_source_indices(v) for at least one matched neighbor v. These bits are **excluded** from the candidate index set.

The candidate index set is C(u) = I(u) ∪ F(u). Note that I(u) ∪ F(u) ∪ P(u) = covered_source_indices(u) and the three sets are mutually disjoint.

Referring to FIG. 4, the matched-neighbor pinning concept 400 is illustrated for a mismatched row node 402 in a 4×4 grid. Intersection indices 404 (shared with mismatched column neighbors) and free indices (if any) form the candidate set 408. Pinned indices 406, covered by matched column neighbors, are excluded.

#### D. Combination Enumeration and Scoring (Steps 606–610)

For flip count k = 1, 2, 3, …, the decoder enumerates all combinations of k indices from C(u). For each combination {j_1, …, j_k} ⊆ C(u):

1. **Tentatively apply** k bit-flips: for each j_m, toggle G_r at the grid position corresponding to source index j_m.
2. **Recompute** hash digests for all nodes v ∈ V such that covered_source_indices(v) ∩ {j_1,…,j_k} ≠ ∅. In the preferred bipartite embodiment, at most 2k nodes are affected (one row node and one column node per flipped bit).
3. **Score** = total number of hash nodes v ∈ V for which the recomputed digest equals the stored digest.
4. **Revert** the tentative flips.

The decoder commits the flip combination achieving the highest score. If multiple combinations achieve the same highest score, the combination of smallest k is preferred, with ties broken arbitrarily.

#### E. Outer Iteration and Flip-Level Climbing (Steps 612–614)

The inner processing of each mismatched node is embedded in an outer iteration that repeats over all mismatched nodes. After each pass over all mismatched nodes, the decoder checks whether the total matched node count improved during the pass. If no improvement was achieved at the current maximum flip level K_max, K_max is incremented by one (flip-level climbing) and the next pass begins with the new ceiling. The outer iteration terminates when all nodes are matched or when the total matched node count has not improved over a configurable number of consecutive passes.

#### F. Output

After the outer iteration terminates, the corrected grid G_c is converted to a flat bit array in row-major order. The inverse Feistel permutation π⁻¹ is applied to recover the corrected source bits, yielding corrected block B_c satisfying B_c[i] = G_c[r][c] where (r, c) is the grid position corresponding to source index i.

### VII. Worked Example

To illustrate the complete encoding and decoding pipeline, consider a data block B of L = 16 bits and group size s = 1 with 8-bit CRC (CRC-8) hash digests.

**Encoding:**
Let B = {b_0, b_1, …, b_15} be the source bits. Applying the Feistel permutation π with key K produces a permuted block B'. B' is arranged into a 4×4 grid G (N = 4, no padding). Four row hash nodes R0–R3 and four column hash nodes C0–C3 are computed, each with an 8-bit CRC-8 digest, yielding 64 bits of hash metadata (50% overhead for a 16-bit block, per Equation 1: 2·4·8/16 = 4 → 400% for CRC-8; illustrative only — CRC-8 is preferred for L ≥ 256).

**Error injection:** Two bit-flips are injected at source indices 5 and 11 of the original block B.

**Decoding:** The received block B_r is arranged into grid G_r. Row and column CRC-8 digests are recomputed. Suppose the flipped bits, after permutation by π, fall at grid positions (1, 2) and (3, 0). Then nodes R1, R3, C0, and C2 are mismatched; nodes R0, R2, C1, and C3 are matched.

Constraint graph G_C is constructed (K_{4,4}). The decoder selects mismatched node R1, which has 2 mismatched neighbors (C2) and 2 matched neighbors... *(etc.)*. Following the candidate collection, pinning, and enumeration steps, the decoder identifies and commits the two corrective flips, restoring all 8 hash nodes to matched status. The corrected grid is converted back, and π⁻¹ is applied to recover the corrected source bits B_c = B.

### VIII. Hardware Embodiment

Referring to FIG. 10, a hardware embodiment system 1000 is illustrated. The system 1000 comprises: a Feistel permutation unit 1002 implementing the R-round SHA-256-keyed Feistel network in combinational and sequential logic, with a cycle-walking controller that iterates until a valid index is found; a grid mapping unit 1004 providing the source-to-grid and grid-to-source index translations; a CRC computation array 1006 comprising N parallel CRC units operating simultaneously over all row groups and N parallel CRC units operating simultaneously over all column groups, computing all 2N digests in a single pipeline pass over the grid data; a metadata register file 1008 storing the 2N baseline hash digests; a mismatch detection unit 1010 comparing stored and recomputed digests and driving the constraint graph labels; a constraint graph register 1012 maintaining the bipartite adjacency structure and matched/mismatched node labels; and a combinatorial search unit 1014 implementing the candidate index collection (including pin mask generation), combination enumeration, tentative flip-and-score, and commit logic.

The system 1000 is integrated with a data storage array 1018 (e.g., SRAM, DRAM, or flash) and a metadata storage region 1020 co-located with the data storage array. On a read operation, the data block 102 is read from storage array 1018 and passed through the decoding pipeline; on a write operation, the data block is passed through the encoding pipeline and both the data and hash metadata 110 are written to storage.

### IX. Applications

#### A. DRAM Memory Protection for AI Accelerator Weight Storage

In one application, the invention protects the weight matrices of deep neural networks (DNNs) stored in on-chip SRAM or off-chip DRAM within an AI accelerator chip. Weight matrices or sub-matrices of L bits are encoded and stored with hash metadata in a dedicated metadata region. During inference, weight blocks are read and decoded before being presented to the processing elements. The reduced overhead relative to BCH codes translates directly to lower silicon area and power for the metadata storage and ECC engine. The approximate nature of correction (probabilistic success at high BER) is acceptable in this application because DNN inference accuracy degrades gracefully with small residual per-weight errors.

#### B. NAND Flash Storage

In another application, the invention protects data pages in NAND flash storage, where high and variable bit error rates — driven by cell wear-out in multi-level cell (MLC) and triple-level cell (TLC) flash — produce error counts well above the correction capacity of traditional on-chip BCH codes. Flash write-disturb and read-disturb events frequently produce burst errors (contiguous flips within a page). The Feistel permutation neutralizes burst errors without requiring a separate interleaver, and the O(1/√L) overhead scaling is particularly advantageous as flash page sizes increase from 4 KB to 16 KB and beyond.

#### C. General-Purpose Memory ECC

In a further application, the invention is used as a general-purpose ECC scheme for any digital storage or transmission application requiring correction of a large number of bit-flip errors at lower overhead than BCH codes. The invention is particularly advantageous when the error count distribution has a heavy tail (high variance), since its correction capability extends to high flip counts without the overhead penalty incurred by BCH codes sized for the 95th or 99th percentile of the error distribution.

### X. Variants

#### A. Group Size Variants

Setting the group size parameter s > 1 reduces the number of hash nodes from 2N to 2⌈N/s⌉, proportionally reducing metadata overhead at the cost of increased candidate set size per node during decoding. For s = 2 and L = 4,096 (N = 64), the overhead at CRC-32 width reduces from 100% to 50%.

#### B. Hash Width Variants

The hash digest width h is a runtime parameter controlling the overhead-versus-false-positive tradeoff. Narrower hashes (CRC-8) provide lower overhead but higher false-positive probability, acceptable for applications with very high BER where the decoder makes many passes. Wider hashes (CRC-32, CRC-64) provide negligible false-positive probability, appropriate for demanding correction requirements.

#### C. Multi-Key Variant

Multiple independent permutations with distinct keys K_1, …, K_m yield m independent constraint graphs, increasing total metadata overhead by a factor of m but providing redundant constraint structures that improve robustness against adversarial or correlated error patterns and reduce decoder search complexity.

#### D. Adaptive Overhead

The group size s and hash width h can be selected adaptively at encoding time based on the expected bit error rate of the channel, the block size L, and a target correction success probability, enabling runtime tuning of the overhead-versus-reliability tradeoff without re-designing the code.
