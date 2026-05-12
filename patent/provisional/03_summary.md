# SUMMARY OF THE INVENTION

The present invention provides a system and method for approximate error correction of data blocks using a two-dimensional hash constraint grid with permutation-based error diffusion and a graph-guided combinatorial bit-flip search for decoding. The invention achieves correction of large numbers of bit-flip errors with metadata overhead that scales as O(1/√L) in the block length L, without requiring Galois field arithmetic, and with native resilience to burst errors.

## Encoding

In one aspect, the invention provides a method of encoding a data block for error correction, comprising: applying a keyed, invertible permutation to the bit indices of the data block to produce a permuted ordering, wherein the permutation is implemented as a multi-round Feistel network using a cryptographic hash function as a round function and cycle-walking to handle domains whose size is not a power of two; arranging the bits of the data block in the permuted ordering into a two-dimensional grid of N rows and N columns, wherein N is approximately the square root of the length L of the data block; computing hash digests over non-overlapping groups of consecutive rows of the grid and over non-overlapping groups of consecutive columns of the grid; and storing the hash digests as error-correction metadata associated with the data block.

## Decoding

In another aspect, the invention provides a method of correcting bit-flip errors in a received data block encoded by the above encoding method, comprising: arranging the received data block into the same two-dimensional grid using the same permutation; recomputing row and column hash digests and comparing them against the stored metadata to identify mismatched hash nodes; constructing a constraint graph in which nodes represent hash digest computations and edges connect pairs of nodes whose covered bit indices overlap; and performing a greedy, constraint-guided bit-flip search that iterates over mismatched nodes in order of ascending covered-bit count, enumerates bit-flip combinations within candidate indices that exclude bits pinned by already-matched neighboring nodes, and commits the combination that maximizes the total count of matched nodes globally.

## System

In yet another aspect, the invention provides a system for error-correctable data storage comprising one or more processors and a non-transitory computer-readable medium storing instructions that, when executed, cause the system to perform the encoding and decoding methods above. A hardware embodiment further comprises dedicated hash computation units for row and column digest computation and a priority queue for node ordering.

## Key Advantages

The present invention provides the following advantages over the prior art:

1. **Lower overhead at equivalent correction capability.** At a block length of 4,096 bits, the invention corrects 200 or more bit-flips (bit error rate ≥ 5%) using approximately 100% metadata overhead, compared to approximately 174% overhead required by BCH codes for equivalent correction capability.

2. **Favorable overhead scaling with block size.** The overhead ratio of the invention scales as O(1/√L), decreasing as block length increases, whereas BCH overhead for a fixed bit error rate remains approximately constant or grows. At a block length of 16,384 bits, the overhead decreases to approximately 50% for the same hash configuration.

3. **Burst error resilience.** The Feistel permutation applied during encoding scatters contiguous burst errors uniformly across the grid, rendering them statistically indistinguishable from random errors from the decoder's perspective. This eliminates the need for a distinct burst-error-correcting code.

4. **No Galois field arithmetic.** The invention uses only standard hash functions (e.g., SHA-256, CRC-32) and combinatorial search operations, requiring no finite-field arithmetic hardware or software libraries.

5. **Runtime tunability.** The overhead-versus-correction tradeoff can be adjusted at deployment time by selecting a different hash digest width or group size without re-encoding the data structure.

6. **Reduced decoder complexity.** Empirical measurements show the invention requires approximately 47 times fewer operations than BCH algebraic decoding for equivalent correction at 5% bit error rate, using hash evaluations rather than Galois field multiplications.
