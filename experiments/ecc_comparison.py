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
    Systematic Hamming code for `data_bits` data bits.

    The number of parity bits r satisfies 2^r >= data_bits + r + 1.
    Can correct 1 error, detect 2 errors (with extended Hamming parity bit).
    """
    r = 1
    while (1 << r) < data_bits + r + 1:
        r += 1
    return {
        "scheme": f"Hamming({data_bits + r},{data_bits})",
        "data_bits": data_bits,
        "parity_bits": r,
        "overhead_ratio": r / data_bits,
        "correctable_bits": 1,
        "detectable_bits": 2,
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

    For data_bits > 256, BCH is modeled as x2 overhead (overhead_ratio = 1.0).
    """
    if data_bits > 256:
        return {
            "scheme": f"BCH(x2,t={t})",
            "data_bits": data_bits,
            "parity_bits": data_bits,
            "overhead_ratio": 1.0,
            "correctable_bits": t,
            "detectable_bits": 2 * t,
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
