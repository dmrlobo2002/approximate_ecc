"""Figure: BCH burst failure vs our CRC-32 burst resilience.

BCH applied to 16 × 256-bit blocks (t=19, sized for 95% success at 5% BER) fails
the moment a burst exceeds 19 bits in any single block.
Our scheme handles 200+ bit bursts via the Feistel permutation.

Outputs:
  results/fig_bch_burst/fig_bch_burst.csv
  results/fig_bch_burst/fig_bch_burst.png
"""
from __future__ import annotations

import argparse
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any

import bchlib

from experiments.common import (
    ensure_dir,
    stable_key,
    stable_rng,
    write_csv,
    write_json,
)
from experiments.trial_runner import get_flip_indices, run_trial

# BCH parameters: t = round(0.05 × 256) = 13 (expected errors at 5% BER)
BCH_BLOCK_BITS = 256
BCH_BLOCK_BYTES = BCH_BLOCK_BITS // 8
BCH_T = 13          # t = round(BER × block) = round(0.05 × 256)
BCH_M = 9           # GF(2^9), n=511 — minimum field that fits 256-bit data

# Our scheme parameters
HASH_BITS  = 32
GROUP_SIZE = 1
ROUNDS     = 8

# Burst lengths: dense near the BCH cliff (t=19), sparse beyond
BURST_LENGTHS = [1, 5, 10, 15, 18, 19, 20, 21, 25, 30, 40, 50, 75, 100, 150, 200, 245]

DEFAULT_BIT_LENGTH = 4096
DEFAULT_KEYS       = 30
DEFAULT_SEED       = 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="BCH burst failure vs our CRC-32 burst resilience"
    )
    p.add_argument("--bit-length", type=int, default=DEFAULT_BIT_LENGTH)
    p.add_argument("--keys",       type=int, default=DEFAULT_KEYS)
    p.add_argument("--seed",       type=int, default=DEFAULT_SEED)
    p.add_argument("--out-dir",    type=str, default="results/fig_bch_burst")
    p.add_argument("--no-plot",    action="store_true")
    p.add_argument("--parallel",   action="store_true")
    p.add_argument("--workers",    type=int, default=0)
    return p.parse_args()


# ── BCH burst trial ───────────────────────────────────────────────────────────

def _bch_burst_task(args_tuple: tuple) -> bool:
    bit_length, t, burst_len, key_id, seed = args_tuple
    n_blocks = bit_length // BCH_BLOCK_BITS
    bch = bchlib.BCH(t, m=BCH_M)

    rng = stable_rng(seed, key_id, burst_len, t, "bch_burst")

    # Generate random data for each block
    all_data = [bytearray(rng.randbytes(BCH_BLOCK_BYTES)) for _ in range(n_blocks)]
    all_ecc  = [bytearray(bch.encode(d)) for d in all_data]

    # Apply burst at a random position across the full bit_length
    max_start = bit_length - burst_len
    burst_start = rng.randint(0, max_start)

    corrupted = [bytearray(d) for d in all_data]
    for bit in range(burst_start, burst_start + burst_len):
        blk = bit // BCH_BLOCK_BITS
        off = bit % BCH_BLOCK_BITS
        corrupted[blk][off // 8] ^= 1 << (off % 8)

    # Decode each block
    for i in range(n_blocks):
        ecc_copy = bytearray(all_ecc[i])
        nerr = bch.decode(corrupted[i], ecc_copy)
        if nerr < 0:
            return False
        bch.correct(corrupted[i], ecc_copy)
        if corrupted[i] != all_data[i]:
            return False
    return True


# ── Our scheme burst trial ────────────────────────────────────────────────────

def _our_burst_task(args_tuple: tuple) -> dict[str, Any]:
    bits, key, rounds, flip_indices = args_tuple
    return run_trial(bits, key, rounds, flip_indices,
                     GROUP_SIZE, GROUP_SIZE, HASH_BITS,
                     "include_partial", None, 0, "crc", 1, 1)


def _make_bits(bit_length: int, seed: int) -> list[int]:
    rng = stable_rng(seed, "bits")
    return [rng.randint(0, 1) for _ in range(bit_length)]


def run_all(args) -> list[dict]:
    bit_length = args.bit_length
    assert bit_length % BCH_BLOCK_BITS == 0, \
        f"bit_length must be a multiple of {BCH_BLOCK_BITS}"

    bits = _make_bits(bit_length, args.seed)
    rows: list[dict] = []

    # Build task lists for both schemes
    bch_tasks, our_tasks, metas = [], [], []
    for burst_len in BURST_LENGTHS:
        for key_id in range(args.keys):
            # BCH task
            bch_tasks.append((bit_length, BCH_T, burst_len, key_id, args.seed))
            # Our scheme task
            key = stable_key(args.seed, key_id)
            rng = stable_rng(args.seed, key_id, burst_len, "our_burst")
            flip_indices = get_flip_indices(burst_len, bit_length, "burst", rng)
            our_tasks.append((bits, key, ROUNDS, flip_indices))
            metas.append((burst_len, key_id))

    total = len(metas)
    print(f"Running {total} BCH trials and {total} our-scheme trials "
          f"({len(BURST_LENGTHS)} burst lengths × {args.keys} keys)...")

    if args.parallel:
        workers = args.workers or None
        bch_results  = [None] * total
        our_results  = [None] * total

        with ProcessPoolExecutor(max_workers=workers) as ex:
            bch_futs = {ex.submit(_bch_burst_task, t): i
                        for i, t in enumerate(bch_tasks)}
            our_futs = {ex.submit(_our_burst_task, t): i
                        for i, t in enumerate(our_tasks)}
            done = 0
            for fut in as_completed({**bch_futs, **our_futs}):
                done += 1
                if done % max(1, total // 20) == 0:
                    print(f"  Progress: {done}/{total*2} ({100*done/(total*2):.0f}%)")
                if fut in bch_futs:
                    bch_results[bch_futs[fut]] = fut.result()
                else:
                    our_results[our_futs[fut]] = fut.result()
    else:
        bch_results = [_bch_burst_task(t) for t in bch_tasks]
        our_results = [_our_burst_task(t) for t in our_tasks]

    for i, (burst_len, key_id) in enumerate(metas):
        rows.append({
            "scheme":    "BCH (16×256-bit, t=19)",
            "burst_len": burst_len,
            "key_id":    key_id,
            "success":   int(bch_results[i]),
        })
        rows.append({
            "scheme":    "Ours (CRC-32)",
            "burst_len": burst_len,
            "key_id":    key_id,
            "success":   int(our_results[i]["fully_corrected"]),
        })

    return rows


def main() -> None:
    args = parse_args()
    ensure_dir(args.out_dir)

    write_json(os.path.join(args.out_dir, "config.json"), {
        "bit_length":   args.bit_length,
        "keys":         args.keys,
        "bch_t":        BCH_T,
        "bch_m":        BCH_M,
        "bch_block":    BCH_BLOCK_BITS,
        "hash_bits":    HASH_BITS,
        "burst_lengths": BURST_LENGTHS,
        "seed":         args.seed,
    })

    rows = run_all(args)

    write_csv(os.path.join(args.out_dir, "fig_bch_burst.csv"), rows,
              ["scheme", "burst_len", "key_id", "success"])

    # Print summary
    from collections import defaultdict
    groups: dict = defaultdict(lambda: defaultdict(list))
    for r in rows:
        groups[r["scheme"]][r["burst_len"]].append(r["success"])

    print("\nSuccess rate vs burst length:")
    print(f"  {'burst':>6}  {'BCH':>8}  {'Ours':>8}")
    print(f"  {'-'*28}")
    for bl in BURST_LENGTHS:
        bch_rate = sum(groups["BCH (16×256-bit, t=19)"][bl]) / args.keys
        our_rate = sum(groups["Ours (CRC-32)"][bl]) / args.keys
        print(f"  {bl:>6}  {bch_rate:>8.1%}  {our_rate:>8.1%}")

    if args.no_plot:
        return

    try:
        import matplotlib.pyplot as plt
        import matplotlib.ticker as ticker
    except ModuleNotFoundError as e:
        raise RuntimeError("matplotlib required; use --no-plot to skip") from e

    fig, ax = plt.subplots(figsize=(10, 6))
    fig.suptitle(
        f"BCH Burst Failure vs Our Scheme  "
        f"(4096-bit block, 5% BER operating point)",
        fontsize=13, fontweight="bold",
    )

    colors = {
        "BCH (16×256-bit, t=19)": "#e41a1c",
        "Ours (CRC-32)":          "#377eb8",
    }
    markers = {
        "BCH (16×256-bit, t=19)": "s",
        "Ours (CRC-32)":          "o",
    }

    for scheme in ["BCH (16×256-bit, t=19)", "Ours (CRC-32)"]:
        xs, ys, errs = [], [], []
        for bl in BURST_LENGTHS:
            vals = groups[scheme][bl]
            n = len(vals)
            rate = sum(vals) / n
            sem  = (rate * (1 - rate) / n) ** 0.5
            xs.append(bl)
            ys.append(rate * 100)
            errs.append(sem * 100)
        ax.errorbar(xs, ys, yerr=errs,
                    color=colors[scheme], marker=markers[scheme],
                    linewidth=2.5, markersize=7, capsize=4,
                    label=scheme)

    # Mark the BCH cliff
    ax.axvline(BCH_T, color="#e41a1c", linestyle="--", linewidth=1.2, alpha=0.6)
    ax.annotate(f"BCH cliff\n(burst > t={BCH_T})",
                xy=(BCH_T, 50), xytext=(BCH_T + 15, 55),
                fontsize=10, color="#e41a1c",
                arrowprops=dict(arrowstyle="->", color="#e41a1c", lw=1.2))

    ax.set_xlabel("Burst length (bits)", fontsize=12)
    ax.set_ylabel("Success rate (%)", fontsize=12)
    ax.set_ylim(-5, 105)
    ax.set_xlim(0, max(BURST_LENGTHS) + 5)
    ax.yaxis.set_major_formatter(ticker.PercentFormatter())
    ax.legend(fontsize=11, loc="center right")
    ax.grid(True, alpha=0.3)

    label = (f"BCH: 16 × BCH(256-bit, t={BCH_T}), overhead={BCH_T*9*16/4096*100:.0f}%\n"
             f"Ours: CRC-32, overhead=100%\n"
             f"Both sized for 5% BER operation  ·  {args.keys} keys")
    ax.text(0.02, 0.05, label, transform=ax.transAxes,
            fontsize=9, verticalalignment="bottom",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="lightyellow", alpha=0.8))

    plt.tight_layout()
    out = os.path.join(args.out_dir, "fig_bch_burst.png")
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
