"""Figure 2: Correction success rate vs block size, BER, and hash width.

Reads raw trial data from --data-file (output of fig1_performance.py) if provided;
otherwise runs the same sweep independently and saves to --out-dir/raw_data.csv.

Layout: 1 row × 3 cols
  Col 0: Success rate vs BER         (lines = block_size, fixed hash_bits = 32)
  Col 1: Success rate vs block size  (lines = hash_bits,  fixed BER = 3%)
  Col 2: Success rate vs hash width  (lines = BER,        fixed block_size = 4096)
"""
from __future__ import annotations

import argparse
import csv
import math
import os
from typing import Any

from experiments.common import (
    ensure_dir,
    stable_key,
    stable_rng,
    write_csv,
    write_json,
)
from experiments.trial_runner import get_flip_indices, run_trials_parallel, run_trials_serial

DEFAULT_BIT_LENGTHS = [256, 512, 1024, 2048, 4096]
DEFAULT_HASH_BITS = [8, 16, 32]
DEFAULT_BER_VALUES = [0.01, 0.02, 0.03, 0.04, 0.05, 0.06]
DEFAULT_KEYS = 20
DEFAULT_ROUNDS = 8
GROUP_SIZE = 1

FIXED_BER = 0.03
FIXED_HASH_BITS = 32
FIXED_BIT_LENGTH = 4096
LINE_BIT_LENGTHS = [256, 1024, 4096]
LINE_BER_VALUES = [0.01, 0.03, 0.05]


def parse_float_list(spec: str) -> list[float]:
    return [float(x.strip()) for x in spec.split(",") if x.strip()]


def parse_int_list(spec: str) -> list[int]:
    return [int(x.strip()) for x in spec.split(",") if x.strip()]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Figure 2: Success rate sweep")
    p.add_argument("--data-file", type=str, default=None,
                   help="Path to raw_data.csv from fig1_performance.py; runs own sweep if omitted")
    p.add_argument("--bit-lengths", type=str, default=",".join(str(x) for x in DEFAULT_BIT_LENGTHS))
    p.add_argument("--hash-bits", type=str, default=",".join(str(x) for x in DEFAULT_HASH_BITS))
    p.add_argument("--ber-values", type=str, default=",".join(str(x) for x in DEFAULT_BER_VALUES))
    p.add_argument("--keys", type=int, default=DEFAULT_KEYS)
    p.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out-dir", type=str, default="results/fig2")
    p.add_argument("--no-plot", action="store_true")
    p.add_argument("--parallel", action="store_true")
    p.add_argument("--workers", type=int, default=0)
    p.add_argument("--max-combos", type=int, default=None,
                   help="Max combinations tried per trial (default: unlimited)")
    return p.parse_args()


def _load_csv(path: str) -> list[dict]:
    rows = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            rows.append({
                "bit_length": int(row["bit_length"]),
                "hash_bits": int(row["hash_bits"]),
                "ber": float(row["ber"]),
                "flip_count": int(row["flip_count"]),
                "key_id": int(row["key_id"]),
                "fully_corrected": int(row["fully_corrected"]),
                "solve_time_ms": float(row["solve_time_ms"]),
                "total_combos_evaluated": int(row["total_combos_evaluated"]),
            })
    return rows


def _run_sweep(args, bit_lengths, hash_bits_list, ber_values) -> list[dict[str, Any]]:
    all_tasks: list[tuple] = []
    all_metas: list[tuple] = []

    for bit_length in bit_lengths:
        bits = [(i * 3 + 1) % 2 for i in range(bit_length)]
        for hash_bits in hash_bits_list:
            for ber in ber_values:
                flip_count = round(ber * bit_length)
                if flip_count < 1:
                    continue
                for key_id in range(args.keys):
                    key = stable_key(args.seed, key_id)
                    rng = stable_rng(args.seed, key_id, bit_length, hash_bits, ber, "random")
                    flip_indices = get_flip_indices(flip_count, bit_length, "random", rng)
                    all_tasks.append((
                        bits, key, args.rounds, flip_indices,
                        GROUP_SIZE, GROUP_SIZE, hash_bits, "include_partial", args.max_combos, 0, "crc", 1, 1,
                    ))
                    all_metas.append((bit_length, hash_bits, ber, key_id, flip_count))

    print(f"Running {len(all_tasks)} trials...")
    if args.parallel:
        flat_results = run_trials_parallel(all_tasks, args.workers)
    else:
        flat_results = run_trials_serial(all_tasks)

    rows = []
    for trial, (bit_length, hash_bits, ber, key_id, flip_count) in zip(flat_results, all_metas):
        rows.append({
            "bit_length": bit_length,
            "hash_bits": hash_bits,
            "ber": ber,
            "flip_count": flip_count,
            "key_id": key_id,
            "fully_corrected": int(trial["fully_corrected"]),
            "solve_time_ms": trial["solve_time_ms"],
            "total_combos_evaluated": trial["total_combos_evaluated"],
        })
    return rows


def _filter(rows, bit_length=None, hash_bits=None, ber=None):
    out = rows
    if bit_length is not None:
        out = [r for r in out if r["bit_length"] == bit_length]
    if hash_bits is not None:
        out = [r for r in out if r["hash_bits"] == hash_bits]
    if ber is not None:
        out = [r for r in out if abs(r["ber"] - ber) < 1e-9]
    return out


def _success_series(rows, x_key, x_vals, **fixed):
    """Return (xs, rates_pct, binomial_se_pct) for a success-rate line."""
    xs, ys, errs = [], [], []
    for xv in x_vals:
        subset = _filter(rows, **dict(fixed, **{x_key: xv}))
        if not subset:
            continue
        n = len(subset)
        p = sum(r["fully_corrected"] for r in subset) / n
        se = math.sqrt(p * (1 - p) / n) if n > 1 and 0 < p < 1 else 0.0
        xs.append(xv)
        ys.append(p * 100)
        errs.append(se * 100)
    return xs, ys, errs


def main() -> None:
    args = parse_args()
    bit_lengths = parse_int_list(args.bit_lengths)
    hash_bits_list = parse_int_list(args.hash_bits)
    ber_values = parse_float_list(args.ber_values)

    ensure_dir(args.out_dir)

    if args.data_file:
        print(f"Loading data from {args.data_file}")
        rows = _load_csv(args.data_file)
        # Infer parameter ranges from data
        bit_lengths = sorted(set(r["bit_length"] for r in rows))
        hash_bits_list = sorted(set(r["hash_bits"] for r in rows))
        ber_values = sorted(set(r["ber"] for r in rows))
    else:
        write_json(os.path.join(args.out_dir, "config.json"), {
            "bit_lengths": bit_lengths,
            "hash_bits": hash_bits_list,
            "ber_values": ber_values,
            "keys": args.keys,
            "rounds": args.rounds,
            "seed": args.seed,
            "group_size": GROUP_SIZE,
        })
        rows = _run_sweep(args, bit_lengths, hash_bits_list, ber_values)
        csv_path = os.path.join(args.out_dir, "raw_data.csv")
        write_csv(csv_path, rows, [
            "bit_length", "hash_bits", "ber", "flip_count", "key_id",
            "fully_corrected", "solve_time_ms", "total_combos_evaluated",
        ])
        print(f"Data saved to {csv_path}")

    if args.no_plot:
        return

    try:
        import matplotlib.pyplot as plt
    except ModuleNotFoundError as e:
        raise RuntimeError("matplotlib required; install it or use --no-plot") from e

    hb_colors = {8: "#e41a1c", 16: "#377eb8", 32: "#4daf4a"}
    bl_colors = {256: "#8dd3c7", 512: "#ffffb3", 1024: "#fb8072", 2048: "#bebada", 4096: "#80b1d3"}
    ber_colors = {0.01: "#e41a1c", 0.03: "#377eb8", 0.05: "#4daf4a"}

    fig, axes = plt.subplots(1, 3, figsize=(18, 6))
    fig.suptitle("Approximate ECC: Correction Success Rate", fontsize=14, fontweight="bold")

    # Col 0: Success rate vs BER — lines = block_size subset, fixed hash_bits
    ax = axes[0]
    line_bl = [bl for bl in LINE_BIT_LENGTHS if bl in bit_lengths]
    for bl in line_bl:
        xs_raw, ys, errs = _success_series(rows, "ber", ber_values, bit_length=bl, hash_bits=FIXED_HASH_BITS)
        xs = [v * 100 for v in xs_raw]
        ax.errorbar(xs, ys, yerr=errs, marker="o", linewidth=2, capsize=3,
                    label=f"L={bl}", color=bl_colors.get(bl, "gray"))
    ax.axhline(100, linestyle="--", color="gray", linewidth=1, alpha=0.5)
    ax.set_title(f"Success rate vs BER  ({FIXED_HASH_BITS}-bit hash)")
    ax.set_xlabel("BER (%)")
    ax.set_ylabel("Success rate (%)")
    ax.set_xticks([v * 100 for v in ber_values])
    ax.set_ylim(-5, 105)
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=9)

    # Col 1: Success rate vs block size — lines = hash_bits, fixed BER
    ax = axes[1]
    for hb in hash_bits_list:
        xs, ys, errs = _success_series(rows, "bit_length", bit_lengths, hash_bits=hb, ber=FIXED_BER)
        ax.errorbar(xs, ys, yerr=errs, marker="o", linewidth=2, capsize=3,
                    label=f"{hb}-bit CRC", color=hb_colors.get(hb, "gray"))
    ax.axhline(100, linestyle="--", color="gray", linewidth=1, alpha=0.5)
    ax.set_title(f"Success rate vs block size  (BER={FIXED_BER:.0%})")
    ax.set_xlabel("Block size (bits)")
    ax.set_ylabel("Success rate (%)")
    ax.set_xscale("log", base=2)
    ax.set_xticks(bit_lengths)
    ax.set_xticklabels([str(b) for b in bit_lengths])
    ax.set_ylim(-5, 105)
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=9)

    # Col 2: Success rate vs hash width — lines = BER subset, fixed block_size
    ax = axes[2]
    line_ber = [b for b in LINE_BER_VALUES if any(abs(v - b) < 1e-9 for v in ber_values)]
    fixed_bl = FIXED_BIT_LENGTH if FIXED_BIT_LENGTH in bit_lengths else bit_lengths[-1]
    for ber in line_ber:
        xs, ys, errs = _success_series(rows, "hash_bits", hash_bits_list, bit_length=fixed_bl, ber=ber)
        ax.errorbar(xs, ys, yerr=errs, marker="o", linewidth=2, capsize=3,
                    label=f"BER={ber:.0%}", color=ber_colors.get(ber, "gray"))
    ax.axhline(100, linestyle="--", color="gray", linewidth=1, alpha=0.5)
    ax.set_title(f"Success rate vs hash width  (L={fixed_bl})")
    ax.set_xlabel("Hash width (bits)")
    ax.set_ylabel("Success rate (%)")
    ax.set_xticks(hash_bits_list)
    ax.set_ylim(-5, 105)
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=9)

    plt.tight_layout()
    out_path = os.path.join(args.out_dir, "fig2_success_rate.png")
    plt.savefig(out_path, dpi=200)
    plt.close()
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
