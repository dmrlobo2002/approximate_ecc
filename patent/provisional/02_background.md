# BACKGROUND OF THE INVENTION

## Field of the Invention

The present invention relates generally to data integrity and error correction, and more particularly to systems and methods for detecting and correcting bit-flip errors in stored or transmitted data blocks using hash-based constraint grids and combinatorial search-based decoding, with particular application to high-reliability data storage, memory systems, and protection of machine learning model parameters.

## Background and Prior Art

Modern digital storage and communication systems are susceptible to bit-flip errors arising from a variety of physical phenomena, including ionizing radiation, DRAM row-hammer disturbance, NAND flash wear-out, magnetic interference, and high-energy particle strikes. The frequency and severity of such errors have increased as device geometries shrink, supply voltages decrease, and memory cells are operated at higher densities. In safety-critical applications — such as autonomous vehicle inference engines, aerospace computing, and medical diagnostic systems — uncorrected bit-flip errors can cause silent data corruption that propagates undetected through the system with potentially catastrophic consequences.

### Algebraic Error-Correcting Codes

Traditional error-correcting codes (ECCs) address this problem through algebraic redundancy. Bose-Chaudhuri-Hocquenghem (BCH) codes, Reed-Solomon (RS) codes, and low-density parity-check (LDPC) codes are the dominant approaches in practice.

**BCH codes** are binary linear codes that can correct up to t arbitrary bit errors in a codeword of length n. The number of parity bits required for a BCH code correcting t errors in an n-bit block is approximately 2t·⌈log₂(n+1)⌉. The BCH decoding algorithm requires solving the error-locator polynomial using the Berlekamp-Massey algorithm and Chien search, both of which involve arithmetic over a Galois field GF(2^m). This requires either dedicated Galois field hardware multipliers or software libraries implementing polynomial arithmetic over finite fields, adding silicon area overhead and power consumption in hardware implementations.

A critical practical limitation of BCH codes is the mismatch between their design parameter t (the guaranteed correction capacity) and the actual error count distribution observed in practice. In applications where errors are distributed across a statistical distribution — for instance, a Poisson process with mean μ flips per block — a BCH code must be parameterized at t ≥ μ + k·σ (where k is chosen so that the success probability exceeds a required target such as 99.9%). For distributions with significant variance, this can require t to be two to five times larger than the mean error rate, which proportionally increases the parity overhead. This phenomenon — referred to herein as the "honest-t problem" — means that BCH overhead in practice significantly exceeds what would be required for the expected error count alone.

**Reed-Solomon codes** operate on symbol alphabets larger than GF(2), providing burst error correction as a byproduct of their structure. However, RS codes require even more complex decoding hardware (Berlekamp-Massey algorithm over GF(2^m) for large m) and their overhead — measured as parity symbols relative to data symbols — similarly grows proportionally with the number of correctable symbol errors.

**LDPC codes** approach the Shannon capacity and provide excellent performance at large block sizes, but their decoding (belief propagation over a Tanner graph) is iterative and requires hundreds to thousands of message-passing operations per decoded block. LDPC codes are designed for channels with known statistical noise models and require lengthy offline design of parity-check matrices tailored to target block sizes and code rates. They do not naturally adapt to variable-overhead configurations at runtime.

### Burst Error Handling

A further limitation common to BCH codes and most binary linear codes is their assumption of an independent random error model. In practice, many failure mechanisms produce burst errors — contiguous sequences of flipped bits arising from a single physical event (e.g., a flash memory page disturb, a DRAM row activation affecting adjacent cells, or a memory controller fault). A contiguous burst of b bit-flips occupying a single codeword block requires t ≥ b to correct under BCH. Burst-error-correcting BCH codes exist but are a distinct family and do not provide the same overhead advantages as random-error-correcting BCH codes for the same burst length b. Reed-Solomon codes provide some burst correction capability by virtue of operating on multi-bit symbols, but impose corresponding overhead in symbol alphabet size.

### Overhead Scaling

For a block of L bits, the overhead of a BCH code correcting t errors is Θ(t·log L) bits. For large error counts (t proportional to L at a fixed bit error rate p), this becomes Θ(p·L·log L), growing super-linearly in the block size. As block sizes increase from 256 to 4096 bits and beyond — driven by trends in flash storage page sizes and memory module granularity — BCH overhead does not benefit from this scaling: the parity bits required for a fixed bit error rate p grow as O(L·log L), while the data block grows as O(L), so the overhead ratio grows slowly with block size.

### Machine Learning Weight Protection

The recent proliferation of deep neural network (DNN) accelerator hardware has introduced a new class of applications that place unusual demands on error correction. DNN inference accelerators store large weight matrices in on-chip SRAM or off-chip DRAM and access them at high bandwidth. At aggressive supply voltages or under radiation exposure, weight values are subject to bit-flip corruption. Unlike traditional data storage, DNN inference is relatively tolerant of small per-weight errors (the model's accuracy degrades gracefully with small perturbations), but large or numerous bit-flip errors can cause catastrophic accuracy collapse. This tolerance profile motivates an "approximate" ECC approach that achieves high success rate at moderate overhead rather than algebraic guarantees at high overhead.

### Need in the Art

There remains a need in the art for an error correction approach that: (i) achieves lower metadata overhead than BCH codes at equivalent or superior correction capability, particularly at high bit error rates; (ii) handles burst errors natively without requiring a distinct burst-correcting code; (iii) does not require Galois field arithmetic in hardware or software; (iv) scales favorably in overhead as block size increases; and (v) is tunable in the overhead-versus-correction-capability tradeoff at runtime without redesigning the code. The present invention addresses these needs.
