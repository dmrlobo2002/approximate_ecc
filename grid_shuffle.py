"""Linear bits <-> NxN grid via Feistel index permutation."""

from __future__ import annotations

import math
from dataclasses import dataclass

from feistel_perm import invert_index, permute_index


@dataclass(frozen=True)
class GridMeta:
    original_length: int
    n: int
    m: int
    rounds: int
    source_to_grid: list[int]
    grid_to_source: list[int]


def normalize_bits(bits: list[int] | tuple[int, ...] | str) -> list[int]:
    if isinstance(bits, str):
        out = []
        for ch in bits:
            if ch not in {"0", "1"}:
                raise ValueError("bit string must contain only 0/1")
            out.append(1 if ch == "1" else 0)
        return out
    out = []
    for bit in bits:
        if bit not in (0, 1):
            raise ValueError("bits must be 0/1")
        out.append(int(bit))
    return out


def bits_to_grid(bits: list[int] | tuple[int, ...] | str, key: bytes, rounds: int = 8) -> tuple[list[list[int]], GridMeta]:
    src = normalize_bits(bits)
    length = len(src)
    if length == 0:
        raise ValueError("input bits cannot be empty")

    n = math.ceil(math.sqrt(length))
    m = n * n
    padded = src + [0] * (m - length)

    grid_linear = [0] * m
    source_to_grid = [-1] * m
    grid_to_source = [-1] * m

    for src_idx, bit in enumerate(padded):
        dst_idx = src_idx if rounds == 0 else permute_index(src_idx, m, key, rounds=rounds)
        grid_linear[dst_idx] = bit
        source_to_grid[src_idx] = dst_idx
        grid_to_source[dst_idx] = src_idx

    grid = [grid_linear[row * n : (row + 1) * n] for row in range(n)]
    meta = GridMeta(
        original_length=length,
        n=n,
        m=m,
        rounds=rounds,
        source_to_grid=source_to_grid,
        grid_to_source=grid_to_source,
    )
    return grid, meta


def grid_to_bits(grid: list[list[int]], meta: GridMeta, key: bytes) -> list[int]:
    if len(grid) != meta.n or any(len(row) != meta.n for row in grid):
        raise ValueError("grid shape does not match metadata")

    grid_linear = [bit for row in grid for bit in row]
    restored = [0] * meta.m

    for dst_idx, bit in enumerate(grid_linear):
        src_idx = dst_idx if meta.rounds == 0 else invert_index(dst_idx, meta.m, key, rounds=meta.rounds)
        restored[src_idx] = bit

    return restored[: meta.original_length]


def source_index_to_grid_coord(source_idx: int, meta: GridMeta) -> tuple[int, int]:
    dst = meta.source_to_grid[source_idx]
    return dst // meta.n, dst % meta.n

