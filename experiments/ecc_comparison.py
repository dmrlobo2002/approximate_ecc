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
    Approximate BCH code overhead for correcting t errors in ~data_bits data bits.

    Uses the standard BCH bound: for a code of block length n = 2^m - 1,
    the parity check matrix has at most 2t*m rows, so parity bits <= 2t*m
    where m = ceil(log2(data_bits + 1)).

    This is an upper bound on parity bits; real BCH codes may use fewer.
    """
    m = max(1, math.ceil(math.log2(data_bits + 1)))
    n = (1 << m) - 1          # BCH block length (nearest 2^m - 1 >= data_bits)
    parity_bits = min(2 * t * m, n - 1)
    actual_data_bits = n - parity_bits
    return {
        "scheme": f"BCH({n},{actual_data_bits},t={t})",
        "data_bits": actual_data_bits,
        "parity_bits": parity_bits,
        "overhead_ratio": parity_bits / actual_data_bits,
        "correctable_bits": t,
        "detectable_bits": 2 * t,
    }


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
