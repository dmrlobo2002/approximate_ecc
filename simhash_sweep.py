"""Compare SimHash, Bit Sampling LSH, and Random Binary Projection
across input sizes and hash sizes under incremental bit-flip corruption.
Two error models are swept: random bit flips and contiguous burst flips.
"""
from __future__ import annotations

import argparse
import hashlib
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any

import numpy as np
from simhash import Simhash

from experiments.common import (
    agg,
    ensure_dir,
    parse_int_list,
    stable_rng,
    write_csv,
    write_json,
)

INPUT_SIZES: list[int] = [256, 512, 1024, 2048, 4096]
HASH_SIZES: list[int] = [8, 16, 32, 64]
N_TRIALS: int = 20
N_GEO_POINTS: int = 20
METHODS: list[str] = ["simhash", "bsl", "rbp"]
ERROR_TYPES: list[str] = ["random", "burst"]

def _hash_size_colors(hash_sizes: list[int]) -> dict[int, Any]:
    try:
        import matplotlib.pyplot as plt
        cmap = plt.cm.tab10
        return {hs: cmap(i / max(len(hash_sizes) - 1, 1)) for i, hs in enumerate(hash_sizes)}
    except ModuleNotFoundError:
        return {}

_METHOD_TITLES: dict[str, str] = {
    "simhash": "SimHash",
    "bsl":     "Bit Sampling LSH",
    "rbp":     "Random Binary Projection",
}

_ERROR_TYPE_LABELS: dict[str, str] = {
    "random": "Random Flips",
    "burst":  "Burst Flips",
}

# SHA-512 (64 bytes) supports f up to 512 bits; the default MD5 (16 bytes) only supports f<=128
# and silently corrupts or crashes for f=256.
def _sha512_hashfunc(x: bytes) -> bytes:
    return hashlib.sha512(x).digest()

# Module-level cache for method parameters; populated lazily per worker process.
# Key: (method, input_size, hash_size, seed)
_param_cache: dict[tuple, Any] = {}


def geo_flip_counts(input_size: int) -> list[int]:
    """~N_GEO_POINTS geometrically-spaced flip counts from 1 to 5% of input_size."""
    max_flips = max(10, int(0.05 * input_size))
    pts: set[int] = set()
    for i in range(N_GEO_POINTS):
        v = max_flips ** (i / (N_GEO_POINTS - 1))
        pts.add(max(1, round(v)))
    return sorted(pts)


def _bits_for_size(input_size: int) -> list[int]:
    return [(i * 3 + 1) % 2 for i in range(input_size)]


def _simhash_hd(orig: list[int], corrupted: list[int], hash_size: int) -> int:
    def to_features(bits: list[int]) -> list[str]:
        feats = []
        for i in range(0, len(bits), 8):
            chunk = bits[i:i + 8]
            val = 0
            for b in chunk:
                val = (val << 1) | b
            feats.append(f"b{i // 8}_{val}")
        return feats

    h_orig = Simhash(to_features(orig), f=hash_size, hashfunc=_sha512_hashfunc).value
    h_corr = Simhash(to_features(corrupted), f=hash_size, hashfunc=_sha512_hashfunc).value
    return bin(h_orig ^ h_corr).count("1")


def _bsl_hd(orig: list[int], corrupted: list[int], positions: list[int]) -> int:
    return sum(orig[p] != corrupted[p] for p in positions)


def _rbp_hd(orig: np.ndarray, corrupted: np.ndarray, H: np.ndarray) -> int:
    h_orig = (H @ orig) % 2
    h_corr = (H @ corrupted) % 2
    return int(np.sum(h_orig ^ h_corr))


def _run_task(task: tuple) -> dict[str, Any]:
    method, input_size, hash_size, flip_count, trial_id, seed, error_type = task

    cache_key = (method, input_size, hash_size, seed)
    if cache_key not in _param_cache:
        if method == "bsl":
            rng = stable_rng(seed, "bsl_params", input_size, hash_size)
            _param_cache[cache_key] = rng.choices(range(input_size), k=hash_size)
        elif method == "rbp":
            rng = stable_rng(seed, "rbp_params", input_size, hash_size)
            np_seed = rng.randint(0, 2 ** 31)
            _param_cache[cache_key] = np.random.default_rng(np_seed).integers(
                0, 2, size=(hash_size, input_size), dtype=np.uint8
            )
        else:
            _param_cache[cache_key] = None

    params = _param_cache[cache_key]
    orig = _bits_for_size(input_size)

    if error_type == "random":
        # Strictly incremental: fixed shuffle per trial, first flip_count positions used.
        flip_rng = stable_rng(seed, "flips", trial_id, input_size)
        positions = flip_rng.sample(range(input_size), input_size)[:flip_count]
    else:  # burst
        # Fixed start per trial; burst grows from that start position.
        max_flips = max(10, int(0.05 * input_size))
        burst_rng = stable_rng(seed, "burst_start", trial_id, input_size)
        start = burst_rng.randint(0, max(0, input_size - max_flips))
        positions = list(range(start, start + flip_count))

    corrupted = list(orig)
    for pos in positions:
        corrupted[pos] ^= 1

    if method == "simhash":
        hd = _simhash_hd(orig, corrupted, hash_size)
    elif method == "bsl":
        hd = _bsl_hd(orig, corrupted, params)
    else:
        hd = _rbp_hd(
            np.array(orig, dtype=np.uint8),
            np.array(corrupted, dtype=np.uint8),
            params,
        )

    return {
        "method":        method,
        "input_size":    input_size,
        "hash_size":     hash_size,
        "flip_count":    flip_count,
        "trial_id":      trial_id,
        "error_type":    error_type,
        "hd":            hd,
        "hd_normalized": hd / hash_size,
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Sweep SimHash, Bit Sampling LSH, and Random Binary Projection under bit-flip corruption"
    )
    p.add_argument("--input-sizes", type=str, default=",".join(str(x) for x in INPUT_SIZES))
    p.add_argument("--hash-sizes",  type=str, default=",".join(str(x) for x in HASH_SIZES))
    p.add_argument("--trials",      type=int, default=N_TRIALS)
    p.add_argument("--seed",        type=int, default=0)
    p.add_argument("--out-dir",     type=str, default="results/simhash_sweep")
    p.add_argument("--no-plot",     action="store_true")
    p.add_argument("--parallel",    action="store_true")
    p.add_argument("--workers",     type=int, default=0)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    input_sizes = parse_int_list(args.input_sizes)
    hash_sizes  = parse_int_list(args.hash_sizes)

    ensure_dir(args.out_dir)
    write_json(os.path.join(args.out_dir, "config.json"), {
        "input_sizes":  input_sizes,
        "hash_sizes":   hash_sizes,
        "trials":       args.trials,
        "seed":         args.seed,
        "methods":      METHODS,
        "error_types":  ERROR_TYPES,
        "n_geo_points": N_GEO_POINTS,
    })

    all_tasks: list[tuple] = []
    for method in METHODS:
        for error_type in ERROR_TYPES:
            for input_size in input_sizes:
                for hash_size in hash_sizes:
                    for flip_count in geo_flip_counts(input_size):
                        for trial_id in range(args.trials):
                            all_tasks.append((
                                method, input_size, hash_size,
                                flip_count, trial_id, args.seed, error_type,
                            ))

    total = len(all_tasks)
    print(
        f"Running {total} trials "
        f"({len(METHODS)} methods × {len(ERROR_TYPES)} error types × {len(input_sizes)} input sizes × "
        f"{len(hash_sizes)} hash sizes × ~{N_GEO_POINTS} flip counts × {args.trials} trials)"
    )

    if args.parallel:
        workers = args.workers if args.workers > 0 else (os.cpu_count() or 1)
        flat_results: list[dict[str, Any]] = [None] * total  # type: ignore
        done = 0
        with ProcessPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(_run_task, t): i for i, t in enumerate(all_tasks)}
            for fut in as_completed(futures):
                flat_results[futures[fut]] = fut.result()
                done += 1
                print(f"\r  {done}/{total} ({100 * done / total:.1f}%)", end="", flush=True)
        print()
    else:
        flat_results = []
        for i, t in enumerate(all_tasks):
            flat_results.append(_run_task(t))
            print(f"\r  {i + 1}/{total} ({100 * (i + 1) / total:.1f}%)", end="", flush=True)
        print()

    csv_path = os.path.join(args.out_dir, "simhash_sweep_data.csv")
    write_csv(csv_path, flat_results,
              ["method", "input_size", "hash_size", "flip_count", "trial_id",
               "error_type", "hd", "hd_normalized"])
    print(f"Saved: {csv_path}")

    if args.no_plot:
        return

    try:
        import matplotlib.pyplot as plt
    except ModuleNotFoundError:
        print("matplotlib not installed; skipping plot (re-run with --no-plot to suppress)")
        return

    colors = _hash_size_colors(hash_sizes)

    for plot_input_size in input_sizes:
        plot_flip_counts = geo_flip_counts(plot_input_size)

        fig, axes = plt.subplots(2, 3, figsize=(18, 10))
        fig.suptitle(
            f"Hash Sensitivity to Bit-Flips  (input_size={plot_input_size} bits)",
            fontsize=14, fontweight="bold",
        )

        for row, error_type in enumerate(ERROR_TYPES):
            for col, method in enumerate(METHODS):
                ax = axes[row][col]
                for hash_size in hash_sizes:
                    xs, ys, yerrs = [], [], []
                    for flip_count in plot_flip_counts:
                        hd_vals = [
                            r["hd"] for r in flat_results
                            if r["method"] == method
                            and r["input_size"] == plot_input_size
                            and r["hash_size"] == hash_size
                            and r["flip_count"] == flip_count
                            and r["error_type"] == error_type
                        ]
                        if not hd_vals:
                            continue
                        a = agg(hd_vals)
                        xs.append(flip_count)
                        ys.append(a.mean)
                        yerrs.append(a.sem)

                    ax.errorbar(
                        xs, ys, yerr=yerrs,
                        marker="o", linewidth=2, capsize=3,
                        label=f"{hash_size}-bit",
                        color=colors[hash_size],
                    )

                if row == 0:
                    ax.set_title(_METHOD_TITLES[method], fontsize=12)
                ax.set_xlabel("Injected bit-flips")
                if col == 0:
                    ax.set_ylabel(f"{_ERROR_TYPE_LABELS[error_type]}\nMean Hamming Distance")
                ax.grid(True, alpha=0.3)
                ax.legend(title="Hash size", fontsize=9)
                ax.set_xlim(left=0)
                ax.set_ylim(bottom=0)

        plt.tight_layout()
        png_path = os.path.join(args.out_dir, f"simhash_sweep_{plot_input_size}b.png")
        plt.savefig(png_path, dpi=200, bbox_inches="tight")
        plt.close()
        print(f"Saved: {png_path}")


if __name__ == "__main__":
    main()
