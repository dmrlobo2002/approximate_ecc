from __future__ import annotations

import argparse
import math
import os
from typing import Any

from grid_shuffle import bits_to_grid, source_index_to_grid_coord

from experiments.common import Agg, agg, ensure_dir, parse_int_list, stable_key, write_csv, write_json


EXPECTED_UNIT_SQUARE_DISTANCE = 0.521405  # E[distance] for two uniform points in [0,1]^2


def _unit_square_points(L: int, key: bytes, rounds: int) -> tuple[list[tuple[float, float]], int]:
    bits = [0] * L
    _grid, meta = bits_to_grid(bits, key=key, rounds=rounds)
    n = meta.n
    pts: list[tuple[float, float]] = []
    for i in range(L):
        r, c = source_index_to_grid_coord(i, meta)
        x = (c + 0.5) / n
        y = (r + 0.5) / n
        pts.append((x, y))
    return pts, n


def adjacency_distances(points: list[tuple[float, float]]) -> list[float]:
    out: list[float] = []
    for i in range(len(points) - 1):
        x1, y1 = points[i]
        x2, y2 = points[i + 1]
        out.append(math.hypot(x2 - x1, y2 - y1))
    return out


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Figure A: Feistel shuffle quality via adjacency Euclidean distances")
    p.add_argument("--lengths", type=str, default="64,256,1024", help="Comma-separated bit-lengths L")
    p.add_argument("--rounds", type=str, default="1,2,4,8,12", help="Comma-separated Feistel rounds")
    p.add_argument("--keys", type=int, default=20, help="Number of random (deterministic) keys")
    p.add_argument("--seed", type=int, default=0, help="Seed for deterministic key derivation")
    p.add_argument("--out-dir", type=str, default="results/fig_a", help="Output directory")
    p.add_argument("--no-plot", action="store_true", help="Write CSV only (skip PNG plotting)")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    lengths = parse_int_list(args.lengths)
    rounds_list = parse_int_list(args.rounds)
    if not lengths or not rounds_list:
        raise ValueError("must provide non-empty --lengths and --rounds")
    if args.keys <= 0:
        raise ValueError("--keys must be positive")

    out_dir = args.out_dir
    ensure_dir(out_dir)

    config: dict[str, Any] = {
        "lengths": lengths,
        "rounds": rounds_list,
        "keys": args.keys,
        "seed": args.seed,
        "expected_unit_square_distance": EXPECTED_UNIT_SQUARE_DISTANCE,
        "metric": "adjacent_source_indices_euclidean_distance_in_unit_square",
        "point_mapping": "x=(c+0.5)/n, y=(r+0.5)/n from source_index_to_grid_coord",
    }
    write_json(os.path.join(out_dir, "config.json"), config)

    rows: list[dict[str, Any]] = []
    for L in lengths:
        for rounds in rounds_list:
            for key_id in range(args.keys):
                key = stable_key(args.seed, key_id)
                pts, n = _unit_square_points(L=L, key=key, rounds=rounds)
                ds = adjacency_distances(pts)
                a = agg(ds)
                rows.append(
                    {
                        "L": L,
                        "rounds": rounds,
                        "key_id": key_id,
                        "n": n,
                        "mean_adj_dist": a.mean,
                        "stdev_adj_dist": a.stdev,
                        "count_pairs": len(ds),
                    }
                )

    csv_path = os.path.join(out_dir, "figure_a_shuffle.csv")
    write_csv(
        csv_path,
        rows=rows,
        fieldnames=["L", "rounds", "key_id", "n", "mean_adj_dist", "stdev_adj_dist", "count_pairs"],
    )

    if args.no_plot:
        return

    # Plot: mean adjacency distance vs rounds, error bars over keys, separate series per L.
    try:
        import matplotlib.pyplot as plt
    except ModuleNotFoundError as e:
        raise RuntimeError(
            "matplotlib is required for plotting. Install it (e.g., `pip install matplotlib`) or rerun with --no-plot."
        ) from e

    # Aggregate over keys for each (L, rounds)
    series: dict[tuple[int, int], list[float]] = {}
    for r in rows:
        series.setdefault((int(r["L"]), int(r["rounds"])), []).append(float(r["mean_adj_dist"]))

    plt.figure(figsize=(8, 5))
    for L in lengths:
        xs = []
        ys = []
        yerr = []
        for rounds in rounds_list:
            vals = series.get((L, rounds), [])
            a = agg(vals)
            xs.append(rounds)
            ys.append(a.mean)
            yerr.append(a.sem)
        plt.errorbar(xs, ys, yerr=yerr, marker="o", linewidth=2, capsize=3, label=f"L={L}")

    plt.axhline(EXPECTED_UNIT_SQUARE_DISTANCE, linestyle="--", linewidth=2, label="E[D] random points (~0.5214)")
    plt.title("Feistel shuffle quality: adjacency Euclidean distance")
    plt.xlabel("Feistel rounds")
    plt.ylabel("Mean distance between adjacent source indices (unit square)")
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.savefig(os.path.join(out_dir, "figure_a_shuffle.png"), dpi=200)


if __name__ == "__main__":
    main()

