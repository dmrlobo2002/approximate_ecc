# CLAIMS

What is claimed is:

---

**1.** A computer-implemented method of encoding a data block for error correction, the method comprising:

applying, by one or more processors, a keyed invertible permutation to bit indices of a data block of length L bits to produce a permuted ordering of the bit indices;

arranging bits of the data block in the permuted ordering into a two-dimensional grid of N rows and N columns, wherein N equals the ceiling of the square root of L;

computing, for each of a plurality of non-overlapping row groups of the two-dimensional grid, a respective row hash digest over bits of the row group;

computing, for each of a plurality of non-overlapping column groups of the two-dimensional grid, a respective column hash digest over bits of the column group; and

storing the row hash digests and the column hash digests as error-correction metadata associated with the data block,

wherein a total number of bits of the error-correction metadata scales as O(1/√L) relative to the data block as the length L increases.

---

**2.** A computer-implemented method of correcting bit-flip errors in a received data block, the received data block being associated with error-correction metadata comprising a plurality of stored row hash digests and a plurality of stored column hash digests, the method comprising:

arranging, by one or more processors, bits of the received data block into a two-dimensional grid of N rows and N columns using the same permutation used when encoding the data block;

computing recomputed row hash digests for a plurality of row groups of the two-dimensional grid and recomputed column hash digests for a plurality of column groups of the two-dimensional grid;

identifying, for each hash node in a plurality of hash nodes corresponding to the row groups and column groups, whether the hash node is mismatched, wherein a hash node is mismatched when its recomputed hash digest differs from its stored hash digest, and matched otherwise;

constructing a constraint graph comprising a plurality of nodes, each node corresponding to one of the plurality of hash nodes, and a plurality of edges, wherein an edge exists between two nodes if and only if the set of source bit indices covered by the first node and the set of source bit indices covered by the second node have a non-empty intersection;

performing a constraint-guided bit-flip search comprising iteratively, for each mismatched node selected from the plurality of hash nodes in a processing order:

&nbsp;&nbsp;&nbsp;&nbsp;(a) determining a candidate index set comprising source bit indices covered by the selected mismatched node that are not covered exclusively by matched neighboring nodes in the constraint graph;

&nbsp;&nbsp;&nbsp;&nbsp;(b) for successive flip counts k beginning at k=1, enumerating combinations of k source bit indices from the candidate index set, tentatively applying each combination as bit-flips to the two-dimensional grid, computing a score equal to a count of matched hash nodes across the entire plurality of hash nodes after the tentative bit-flips, and committing the combination achieving the highest score;

&nbsp;&nbsp;&nbsp;&nbsp;(c) updating the matched or mismatched status of each hash node affected by committed bit-flips; and

repeating the iterative constraint-guided bit-flip search until no mismatched hash nodes remain or until no further improvement in matched node count is achievable; and

inverting the permutation applied to the corrected two-dimensional grid to recover corrected source bits.

---

**3.** A system for error-correctable data storage comprising:

one or more processors; and

a non-transitory computer-readable medium storing instructions that, when executed by the one or more processors, cause the system to perform:

&nbsp;&nbsp;&nbsp;&nbsp;encoding a data block by performing the method of claim 1; and

&nbsp;&nbsp;&nbsp;&nbsp;decoding a received version of the data block by performing the method of claim 2.

---

**4.** A non-transitory computer-readable medium storing instructions that, when executed by one or more processors, cause the processors to perform the method of claim 1.

---

**5.** A non-transitory computer-readable medium storing instructions that, when executed by one or more processors, cause the processors to perform the method of claim 2.

---

**6.** The method of claim 1, wherein the keyed invertible permutation is implemented as a multi-round Feistel network comprising a plurality of Feistel rounds, each round applying a round function to produce a pseudorandom transformation of a right-half value.

---

**7.** The method of claim 6, wherein the multi-round Feistel network uses a cycle-walking technique to produce a bijection on the integer domain {0, 1, …, L−1} when L is not a power of two, the cycle-walking technique comprising re-applying the Feistel network to a candidate output index until the candidate output index falls within the integer domain {0, 1, …, L−1}.

---

**8.** The method of claim 6, wherein the round function comprises a cryptographic hash function.

---

**9.** The method of claim 8, wherein the cryptographic hash function is SHA-256.

---

**10.** The method of claim 6, wherein the multi-round Feistel network comprises at least eight rounds.

---

**11.** The method of claim 6, wherein the multi-round Feistel network is parameterized by a secret key of at least 128 bits shared between an encoder performing the method of claim 1 and a decoder performing the method of claim 2.

---

**12.** The method of claim 1, wherein the two-dimensional grid is zero-padded at positions L through N²−1 with zero-valued bits when L is not a perfect square.

---

**13.** The method of claim 1, wherein each row group consists of exactly one row of the two-dimensional grid and each column group consists of exactly one column of the two-dimensional grid, such that N row hash digests and N column hash digests are computed, the error-correction metadata comprising 2Nh bits where h is a hash digest width in bits.

---

**14.** The method of claim 1, wherein each row group consists of s consecutive rows of the two-dimensional grid and each column group consists of s consecutive columns of the two-dimensional grid, wherein s is an integer greater than or equal to two.

---

**15.** The method of claim 1, wherein the row hash digests and the column hash digests are cyclic redundancy check (CRC) digests.

---

**16.** The method of claim 15, wherein the CRC digests are 32-bit CRC digests computed using the generator polynomial 0xEDB88320.

---

**17.** The method of claim 1, wherein the row hash digests and the column hash digests are GF(2) random linear hash digests of width h bits, wherein each output bit of a digest is computed as a bitwise exclusive-OR over a subset of the input bits, the subset being determined by a random binary matrix derived from a seed value.

---

**18.** The method of claim 2, wherein the processing order comprises selecting mismatched nodes in ascending order of the count of source bit indices covered by the node.

---

**19.** The method of claim 2, wherein step (a) comprises:

collecting, as intersection indices, source bit indices covered by the selected mismatched node that are also covered by at least one mismatched neighboring node in the constraint graph;

collecting, as free indices, source bit indices covered by the selected mismatched node that are not covered by any matched neighboring node in the constraint graph; and

excluding from the candidate index set source bit indices covered by the selected mismatched node that are covered by at least one matched neighboring node in the constraint graph.

---

**20.** The method of claim 19, wherein within the candidate index set, intersection indices are enumerated before free indices during the combination enumeration of step (b).

---

**21.** The method of claim 2, wherein, when no combination of k source bit indices from the candidate index set improves the total matched node count, the flip count k is incremented before enumerating combinations of k+1 source bit indices.

---

**22.** The method of claim 2, further comprising verifying, after the constraint-guided bit-flip search terminates, that all hash nodes in the plurality of hash nodes are matched, and producing a correction success indicator.

---

**23.** The method of claim 2, wherein the constraint graph is a complete bipartite graph comprising N row nodes and N column nodes, wherein each edge of the bipartite graph has a weight of one corresponding to exactly one shared source bit index, and wherein the method further comprises, prior to the constraint-guided bit-flip search, identifying pairs of mismatched nodes connected by a single edge as candidates for single-bit-flip correction.

---

**24.** The method of claim 1 or claim 2, wherein the data block comprises weight parameters of a neural network model.

---

**25.** The method of claim 1 or claim 2, wherein the data block is stored in a dynamic random-access memory (DRAM) device.

---

**26.** The method of claim 1 or claim 2, wherein the data block is stored in a NAND flash memory device, and wherein burst bit-flip errors caused by cell-to-cell interference in the NAND flash memory device are scattered across the two-dimensional grid by the permutation.

---

**27.** The system of claim 3, further comprising a hardware encoder unit comprising a plurality of parallel hash computation circuits, wherein the plurality of parallel hash computation circuits compute the row hash digests for all row groups simultaneously and the column hash digests for all column groups simultaneously in a single pass over data of the two-dimensional grid.

---

**28.** The system of claim 3, further comprising a priority queue configured to order mismatched hash nodes for processing in ascending order of covered source bit count.

---

**29.** The method of claim 1, wherein the error-correction metadata overhead ratio relative to the data block length L is at most 2h/(s·√L), wherein h is a hash digest width in bits and s is a row or column group size, and wherein the overhead ratio decreases as L increases.

---

**30.** The method of claim 2, wherein the permutation scatters contiguous burst bit-flip errors uniformly across the two-dimensional grid such that a burst of b consecutive bit-flips in the data block is distributed across at least b/2 distinct row groups and at least b/2 distinct column groups of the two-dimensional grid in expectation.
