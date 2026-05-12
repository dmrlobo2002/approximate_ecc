# BRIEF DESCRIPTION OF THE DRAWINGS

The accompanying drawings, which are incorporated in and form a part of this specification, illustrate embodiments of the invention and together with the description serve to explain the principles of the invention.

---

**FIG. 1** is a block diagram illustrating the encoding pipeline of an embodiment of the present invention, showing a source data block passing through a Feistel permutation stage, a two-dimensional grid arrangement stage, a row/column hash computation stage, and storage of hash digests as error-correction metadata.

**FIG. 2** is a block diagram illustrating the decoding pipeline of an embodiment of the present invention, showing a received data block being arranged into a two-dimensional grid, hash digests being recomputed and compared to stored values, a constraint graph being constructed from mismatched hash nodes, and a constraint-guided bit-flip search producing a corrected output block.

**FIG. 3** is a diagram illustrating an example constraint graph for a 4×4 grid embodiment, showing four row hash nodes and four column hash nodes connected by edges representing shared bit coverage, with mismatched nodes visually distinguished from matched nodes.

**FIG. 4** is a diagram illustrating the matched-neighbor pinning concept, showing, for an example mismatched node, which bit indices are classified as intersection indices (shared with mismatched neighbors), free indices (not covered by any matched neighbor), and pinned indices (covered by matched neighbors, excluded from search).

**FIG. 5** is a flowchart illustrating the steps of the Feistel permutation used during encoding, including the multi-round forward Feistel operation and the cycle-walking loop used to handle domains whose size is not a power of two.

**FIG. 6** is a flowchart illustrating the steps of the constraint-guided bit-flip search algorithm, including node selection by covered-bit count, candidate index prioritization, combination enumeration, global scoring, and commitment of the best-scoring flip combination.

**FIG. 7** is a graph showing empirical overhead ratio (metadata bits / source bits) as a function of block length L for one or more hash configurations of the present invention, compared against the analytical overhead of BCH codes configured for equivalent correction capability, illustrating the O(1/√L) scaling advantage of the present invention.

**FIG. 8** is a graph showing empirical correction success rate as a function of bit-flip count (and bit error rate) for one or more hash configurations of the present invention at a block length of 4096 bits, demonstrating the ability to fully correct 200 or more bit-flips at 100% metadata overhead.

**FIG. 9** is a pair of graphs comparing correction success rate and solver search effort (number of hash evaluations) for random bit-flip errors and burst bit-flip errors of equivalent total count, demonstrating that the Feistel permutation renders the decoder's performance statistically equivalent for both error models.

**FIG. 10** is a system diagram illustrating a hardware embodiment of the present invention, showing a data storage system comprising an encoding unit, a hash computation unit, a metadata storage region, a decoding unit with a constraint graph data structure, and a corrected-output register.
