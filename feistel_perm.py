"""Feistel-based permutation over integer domains."""

from __future__ import annotations

import hashlib
import math


def _split_bits(value: int, left_bits: int, right_bits: int) -> tuple[int, int]:
    right_mask = (1 << right_bits) - 1
    right = value & right_mask
    left = (value >> right_bits) & ((1 << left_bits) - 1)
    return left, right


def _join_bits(left: int, right: int, right_bits: int) -> int:
    return (left << right_bits) | right


def _round_function(right: int, round_idx: int, key: bytes, out_bits: int) -> int:
    payload = key + round_idx.to_bytes(4, "big") + right.to_bytes(8, "big")
    digest = hashlib.sha256(payload).digest()
    raw = int.from_bytes(digest, "big")
    return raw & ((1 << out_bits) - 1)


def _feistel_forward(block: int, k_bits: int, key: bytes, rounds: int) -> int:
    half_bits = k_bits // 2
    left_bits = half_bits
    right_bits = half_bits
    left, right = _split_bits(block, left_bits, right_bits)

    for round_idx in range(rounds):
        f = _round_function(right, round_idx, key, left_bits)
        new_left = right
        new_right = left ^ f
        left, right = new_left & ((1 << half_bits) - 1), new_right & ((1 << half_bits) - 1)

    return _join_bits(left, right, right_bits)


def _feistel_inverse(block: int, k_bits: int, key: bytes, rounds: int) -> int:
    half_bits = k_bits // 2
    left, right = _split_bits(block, half_bits, half_bits)

    for reverse_pos in range(rounds - 1, -1, -1):
        prev_right = left
        f = _round_function(prev_right, reverse_pos, key, half_bits)
        prev_left = right ^ f
        left, right = prev_left & ((1 << half_bits) - 1), prev_right & ((1 << half_bits) - 1)

    return _join_bits(left, right, half_bits)


def permute_index(index: int, domain_size: int, key: bytes, rounds: int = 8) -> int:
    """Permute integer index in [0, domain_size) with cycle-walked Feistel."""
    if not (0 <= index < domain_size):
        raise ValueError("index out of domain")
    if domain_size <= 1:
        return 0
    if rounds <= 0:
        raise ValueError("rounds must be positive")

    k_bits = max(2, math.ceil(math.log2(domain_size)))
    if k_bits % 2 == 1:
        k_bits += 1
    value = index
    while True:
        value = _feistel_forward(value, k_bits, key, rounds)
        if value < domain_size:
            return value


def invert_index(index: int, domain_size: int, key: bytes, rounds: int = 8) -> int:
    """Inverse permutation for permute_index."""
    if not (0 <= index < domain_size):
        raise ValueError("index out of domain")
    if domain_size <= 1:
        return 0
    if rounds <= 0:
        raise ValueError("rounds must be positive")

    k_bits = max(2, math.ceil(math.log2(domain_size)))
    if k_bits % 2 == 1:
        k_bits += 1
    value = index
    while True:
        value = _feistel_inverse(value, k_bits, key, rounds)
        if value < domain_size:
            return value

