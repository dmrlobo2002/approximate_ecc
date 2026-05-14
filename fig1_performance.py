"""Figure 1: Solver performance — solve time and comparisons vs block size, BER, and hash width.

Layout: 2 rows × 3 cols
  Row 0: Mean solve time (ms)
  Row 1: Mean comparisons evaluated
  Col 0: vs block size  (lines = hash_bits,  fixed BER = 3%)
  Col 1: vs BER         (lines = block_size, fixed hash_bits = 32)
  Col 2: vs hash width  (lines = BER,        fixed block_size = 4096)
"""
from __future__ import annotations

import argparse
import os
from typing import Any

from experiments.common import (
    agg,
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
    p = argparse.ArgumentParser(description="Figure 1: Solver performance sweep")
    p.add_argument("--bit-lengths", type=str, default=",".join(str(x) for x in DEFAULT_BIT_LENGTHS))
    p.add_argument("--hash-bits", type=str, default=",".join(str(x) for x in DEFAULT_HASH_BITS))
    p.add_argument("--ber-values", type=str, default=",".join(str(x) for x in DEFAULT_BER_VALUES))
    p.add_argument("--keys", type=int, default=DEFAULT_KEYS)
    p.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out-dir", type=str, default="results/fig1")
    p.add_argument("--no-plot", action="store_true")
    p.add_argument("--parallel", action="store_true")
    p.add_argument("--workers", type=int, default=0)
    return p.parse_args()


def _filter(rows: list[dict], bit_length=None, hash_bits=None, ber=None) -> list[dict]:
    out = rows
    if bit_length is not None:
        out = [r for r in out if r["bit_length"] == bit_length]
    if hash_bits is not None:
        out = [r for r in out if r["hash_bits"] == hash_bits]
    if ber is not None:
        out = [r for r in out if abs(r["ber"] - ber) < 1e-9]
    return out


def _series(rows, x_key, x_vals, metric, **fixed):
    xs, ys, errs = [], [], []
    for xv in x_vals:
        subset = _filter(rows, **dict(fixed, **{x_key: xv}))
        if not subset:
            continue
        a = agg([r[metric] for r in subset])
        xs.append(xv)
        ys.append(a.mean)
        errs.append(a.sem)
    return xs, ys, errs


def main() -> None:
    args = parse_args()
    bit_lengths = parse_int_list(args.bit_lengths)
    hash_bits_list = parse_int_list(args.hash_bits)
    ber_values = parse_float_list(args.ber_values)

    ensure_dir(args.out_dir)
    write_json(os.path.join(args.out_dir, "config.json"), {
        "bit_lengths": bit_lengths,
        "hash_bits": hash_bits_list,
        "ber_values": ber_values,
        "keys": args.keys,
        "rounds": args.rounds,
        "seed": args.seed,
        "group_size": GROUP_SIZE,
    })

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
                        GROUP_SIZE, GROUP_SIZE, hash_bits, "include_partial", None, 0, "crc", 1, 1,
                    ))
                    all_metas.append((bit_length, hash_bits, ber, key_id, flip_count))

    print(f"Running {len(all_tasks)} trials...")
    if args.parallel:
        flat_results = run_trials_parallel(all_tasks, args.workers)
    else:
        flat_results = run_trials_serial(all_tasks)

    rows: list[dict[str, Any]] = []
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

    fig, axes = plt.subplots(2, 3, figsize=(18, 10))
    fig.suptitle("Approximate ECC: Solver Performance", fontsize=14, fontweight="bold")

    for row_idx, (metric, row_label) in enumerate(zip(
        ["solve_time_ms", "total_combos_evaluated"],
        ["Mean solve time (ms)", "Mean comparisons evaluated"],
    )):
        short = ["Solve time", "Comparisons"][row_idx]

        # Col 0: vs block size — lines = hash_bits, fixed BER = FIXED_BER
        ax = axes[row_idx, 0]
        for hb in hash_bits_list:
            xs, ys, errs = _series(rows, "bit_length", bit_lengths, metric, hash_bits=hb, ber=FIXED_BER)
            ax.errorbar(xs, ys, yerr=errs, marker="o", linewidth=2, capsize=3,
                        label=f"{hb}-bit CRC", color=hb_colors.get(hb, "gray"))
        ax.set_title(f"{short} vs block size  (BER={FIXED_BER:.0%})")
        ax.set_xlabel("Block size (bits)")
        ax.set_ylabel(row_label)
        ax.set_xscale("log", base=2)
        ax.set_xticks(bit_lengths)
        ax.set_xticklabels([str(b) for b in bit_lengths])
        ax.set_yscale("log")
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=9)

        # Col 1: vs BER — lines = block_size subset, fixed hash_bits = FIXED_HASH_BITS
        ax = axes[row_idx, 1]
        for bl in LINE_BIT_LENGTHS:
            xs_raw, ys, errs = _series(rows, "ber", ber_values, metric, bit_length=bl, hash_bits=FIXED_HASH_BITS)
            xs = [v * 100 for v in xs_raw]
            ax.errorbar(xs, ys, yerr=errs, marker="o", linewidth=2, capsize=3,
                        label=f"L={bl}", color=bl_colors.get(bl, "gray"))
        ax.set_title(f"{short} vs BER  ({FIXED_HASH_BITS}-bit hash)")
        ax.set_xlabel("BER (%)")
        ax.set_ylabel(row_label)
        ax.set_xticks([v * 100 for v in ber_values])
        ax.set_yscale("log")
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=9)

        # Col 2: vs hash width — lines = BER subset, fixed block_size = FIXED_BIT_LENGTH
        ax = axes[row_idx, 2]
        for ber in LINE_BER_VALUES:
            xs, ys, errs = _series(rows, "hash_bits", hash_bits_list, metric,
                                   bit_length=FIXED_BIT_LENGTH, ber=ber)
            ax.errorbar(xs, ys, yerr=errs, marker="o", linewidth=2, capsize=3,
                        label=f"BER={ber:.0%}", color=ber_colors.get(ber, "gray"))
        ax.set_title(f"{short} vs hash width  (L={FIXED_BIT_LENGTH})")
        ax.set_xlabel("Hash width (bits)")
        ax.set_ylabel(row_label)
        ax.set_xticks(hash_bits_list)
        ax.set_yscale("log")
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=9)

    plt.tight_layout()
    out_path = os.path.join(args.out_dir, "fig1_performance.png")
    plt.savefig(out_path, dpi=200)
    plt.close()
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
