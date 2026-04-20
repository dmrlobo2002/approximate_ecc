# NeurIPS Paper Roadmap

## Central Claim

> A hash-based, block-structured ECC scheme that protects neural network weights in DRAM on AI accelerators — correcting 10–100× more errors per overhead percent than SECDED/BCH, with burst resilience via Feistel interleaving, at negligible inference latency.

Every experiment and theoretical section must serve this claim.

---

## Current Status

| Component | Status | NeurIPS role |
|---|---|---|
| fig1: success rate vs flip count | Done | Supplementary ablation |
| fig2: overhead vs BCH | Done | Needs LDPC added |
| fig3: scalability | Done | Keep as-is |
| fig4: burst resilience | Done | Core selling point, keep prominent |
| fig5: NN accuracy recovery | Partial | **This is the paper** |
| Theory / formal guarantees | Missing | **Required for NeurIPS main** |
| Solver complexity analysis | Missing | Required |
| Second model (beyond ResNet-20) | Missing | Required for generality |
| INT8 quantized weight experiment | Missing | Required for AI accelerator realism |

---

## Phase 1 — Nail the Application Story (fig5)

*Estimated effort: ~2 weeks. Everything else depends on this.*

This is the paper's hook. Without a clean, compelling fig5, the paper reads as a
coding theory submission — not a ML paper.

### Tasks

**1. Complete the BER sweep**
- Fix performance so the full sweep (1e-5 → 2e-2) runs in reasonable wall time.
- Precompute all block metas + checksums once upfront (already implemented).
- Use C++-accelerated `correct_with_dag` for the solver step (already switched).
- Verify timing at high BER (1e-2, 2e-2). If too slow, cap claims at BER ≤ 5e-3.
- Target: 5 trials × 8 BER points × 3 ECC configs < 2 hours total.

**2. Add a second model**
- VGG-16 or MobileNetV2 on CIFAR-10, both available via `chenyaofo/pytorch-cifar-models`.
- Two models proves the result is not ResNet-20-specific.

**3. Add INT8 quantized weights**
- Repeat fig5 on post-training quantized INT8 weights.
- Use `torch.quantization.quantize_dynamic` (simple, no calibration required).
- AI accelerators overwhelmingly use INT8; this makes the paper directly applicable.
- Story: INT8 flips are less individually catastrophic but still degrade accuracy at BER > 1e-3.

**4. Target figure shape**
Panel A — Accuracy vs BER (log x-axis):
- Clean accuracy: dashed horizontal line (~91%)
- No ECC: collapses at BER ~1e-4 (FP32) or ~1e-3 (INT8)
- SECDED (12.5% overhead): survives slightly longer, then collapses
- CRC-8 (25%), CRC-16 (50%), CRC-32 (100%): each maintains clean accuracy up to its threshold

Panel B — Bit correction rate vs BER: bridges to figs 1–4

Panel C — Memory overhead required for ≥95% accuracy preservation vs BER: ours vs BCH analytical

### Target result
"Our scheme maintains ≥95% of clean accuracy at BER up to 5×10⁻³ with 25% overhead,
where SECDED (12.5% overhead) fails above BER ~2×10⁻⁴."

---

## Phase 2 — Theoretical Grounding

*Estimated effort: ~2 weeks. Required for NeurIPS main; without it, aim for a workshop.*

NeurIPS reviewers will ask "what are the guarantees?" These three propositions are all
tractable given the existing codebase and require no fundamentally new theory.

### Proposition 1 — False Positive Probability
A clean block passes all hash checks with probability 1.
A corrupted block is miscorrected (flipped to a wrong value that still passes all checks)
with probability ≤ 2^{-hash_bits} per node.
State formally with proof sketch (follows directly from CRC collision probability).

### Proposition 2 — Overhead Formula
For an L-bit block on an N×N grid (N = ⌈√L⌉) with hash_bits = h:
- Row overhead: N × h bits
- Col overhead: N × h bits
- Total overhead ratio: 2Nh / L ≈ 2h / √L

This is the O(1/√L) scaling shown empirically in fig3. Formalize it.
Corollary: to achieve overhead ratio r, set h = r√L / 2.

### Proposition 3 — Solver Complexity
At BER p on an L-bit block, each N-bit hash node sees ≈ pN flips in expectation.
The solver tries C(N, k) combinations at flip level k.
For pN < 1 (low-flip regime, which is the operating regime of any practical ECC):
- k=1 dominates, complexity is O(N) per mismatched node
- Expected mismatched nodes: O(pN × 2N) = O(pL) total
- End-to-end solver complexity: O(pL × N) = O(p L^{3/2}) per block

State the condition on p under which this bound holds, and show empirically
(from fig1 combo counts) that actual behavior matches this scaling.

### Capacity comparison
Show where the scheme sits on the overhead vs correctable-errors Pareto frontier
relative to BCH and LDPC (LDPC is capacity-approaching; show analytically that
our scheme trades some capacity efficiency for burst resilience and a simpler decoder).

---

## Phase 3 — Better Baselines

*Estimated effort: ~1 week. The BCH comparison exists; extend it.*

**LDPC** — already in `experiments/ecc_comparison.py` (`ldpc_overhead`).
Add to fig2. Frame: "At comparable overhead, LDPC achieves X% BER channel capacity
vs our empirical Y% BER correction."

**Reed-Solomon** — also in `ecc_comparison.py` (`rs_overhead`).
RS is the standard for NAND flash/SSD storage. Compare on fig4 burst-error panel.

**ECC-aware training strawman** — briefly discuss whether training with bit-flip
noise injection is a substitute for hardware ECC. It is not:
- Retraining costs dominate for large models
- Hardware errors occur at inference time on already-deployed models
- Bit flips during inference are not the same distribution as training noise

---

## Phase 4 — Ablations

*Estimated effort: ~1 week. Goes in the appendix; reviewers expect to see these.*

| Ablation | Variable | What to show |
|---|---|---|
| Hash function | CRC vs SimHash | Same false-positive rate, slightly worse solver guidance for SimHash |
| Group size | 1×1 vs 2×2 vs 4×4 | Larger groups → less overhead, coarser correction granularity |
| Feistel rounds | 1 vs 4 vs 8 | ≥4 rounds sufficient for burst equalization; 1 round fails |
| Block size | 512, 1024, 4096, 16384 bits | Overhead vs correction tradeoff matches Proposition 2 |

---

## Phase 5 — Writing

*Estimated effort: ~2–3 weeks.*

### Paper structure (9 pages + references, NeurIPS format)

1. **Introduction** (1.5 pages)
   - DRAM soft error rates (cite Li et al. SC'17, JEDEC specs)
   - AI accelerator context: weights in HBM/DRAM, checksums in on-chip SRAM
   - Why existing ECC (SECDED, BCH) is insufficient
   - Our approach and contributions list

2. **Background** (0.5 pages)
   - DRAM SER rates and failure modes
   - Classical ECC: SECDED, BCH, LDPC
   - Related NN robustness work (quantization, fault-aware training)

3. **Method** (2 pages)
   - Feistel shuffle for burst equalization
   - 2D grid hash structure and DAG construction
   - DAG-guided solver: iterative flip-level climbing
   - Hardware deployment model: encode at load time, decode at inference time

4. **Theory** (1 page)
   - Proposition 1: false positive probability
   - Proposition 2: overhead formula and O(1/√L) scaling
   - Proposition 3: solver complexity in the low-flip regime

5. **Experiments** (3 pages)
   - fig5 (accuracy vs BER — main result, full page)
   - fig2 (overhead vs BCH/LDPC)
   - fig4 (burst resilience)
   - Ablations summary table

6. **Related Work** (0.5 pages)

7. **Conclusion** (0.5 pages)

---

## Risk Register

| Risk | Severity | Mitigation |
|---|---|---|
| Solver too slow at BER > 1e-2 for large models | High | Cap claims at BER ≤ 5e-3 (still far beyond SECDED's failure point) |
| Reviewers ask "why not retrain on noisy data?" | Medium | Quantitative: retraining costs >> ECC overhead; hardware errors are post-deployment |
| No polynomial-time decoder | Medium | Frame solver as practically O(pL^{3/2}); connect to loopy BP on a factor graph |
| Venue fit: NeurIPS vs MLSys | Medium | MLSys as primary target; NeurIPS as stretch; NeurIPS workshop as fallback |
| Theory reveals gaps in guarantees | Low | False positive bound is tight and already proven; solver bound is conditional but honest |

---

## Venue Guidance

**Primary target: MLSys** (conference on ML systems and hardware)
- Strongest fit for hardware ECC + AI accelerator framing
- Accepts papers without heavy theory

**Stretch target: NeurIPS main**
- Requires Phases 1–3 all complete, with theory section
- Must be submitted to a track accepting hardware/systems work

**Fallback: NeurIPS workshop**
- "ML for Systems" or "Efficient Neural Network" workshop
- Lower bar; good for getting reviewer feedback before a full submission
- Strongly recommended as a parallel submission to get early signal

---

## Immediate Next Step

Run Phase 1 experiments completely before doing anything else.
All theory and writing depends on knowing what fig5 actually looks like with real data.

```bash
# Full fig5 run — expect ~2 hours
python fig5_nn_weight_protection.py \
    --trials 5 \
    --subset 2000 \
    --ber-sweep "1e-5,5e-5,1e-4,5e-4,1e-3,5e-3,1e-2,2e-2" \
    --out-dir results/fig5
```
