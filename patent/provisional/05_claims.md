# CLAIMS

*(Note: Claims in a provisional application are not examined and are included here to support the disclosure. They will be refined by patent counsel before the non-provisional filing.)*

---

**1.** A computer-implemented method of encoding a data block for error correction, the method comprising:

applying, by one or more processors, a keyed invertible permutation to indices of bits of a data block of length L bits to produce a permuted ordering of the bits;

arranging bits of the data block in the permuted ordering into a two-dimensional grid of N rows and N columns, wherein N = ⌈√L⌉;

computing, for each of a plurality of row groups of the grid, a respective row hash digest over the bits of that row group;

computing, for each of a plurality of column groups of the grid, a respective column hash digest over the bits of that column group; and

storing the row hash digests and the column hash digests as error-correction metadata associated with the data block.

---

**2.** A computer-implemented method of correcting bit-flip errors in a received data block, the received data block being associated with error-correction metadata comprising stored row hash digests and stored column hash digests, the method comprising:

arranging bits of the received data block into a two-dimensional grid of N rows and N columns using a permutation used during encoding of the data block;

computing recomputed row hash digests over row groups of the two-dimensional grid and recomputed column hash digests over column groups of the two-dimensional grid;

identifying as mismatched each hash node for which the recomputed hash digest differs from the stored hash digest, and identifying as matched each hash node for which the recomputed hash digest equals the stored hash digest;

constructing a constraint graph comprising a plurality of nodes, each node corresponding to a hash node, and a plurality of edges, each edge connecting two nodes whose covered source bit indices have a non-empty intersection;

iteratively performing, for each mismatched node selected in a processing order:

&nbsp;&nbsp;&nbsp;&nbsp;(a) collecting, as intersection indices, source bit indices covered by the selected mismatched node that are also covered by at least one mismatched neighboring node in the constraint graph;

&nbsp;&nbsp;&nbsp;&nbsp;(b) excluding from a candidate index set any source bit indices covered by the selected mismatched node that are also covered by at least one matched neighboring node in the constraint graph;

&nbsp;&nbsp;&nbsp;&nbsp;(c) enumerating, for successive flip counts k = 1, 2, 3, …, all combinations of k indices from the candidate index set, tentatively applying each combination as bit-flips to the two-dimensional grid, computing a score equal to a count of hash nodes whose recomputed digest matches the stored digest after the tentative flip, and committing the combination achieving the highest score; and

repeating the iterative performing until no mismatched nodes remain or no further improvement in total matched node count is achievable; and

inverting the permutation on the corrected two-dimensional grid to recover corrected source bits.

---

**3.** A system for error-correctable data storage, the system comprising:

one or more processors; and

a non-transitory computer-readable medium storing instructions that, when executed by the one or more processors, cause the system to:

&nbsp;&nbsp;&nbsp;&nbsp;encode a data block by performing the method of claim 1; and

&nbsp;&nbsp;&nbsp;&nbsp;decode a received data block by performing the method of claim 2.

---

**4.** The method of claim 1, wherein the permutation is implemented as a multi-round Feistel network using a cryptographic hash function as a round function.

---

**5.** The method of claim 4, wherein the Feistel network uses a cycle-walking technique to produce a bijection on integer domains whose size is not a power of two, wherein the cycle-walking technique comprises repeatedly re-applying the Feistel cipher to a candidate output index until the candidate output index falls within the domain {0, 1, …, L-1}.

---

**6.** The method of claim 4, wherein the cryptographic hash function is SHA-256.

---

**7.** The method of claim 4, wherein the Feistel network comprises at least eight rounds.

---

**8.** The method of claim 4, wherein the Feistel network is parameterized by a secret key of at least 128 bits, the secret key being shared between an encoder performing the method of claim 1 and a decoder performing the method of claim 2.

---

**9.** The method of claim 1, wherein the grid is zero-padded with zero-valued bits at positions N²−L through N²−1 when L is not a perfect square.

---

**10.** The method of claim 1, wherein the row hash digests and column hash digests are computed as cyclic redundancy check (CRC) digests.

---

**11.** The method of claim 10, wherein the CRC digests are 32-bit CRC-32 digests computed using the polynomial 0xEDB88320.

---

**12.** The method of claim 1, wherein the row hash digests and column hash digests are computed as GF(2) random linear hash digests of width h bits, wherein each output bit of the digest is computed as a bitwise XOR over a random subset of the input bits, and wherein the false-positive probability per node is 2⁻ʰ.

---

**13.** The method of claim 1, wherein each row group consists of a single row of the grid and each column group consists of a single column of the grid, such that N row hash digests and N column hash digests are computed, yielding a total metadata overhead of 2Nh bits, wherein h is the hash digest width in bits, and wherein the overhead ratio relative to the data block scales as O(1/√L).

---

**14.** The method of claim 1, wherein each row group consists of s consecutive rows of the grid and each column group consists of s consecutive columns of the grid, wherein s ≥ 2.

---

**15.** The method of claim 2, wherein the processing order comprises selecting mismatched nodes in ascending order of their covered source bit count.

---

**16.** The method of claim 2, wherein the processing order further comprises, as a secondary sort criterion, selecting mismatched nodes having fewer mismatched neighboring nodes before mismatched nodes having more mismatched neighboring nodes.

---

**17.** The method of claim 2, wherein step (a) further comprises collecting, as free indices, source bit indices covered by the selected mismatched node that are not covered by any matched neighboring node, and wherein the candidate index set comprises both the intersection indices and the free indices.

---

**18.** The method of claim 2, wherein, when no combination at the current flip count k improves the total matched node count, the flip count is incremented by one before enumerating the next level of combinations.

---

**19.** The method of claim 2, further comprising verifying, after the iterative performing, that all hash nodes in the constraint graph are matched, and outputting a correction success indicator.

---

**20.** The method of claim 1, wherein the data block comprises weight parameters of a neural network model stored in a memory device.

---

**21.** The method of claim 1, wherein the data block is stored in a DRAM memory device.

---

**22.** The method of claim 1, wherein the data block is stored in a NAND flash memory device, and wherein burst bit-flip errors arising from cell-to-cell interference in the NAND flash memory device are scattered uniformly across the two-dimensional grid by the permutation.

---

**23.** The system of claim 3, further comprising dedicated hash computation hardware configured to compute the row hash digests and column hash digests in parallel for all row groups and column groups in a single pass over the two-dimensional grid.

---

**24.** The system of claim 3, wherein the constraint graph is implemented as a bipartite graph comprising N row nodes and N column nodes, wherein each row node is connected to each column node by an edge of weight one, representing the single source bit index shared between the corresponding row and column.

---

**25.** A non-transitory computer-readable medium storing instructions that, when executed by one or more processors, cause the processors to perform the method of claim 1 or the method of claim 2.
