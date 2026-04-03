"""Grouped row/column hashing with CRC variants."""

from __future__ import annotations

import binascii
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


def build_group_context(
    meta: GridMeta,
    row_group_size: int,
    col_group_size: int,
    hash_bits: int,
    tail_policy: TailPolicy = "include_partial",
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
        digest=_crc_hash(bits, ctx.hash_bits),
        source_indices=old_node.source_indices,
    )


def build_hash_nodes(
    grid: list[list[int]],
    meta: GridMeta,
    row_group_size: int,
    col_group_size: int,
    hash_bits: int,
    tail_policy: TailPolicy = "include_partial",
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

        digest = _crc_hash(bits, hash_bits)
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

        digest = _crc_hash(bits, hash_bits)
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

