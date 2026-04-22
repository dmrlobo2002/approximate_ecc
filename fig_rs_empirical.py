"""Empirical RS comparison: RS(255,k) over GF(2^8) vs our scheme.

RS is used the natural way: byte-oriented GF(2^8), standard 255-byte codewords,
data tiled into chunks of k bytes each. Parity stored separately (errors in data only).

Configs tested:
  t=32  k=191  ~37.5% overhead  — low cost, handles burst, not random
  t=64  k=127  ~125% overhead   — high cost, handles both (closest to our 100% OH)

Compared against our scheme from fig4_data.csv (CRC-32, 100% overhead).

Usage:
  python fig_rs_empirical.py --keys 5 --no-plot        # smoke test (fast)
  python fig_rs_empirical.py --keys 30                 # full run (send to server)
"""
from __future__ import annotations

import argparse
import csv
import math
import os
import time
from collections import defaultdict

import numpy as np

from experiments.common import ensure_dir, stable_rng
from experiments.trial_runner import get_flip_indices

FIG4_DATA = "results/fig4/fig4_data.csv"
OUT_DIR   = "results/fig_rs_empirical"
BIT_LENGTH = 4096   # 512 bytes — matches fig4
MAX_FLIP   = 245    # 6% BER of 4096 bits


# ---------------------------------------------------------------------------
# RS engine (galois GF(2^8))
# ---------------------------------------------------------------------------

def _build_rs(t: int):
    """Return a galois.ReedSolomon(255, 255-2t) instance (cached by t)."""
    import galois
    return galois.ReedSolomon(255, 255 - 2 * t), galois.GF(2**8)


_rs_cache: dict[int, tuple] = {}

def rs_correct(data_bytes: bytes, flip_bit_positions: list[int], t: int) -> bool:
    """Inject bit flips into data_bytes, try to correct with RS(255,255-2t).

    Parity is stored separately — errors only affect data, parity is always correct.
    Returns True iff fully corrected.
    """
    if t not in _rs_cache:
        _rs_cache[t] = _build_rs(t)
    rs, GF = _rs_cache[t]

    k = 255 - 2 * t   # data bytes per chunk
    n_bytes = len(data_bytes)

    # Inject errors
    corrupted = bytearray(data_bytes)
    for bp in flip_bit_positions:
        byte_idx, bit_idx = bp >> 3, bp & 7
        if byte_idx < n_bytes:
            corrupted[byte_idx] ^= 1 << bit_idx

    # Process each chunk
    pos = 0
    while pos < n_bytes:
        actual_k = min(k, n_bytes - pos)
        orig_chunk  = bytes(data_bytes[pos : pos + actual_k])
        corr_chunk  = bytes(corrupted[pos   : pos + actual_k])

        # Pad to k bytes for shortened codewords
        if actual_k < k:
            orig_chunk  = orig_chunk  + bytes(k - actual_k)
            corr_chunk  = corr_chunk  + bytes(k - actual_k)

        orig_gf = GF(np.frombuffer(orig_chunk, dtype=np.uint8))
        corr_gf = GF(np.frombuffer(corr_chunk, dtype=np.uint8))

        # Encode original to get correct parity; swap in corrupted data portion
        codeword = rs.encode(orig_gf)
        received = codeword.copy()
        received[:k] = corr_gf

        try:
            decoded = rs.decode(received)
        except Exception:
            return False

        if not np.array_equal(np.asarray(decoded)[:actual_k],
                               np.asarray(orig_gf)[:actual_k]):
            return False
        pos += actual_k

    return True


def overhead(t: int, n_data_bytes: int) -> float:
    k = 255 - 2 * t
    n_chunks = math.ceil(n_data_bytes / k)
    return n_chunks * 2 * t / n_data_bytes


# ---------------------------------------------------------------------------
# Trials
# ---------------------------------------------------------------------------

def run_rs_trials(
    t: int,
    modes: list[str],
    flip_counts: list[int],
    n_keys: int,
    seed: int = 0,
) -> list[dict]:
    data_bytes = bytes((i * 3 + 1) % 256 for i in range(BIT_LENGTH // 8))
    rows = []
    total = len(modes) * len(flip_counts) * n_keys
    done = 0
    t0 = time.time()

    for mode in modes:
        for fc in flip_counts:
            for key_id in range(n_keys):
                rng = stable_rng(seed, key_id, fc, t, mode)
                flips = get_flip_indices(fc, BIT_LENGTH, mode, rng)
                t_trial = time.time()
                ok = rs_correct(data_bytes, flips, t)
                rows.append({
                    "t": t, "mode": mode, "flip_count": fc, "key_id": key_id,
                    "ber": fc / BIT_LENGTH,
                    "fully_corrected": int(ok),
                    "solve_time_ms": round((time.time() - t_trial) * 1000, 3),
                })
                done += 1
                if done % max(1, total // 10) == 0:
                    print(f"  RS t={t}  {done}/{total}  ({time.time()-t0:.1f}s)")
    return rows


def load_fig4() -> dict[tuple, list[float]]:
    """Load fig4 data: {(mode, flip_count): [fully_corrected, ...]}"""
    data: dict[tuple, list[float]] = defaultdict(list)
    with open(FIG4_DATA) as f:
        for r in csv.DictReader(f):
            data[(r["mode"], int(r["flip_count"]))].append(int(r["fully_corrected"]))
    return data


def success_curve(rows: list[dict], mode: str) -> tuple[list[int], list[float], list[float]]:
    from collections import defaultdict
    buckets: dict[int, list[int]] = defaultdict(list)
    for r in rows:
        if r["mode"] == mode:
            buckets[r["flip_count"]].append(r["fully_corrected"])
    xs, ys, errs = [], [], []
    for fc in sorted(buckets):
        vals = buckets[fc]
        n = len(vals)
        rate = sum(vals) / n
        se = math.sqrt(rate * (1 - rate) / n) if n > 1 and 0 < rate < 1 else 0.0
        xs.append(fc)
        ys.append(rate * 100)
        errs.append(se * 100)
    return xs, ys, errs


def fig4_curve(data: dict, mode: str) -> tuple[list[int], list[float], list[float]]:
    xs, ys, errs = [], [], []
    for (m, fc), vals in sorted(data.items(), key=lambda x: x[0][1]):
        if m != mode:
            continue
        n = len(vals)
        rate = sum(vals) / n
        se = math.sqrt(rate * (1 - rate) / n) if n > 1 and 0 < rate < 1 else 0.0
        xs.append(fc)
        ys.append(rate * 100)
        errs.append(se * 100)
    return xs, ys, errs


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--keys",    type=int, default=30)
    p.add_argument("--seed",    type=int, default=0)
    p.add_argument("--out-dir", default=OUT_DIR)
    p.add_argument("--no-plot", action="store_true")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    ensure_dir(args.out_dir)

    flip_counts = list(range(10, MAX_FLIP + 1, 10))
    modes = ["random", "burst"]

    # RS configs: t=32 (burst-only capable, ~37.5% OH) and t=64 (~125% OH, handles both)
    rs_configs = [
        (32, "#ff7f00"),   # orange — low overhead, burst only
        (64, "#4daf4a"),   # green  — high overhead, both
    ]

    fig4_data = load_fig4()

    all_rows: dict[int, list[dict]] = {}
    for t, _ in rs_configs:
        oh = overhead(t, BIT_LENGTH // 8)
        print(f"\nRunning RS t={t} ({oh:.1%} overhead, {args.keys} keys)...")
        all_rows[t] = run_rs_trials(t, modes, flip_counts, args.keys, args.seed)

    if args.no_plot:
        # Print summary
        for t, _ in rs_configs:
            for mode in modes:
                xs, ys, _ = success_curve(all_rows[t], mode)
                rate_at_max = ys[-1] if ys else 0
                print(f"  RS t={t} {mode}: success at {MAX_FLIP} flips = {rate_at_max:.1f}%")
        return

    try:
        import matplotlib.pyplot as plt
    except ModuleNotFoundError as e:
        raise RuntimeError("matplotlib required; use --no-plot") from e

    fig, axes = plt.subplots(1, 2, figsize=(15, 6))
    fig.suptitle(
        "Reed-Solomon vs Our Scheme: Burst and Random Error Correction\n"
        f"(4096-bit block, GF(2⁸) RS with 255-byte codewords)",
        fontsize=13, fontweight="bold",
    )

    our_color_burst  = "#e41a1c"   # red   — our scheme burst
    our_color_random = "#377eb8"   # blue  — our scheme random

    for panel_idx, (mode, ax) in enumerate(zip(["burst", "random"], axes)):
        mode_label = "burst errors" if mode == "burst" else "random errors"

        # Our scheme (from fig4)
        xs_ours, ys_ours, err_ours = fig4_curve(fig4_data, mode)
        color_ours = our_color_burst if mode == "burst" else our_color_random
        ax.errorbar(xs_ours, ys_ours, yerr=err_ours,
                    color=color_ours, linestyle="-", marker="o", linewidth=2.5,
                    capsize=3, label="Ours — CRC-32, 100% overhead",
                    zorder=5)

        # RS configs
        for t, color in rs_configs:
            oh = overhead(t, BIT_LENGTH // 8)
            xs_rs, ys_rs, err_rs = success_curve(all_rows[t], mode)
            ax.errorbar(xs_rs, ys_rs, yerr=err_rs,
                        color=color, linestyle="--", marker="s", linewidth=2,
                        capsize=3, label=f"RS t={t}, {oh:.0%} overhead",
                        zorder=4)

        ax.set_title(f"Success rate vs {mode_label}", fontsize=11)
        ax.set_xlabel("Injected bit-flips")
        ax.set_ylabel("Success rate (%)")
        ax.set_ylim(-5, 108)
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=9)

        ax1_ber = ax.secondary_xaxis("top")
        ber_ticks = flip_counts[::3]
        ax1_ber.set_xticks(ber_ticks)
        ax1_ber.set_xticklabels([f"{fc/BIT_LENGTH:.1%}" for fc in ber_ticks],
                                 fontsize=7, rotation=45)
        ax1_ber.set_xlabel("BER", fontsize=9)

    plt.tight_layout()
    out_path = os.path.join(args.out_dir, "fig_rs_empirical.png")
    plt.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close()
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
