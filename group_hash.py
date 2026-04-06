"""Grouped row/column hashing with CRC variants and SimHash LSH."""

from __future__ import annotations

import binascii
import functools
import hashlib
import math
import random as _random
from dataclasses import dataclass
from typing import Literal

from grid_shuffle import GridMeta

Axis = Literal["row", "col"]
TailPolicy = Literal["include_partial", "pad_with_zeros", "drop_partial"]


@dataclass(frozen=True)
class HashNode:
    node_id: str
    axis: Axis
    group_index: int
    hash_bits: int
    digest: int
    source_indices: frozenset[int]

    @property
    def covered_bits(self) -> int:
        return len(self.source_indices)


def _crc8(data: bytes, poly: int = 0x07, init: int = 0x00, xor_out: int = 0x00) -> int:
    crc = init
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ poly) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
    return crc ^ xor_out


def _make_crc16_table(poly: int = 0x1021) -> list:
    table = []
    for byte in range(256):
        crc = byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ poly) if (crc & 0x8000) else (crc << 1)
            crc &= 0xFFFF
        table.append(crc)
    return table


_CRC16_TABLE = _make_crc16_table()


def _crc16(data: bytes, init: int = 0xFFFF, xor_out: int = 0x0000) -> int:
    crc = init
    for byte in data:
        crc = ((crc << 8) ^ _CRC16_TABLE[(crc >> 8) ^ byte]) & 0xFFFF
    return crc ^ xor_out


def _pack_bits_to_bytes(bits: list[int]) -> bytes:
    out = bytearray()
    byte = 0
    for i, bit in enumerate(bits):
        byte = (byte << 1) | bit
        if (i + 1) % 8 == 0:
            out.append(byte)
            byte = 0
    rem = len(bits) % 8
    if rem:
        byte <<= 8 - rem
        out.append(byte)
    return bytes(out)


def _node_seed(node_id: str) -> int:
    return int(hashlib.md5(node_id.encode()).hexdigest(), 16) & 0xFFFFFFFF


@functools.lru_cache(maxsize=512)
def _simhash_masks(n: int, hash_bits: int, node_id: str) -> tuple[int, ...]:
    """Precompute and cache GF(2) projection masks as packed integers.

    masks[h] is an integer bitmask: bit i is set iff input position i is included in
    the XOR for output bit h. Cached so the RNG is only run once per unique
    (node_id, n, hash_bits) combination; subsequent calls only do bitwise ops.
    """
    rng = _random.Random(_node_seed(node_id))
    masks = []
    for _ in range(hash_bits):
        mask = 0
        for i in range(n):
            if rng.randint(0, 1):
                mask |= 1 << i
        masks.append(mask)
    return tuple(masks)


def _simhash(bits: list[int], hash_bits: int, node_id: str) -> int:
    n = len(bits)
    if n == 0:
        return 0
    # GF(2) random linear hash: each output bit is the XOR of a random subset of input bits.
    # Every input bit contributes to every output bit with probability 0.5, so a single flip
    # changes each output bit independently with probability 0.5. This gives:
    #   - detection probability: 1 - 2^(-hash_bits)  (same as CRC)
    #   - false positive probability: 2^(-hash_bits) for any nonzero error pattern  (same as CRC)
    # Unlike hyperplane SimHash, the false positive rate does NOT increase for nearby vectors.
    #
    # Hot path: pack bits into one integer, then use C-speed AND + popcount per output bit.
    bits_int = 0
    for i, b in enumerate(bits):
        if b:
            bits_int |= 1 << i
    masks = _simhash_masks(n, hash_bits, node_id)
    result = 0
    for h, mask in enumerate(masks):
        parity = (bits_int & mask).bit_count() & 1
        result |= parity << h
    return result


def _compute_hash(bits: list[int], hash_bits: int, node_id: str, hash_type: str) -> int:
    if hash_type == "simhash":
        return _simhash(bits, hash_bits, node_id)
    return _crc_hash(bits, hash_bits)


def _crc_hash(bits: list[int], hash_bits: int) -> int:
    data = _pack_bits_to_bytes(bits)
    if hash_bits == 8:
        return _crc8(data)
    if hash_bits == 16:
        return _crc16(data)
    if hash_bits == 32:
        return binascii.crc32(data) & 0xFFFFFFFF
    raise ValueError("hash_bits must be one of 8, 16, 32")


def _iter_groups(length: int, group_size: int, tail_policy: TailPolicy) -> list[tuple[int, int]]:
    if group_size <= 0:
        raise ValueError("group_size must be positive")
    groups = []
    start = 0
    while start < length:
        end = min(start + group_size, length)
        size = end - start
        if size < group_size and tail_policy == "drop_partial":
            break
        groups.append((start, end))
        start += group_size
    return groups


@dataclass(frozen=True)
class GroupHashContext:
    meta: GridMeta
    row_group_size: int
    col_group_size: int
    hash_bits: int
    tail_policy: TailPolicy
    row_groups: tuple[tuple[int, int], ...]
    col_groups: tuple[tuple[int, int], ...]
    src_to_node_ids: dict[int, tuple[str, ...]]
    hash_type: str = "crc"


def build_group_context(
    meta: GridMeta,
    row_group_size: int,
    col_group_size: int,
    hash_bits: int,
    tail_policy: TailPolicy = "include_partial",
    hash_type: str = "crc",
) -> GroupHashContext:
    row_groups = tuple(_iter_groups(meta.n, row_group_size, tail_policy))
    col_groups = tuple(_iter_groups(meta.n, col_group_size, tail_policy))
    src_to_node_ids: dict[int, tuple[str, ...]] = {}
    for src_idx in range(meta.original_length):
        linear = meta.source_to_grid[src_idx]
        r, c = linear // meta.n, linear % meta.n
        nids: list[str] = []
        row_gidx = r // row_group_size
        col_gidx = c // col_group_size
        if row_gidx < len(row_groups):
            nids.append(f"row_{row_gidx}")
        if col_gidx < len(col_groups):
            nids.append(f"col_{col_gidx}")
        src_to_node_ids[src_idx] = tuple(nids)
    return GroupHashContext(
        meta=meta,
        row_group_size=row_group_size,
        col_group_size=col_group_size,
        hash_bits=hash_bits,
        tail_policy=tail_policy,
        row_groups=row_groups,
        col_groups=col_groups,
        src_to_node_ids=src_to_node_ids,
        hash_type=hash_type,
    )


def recompute_node(old_node: "HashNode", grid: list[list[int]], ctx: GroupHashContext) -> "HashNode":
    n = ctx.meta.n
    if old_node.axis == "row":
        r0, r1 = ctx.row_groups[old_node.group_index]
        bits = [grid[r][c] for r in range(r0, r1) for c in range(n)]
        if ctx.tail_policy == "pad_with_zeros" and (r1 - r0) < ctx.row_group_size:
            bits.extend([0] * (ctx.row_group_size - (r1 - r0)) * n)
    else:
        c0, c1 = ctx.col_groups[old_node.group_index]
        bits = [grid[r][c] for c in range(c0, c1) for r in range(n)]
        if ctx.tail_policy == "pad_with_zeros" and (c1 - c0) < ctx.col_group_size:
            bits.extend([0] * (ctx.col_group_size - (c1 - c0)) * n)
    return HashNode(
        node_id=old_node.node_id,
        axis=old_node.axis,
        group_index=old_node.group_index,
        hash_bits=old_node.hash_bits,
        digest=_compute_hash(bits, ctx.hash_bits, old_node.node_id, ctx.hash_type),
        source_indices=old_node.source_indices,
    )


def build_hash_nodes(
    grid: list[list[int]],
    meta: GridMeta,
    row_group_size: int,
    col_group_size: int,
    hash_bits: int,
    tail_policy: TailPolicy = "include_partial",
    hash_type: str = "crc",
) -> list[HashNode]:
    n = meta.n
    if len(grid) != n or any(len(row) != n for row in grid):
        raise ValueError("grid shape mismatch")

    nodes: list[HashNode] = []

    row_groups = _iter_groups(n, row_group_size, tail_policy)
    for group_idx, (r0, r1) in enumerate(row_groups):
        bits: list[int] = []
        source_indices: set[int] = set()
        for r in range(r0, r1):
            for c in range(n):
                bits.append(grid[r][c])
                src_idx = meta.grid_to_source[r * n + c]
                if src_idx < meta.original_length:
                    source_indices.add(src_idx)

        if tail_policy == "pad_with_zeros" and (r1 - r0) < row_group_size:
            bits.extend([0] * (row_group_size - (r1 - r0)) * n)

        digest = _compute_hash(bits, hash_bits, f"row_{group_idx}", hash_type)
        nodes.append(
            HashNode(
                node_id=f"row_{group_idx}",
                axis="row",
                group_index=group_idx,
                hash_bits=hash_bits,
                digest=digest,
                source_indices=frozenset(source_indices),
            )
        )

    col_groups = _iter_groups(n, col_group_size, tail_policy)
    for group_idx, (c0, c1) in enumerate(col_groups):
        bits = []
        source_indices = set()
        for c in range(c0, c1):
            for r in range(n):
                bits.append(grid[r][c])
                src_idx = meta.grid_to_source[r * n + c]
                if src_idx < meta.original_length:
                    source_indices.add(src_idx)

        if tail_policy == "pad_with_zeros" and (c1 - c0) < col_group_size:
            bits.extend([0] * (col_group_size - (c1 - c0)) * n)

        digest = _compute_hash(bits, hash_bits, f"col_{group_idx}", hash_type)
        nodes.append(
            HashNode(
                node_id=f"col_{group_idx}",
                axis="col",
                group_index=group_idx,
                hash_bits=hash_bits,
                digest=digest,
                source_indices=frozenset(source_indices),
            )
        )

    return nodes


@dataclass(frozen=True)
class BlockHashResult:
    block_index: int
    digest: int
    source_indices: frozenset


def compute_block_hashes(
    grid: list[list[int]],
    meta: GridMeta,
    block_count: int,
    hash_bits: int = 32,
) -> list[BlockHashResult]:
    """Divide the NxN grid into block_count row-bands and CRC-hash each band.

    Any band whose digest matches the baseline is provably clean
    (P(false match) ≈ 1/2^hash_bits).  Clean bands can be used to pin their
    source indices as definitely-correct in the solver.
    """
    n = meta.n
    rows_per_block = math.ceil(n / block_count)
    results = []
    for b in range(block_count):
        r0 = b * rows_per_block
        r1 = min(r0 + rows_per_block, n)
        bits: list[int] = []
        src_indices: set[int] = set()
        for r in range(r0, r1):
            for c in range(n):
                bits.append(grid[r][c])
                src_idx = meta.grid_to_source[r * n + c]
                if src_idx < meta.original_length:
                    src_indices.add(src_idx)
        results.append(BlockHashResult(
            block_index=b,
            digest=_crc_hash(bits, hash_bits),
            source_indices=frozenset(src_indices),
        ))
    return results

