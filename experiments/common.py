from __future__ import annotations

import csv
import hashlib
import json
import os
import random
import statistics
import time
from dataclasses import dataclass
from typing import Any, Iterable, Sequence


def parse_int_list(spec: str) -> list[int]:
    spec = spec.strip()
    if not spec:
        return []
    return [int(x.strip()) for x in spec.split(",") if x.strip()]


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def write_json(path: str, obj: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, sort_keys=True)
        f.write("\n")


def write_csv(path: str, rows: Iterable[dict[str, Any]], fieldnames: Sequence[str]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in rows:
            w.writerow(row)


def stable_key(seed: int, key_id: int, nbytes: int = 16) -> bytes:
    """Deterministically derive a key from (seed, key_id)."""
    h = hashlib.blake2b(f"{seed}:{key_id}".encode("utf-8"), digest_size=nbytes)
    return h.digest()


def stable_rng(*parts: Any) -> random.Random:
    """Build a deterministic RNG from mixed parts."""
    payload = "|".join(str(p) for p in parts).encode("utf-8")
    digest = hashlib.blake2b(payload, digest_size=16).digest()
    seed_int = int.from_bytes(digest, "big")
    return random.Random(seed_int)


@dataclass(frozen=True)
class Agg:
    mean: float
    stdev: float
    n: int

    @property
    def sem(self) -> float:
        if self.n <= 1:
            return 0.0
        return self.stdev / (self.n ** 0.5)


def agg(values: Sequence[float]) -> Agg:
    if not values:
        return Agg(mean=float("nan"), stdev=float("nan"), n=0)
    if len(values) == 1:
        return Agg(mean=float(values[0]), stdev=0.0, n=1)
    return Agg(mean=float(statistics.mean(values)), stdev=float(statistics.stdev(values)), n=len(values))


def median(values: Sequence[float]) -> float:
    if not values:
        return float("nan")
    return float(statistics.median(values))


class Timer:
    def __enter__(self) -> "Timer":
        self._t0 = time.perf_counter()
        self.elapsed = 0.0
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.elapsed = time.perf_counter() - self._t0

