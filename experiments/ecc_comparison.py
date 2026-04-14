"""Analytic overhead and correction capability for classical ECC schemes.

All functions return a dict with at least:
  parity_bits      — number of check/parity bits required
  overhead_ratio   — parity_bits / data_bits
  correctable_bits — number of bit errors the code can correct
  detectable_bits  — number of bit errors the code can detect (not correct)
"""
from __future__ import annotations

import math


def hamming_overhead(data_bits: int) -> dict:
    """
    Hamming/SECDED overhead using the standard (72, 64) SECDED building block.

    Memory ECC is deployed as SECDED over 64-bit words: 8 parity bits per word,
    12.5% overhead, corrects 1 bit per word, detects 2.
    For any data_bits, tile ceil(data_bits / 64) such codewords.
    """
    SECDED_DATA = 64    # data bits per word
    SECDED_PARITY = 8   # parity bits per word
    n_blocks = math.ceil(data_bits / SECDED_DATA)
    total_parity = n_blocks * SECDED_PARITY
    return {
        "scheme": f"SECDED({n_blocks}×(72,64))",
        "data_bits": data_bits,
        "parity_bits": total_parity,
        "overhead_ratio": total_parity / data_bits,
        "correctable_bits": n_blocks,   # 1 bit per 64-bit word
        "detectable_bits": 2 * n_blocks,
    }


def bch_overhead(data_bits: int, t: int) -> dict:
    """
    Exact BCH code overhead for correcting t errors in data_bits data bits.

    Computes the exact generator polynomial degree via 2-cyclotomic cosets over GF(2^m).
    The generator polynomial is LCM(m_1, m_3, m_5, ..., m_{2t-1}) where m_i is the
    minimal polynomial of alpha^i. Elements in the same cyclotomic coset share a
    minimal polynomial, so we sum coset sizes for each distinct odd coset up to 2t-1.

    Overhead is reported relative to data_bits (as for a shortened BCH code), which
    is the relevant metric when comparing against a fixed data size.

    For data_bits > 256, tile ceil(data_bits/256) BCH(256, t) codewords with the same
    t per block. Overhead ratio = BCH(256, t) overhead (constant in data_bits).
    """
    if data_bits > 256:
        # Tile multiple BCH(256, t) codewords — same t per 256-bit block.
        # Overhead ratio = BCH(256, t) overhead ratio (constant regardless of data_bits).
        # Correctable bits scale with the number of blocks.
        n_blocks = math.ceil(data_bits / 256)
        base = bch_overhead(256, t)
        total_parity = n_blocks * base["parity_bits"]
        return {
            "scheme": f"BCH({n_blocks}×BCH(256),t={t}/block)",
            "data_bits": data_bits,
            "parity_bits": total_parity,
            "overhead_ratio": total_parity / data_bits,
            "correctable_bits": n_blocks * t,
            "detectable_bits": n_blocks * 2 * t,
        }

    m = max(1, math.ceil(math.log2(data_bits + 1)))
    n = (1 << m) - 1  # primitive BCH block length: 2^m - 1

    # Compute exact parity bits via 2-cyclotomic cosets mod n.
    # Roots needed: alpha^1, alpha^3, ..., alpha^(2t-1).
    # Any root already covered by a prior coset adds no new parity bits.
    covered: set[int] = set()
    parity_bits = 0
    for i in range(1, 2 * t, 2):  # odd indices 1, 3, 5, ..., 2t-1
        root = i % n
        if root in covered:
            continue
        coset: set[int] = set()
        j = root
        while j not in coset:
            coset.add(j)
            j = (j * 2) % n
        covered |= coset
        parity_bits += len(coset)

    parity_bits = min(parity_bits, n - 1)
    actual_data_bits = n - parity_bits
    return {
        "scheme": f"BCH({n},{actual_data_bits},t={t})",
        "data_bits": actual_data_bits,
        "parity_bits": parity_bits,
        "overhead_ratio": parity_bits / data_bits,  # overhead vs. actual data size
        "correctable_bits": t,
        "detectable_bits": 2 * t,
    }


def bch_decode_ops(data_bits: int, t: int) -> int:
    """
    Approximate number of GF field operations for BCH decoding with t error correction.

    Dominant costs (all in GF(2^m) field ops):
      - Syndrome computation:  2t * n        (evaluate 2t polynomials at n points)
      - Berlekamp-Massey:      ~t^2           (O(t^2) field multiplications)
      - Chien search:          n * t          (dominant for large n and t)
      - Forney algorithm:      ~n * t         (error magnitude, same order as Chien)

    Returns an approximate operation count comparable to our total_combos_evaluated.
    """
    m = max(1, math.ceil(math.log2(data_bits + 1)))
    n = (1 << m) - 1
    syndrome_cost = 2 * t * n
    bm_cost = t * t
    chien_cost = n * t
    forney_cost = n * t
    return syndrome_cost + bm_cost + chien_cost + forney_cost


def rs_overhead(data_bits: int, t: int, symbol_bits: int = 8) -> dict:
    """
    Reed-Solomon overhead for correcting t symbol errors per codeword over GF(2^symbol_bits).

    Natural unit: RS(255, 255-2t) over GF(2^8) — the standard 255-byte codeword.
    `t` is the number of symbol errors correctable per 255-symbol codeword.

    For data_bits <= (255-2t)*symbol_bits (fits in one shortened codeword):
      parity = 2t * symbol_bits, overhead = parity / data_bits.

    For larger blocks: tile ceil(data_bits / natural_data_bits) full RS(255) codewords.
      Overhead ratio converges to 2t / (255-2t) (constant, independent of data_bits).
    """
    MAX_SYMBOLS = 255
    natural_data_bits = (MAX_SYMBOLS - 2 * t) * symbol_bits
    if natural_data_bits <= 0:
        raise ValueError(f"t={t} too large for RS over GF(2^{symbol_bits}): max t={MAX_SYMBOLS // 2 - 1}")

    parity_per_codeword = 2 * t * symbol_bits
    if data_bits <= natural_data_bits:
        # Shortened RS: same 2t parity symbols, fewer data symbols.
        return {
            "scheme": f"RS(GF(2^{symbol_bits}),t={t}sym)",
            "data_bits": data_bits,
            "parity_bits": parity_per_codeword,
            "overhead_ratio": parity_per_codeword / data_bits,
            "correctable_symbols": t,
            "correctable_bits": t * symbol_bits,
            "detectable_bits": 2 * t * symbol_bits,
        }
    else:
        # Tile multiple RS(255, 255-2t) codewords.
        n_blocks = math.ceil(data_bits / natural_data_bits)
        total_parity = n_blocks * parity_per_codeword
        return {
            "scheme": f"RS({n_blocks}×RS(255),t={t}sym/block)",
            "data_bits": data_bits,
            "parity_bits": total_parity,
            "overhead_ratio": total_parity / data_bits,
            "correctable_symbols": n_blocks * t,
            "correctable_bits": n_blocks * t * symbol_bits,
            "detectable_bits": n_blocks * 2 * t * symbol_bits,
        }


def rs_overhead_for_ber(data_bits: int, ber: float, symbol_bits: int = 8) -> dict:
    """
    RS overhead required at a given BER, using per-codeword expected symbol-error count.

    Uses the RS(255) tiling model: t is the expected errored symbols per 255-symbol
    codeword, which is 255 * (1 - (1 - ber)^symbol_bits).
    """
    if data_bits <= symbol_bits or ber <= 0.0:
        t = 0
    else:
        p_sym_error = 1.0 - (1.0 - ber) ** symbol_bits
        t = math.ceil(255 * p_sym_error)   # per RS(255) codeword
    return rs_overhead(data_bits, t, symbol_bits)


def ldpc_overhead(data_bits: int, code_rate: float = 0.5) -> dict:
    """
    LDPC code at a given code rate R = data_bits / (data_bits + parity_bits).

    Correction capability for LDPC is channel-dependent; we report the
    overhead ratio only. Theoretical capacity-approaching performance is
    assumed (Shannon limit approximation).
    """
    parity_bits = round(data_bits * (1 / code_rate - 1))
    return {
        "scheme": f"LDPC(rate={code_rate})",
        "data_bits": data_bits,
        "parity_bits": parity_bits,
        "overhead_ratio": parity_bits / data_bits,
        "correctable_bits": None,   # channel-dependent
        "detectable_bits": None,
    }
