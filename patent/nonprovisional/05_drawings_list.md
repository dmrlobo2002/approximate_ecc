# BRIEF DESCRIPTION OF THE DRAWINGS

The accompanying drawings, which are incorporated in and constitute a part of this specification, illustrate one or more embodiments of the invention and together with the description serve to explain the principles of the invention. In the drawings:

---

**FIG. 1** is a block diagram illustrating an encoding pipeline 100 according to an embodiment of the present invention, comprising a source data block 102, a Feistel permutation stage 104, a two-dimensional grid 106, a hash computation stage 108, and hash metadata storage 110.

**FIG. 2** is a block diagram illustrating a decoding pipeline 200 according to an embodiment of the present invention, comprising a received data block 202, a grid reconstruction stage 204, a hash recomputation and comparison stage 206, a mismatched node set 208, a constraint graph construction stage 210, a constraint-guided search stage 212, and a corrected output block 214.

**FIG. 3** is a diagram illustrating a constraint graph 300 for a 4×4 grid embodiment, showing row hash nodes 302 (R0–R3) and column hash nodes 304 (C0–C3), wherein edges 306 connect each row node to each column node, and wherein mismatched nodes 308 are visually distinguished from matched nodes 310.

**FIG. 4** is a diagram illustrating the matched-neighbor pinning concept 400 for an example mismatched row node 402, showing intersection indices 404 shared with mismatched column neighbors, pinned indices 406 covered by matched column neighbors and excluded from search, and the resulting pruned candidate index set 408.

**FIG. 5** is a flowchart illustrating the steps of a Feistel permutation method 500, comprising an initialization step 502, a multi-round forward Feistel step 504, a cycle-walking validity check 506, and an output step 508; and further illustrating the inverse permutation steps 510 used during decoding.

**FIG. 6** is a flowchart illustrating the steps of the constraint-guided bit-flip search method 600, comprising a node sorting step 602, a candidate index collection step 604 including pinning exclusion, a combination enumeration loop 606, a tentative flip and scoring step 608, a commit step 610, a progress check 612, and a flip-level increment step 614.

**FIG. 7** is a graph 700 illustrating overhead ratio (metadata bits / source bits) as a function of block length L for embodiments of the present invention using CRC-8, CRC-16, and CRC-32 hash functions compared against the analytical overhead of BCH codes configured for a target bit error rate of 5%, illustrating the O(1/√L) scaling of the present invention versus the approximately constant overhead of BCH.

**FIG. 8** is a graph 800 illustrating correction success rate as a function of bit-flip count for a 4096-bit block using CRC-8, CRC-16, and CRC-32 hash configurations of the present invention, alongside corresponding BCH analytical success rates, demonstrating that the present invention achieves ≥95% success for 200 or more bit-flips at 100% overhead.

**FIG. 9** is a pair of graphs 900A and 900B illustrating correction success rate and search effort (hash evaluations) respectively, comparing random bit-flip errors and burst bit-flip errors of equivalent total count for a 4096-bit block, demonstrating statistical equivalence of performance for both error models due to the Feistel permutation.

**FIG. 10** is a system diagram 1000 illustrating a hardware embodiment of the present invention, comprising a Feistel permutation unit 1002, a grid mapping unit 1004, a CRC computation array 1006, a metadata register file 1008, a mismatch detection unit 1010, a constraint graph register 1012, and a combinatorial search unit 1014, integrated within a memory subsystem 1016 comprising a data storage array 1018 and a metadata storage region 1020.
