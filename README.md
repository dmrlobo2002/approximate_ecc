# Approximate_ECC
Codebase for Approximate ECC Paper
## DAG Visualization (PNG)

The `demo.py` script can optionally render the hash-node DAG as PNG files (with nodes
colored to show which hash checks currently mismatch the baseline).

Dependencies:
- System Graphviz binaries (the `dot` executable)
- Python package `graphviz` (install via `pip install graphviz`)

Example:
```bash
python3 demo.py --bit-length 1024 --hash-bits 16 --row-group-size 1 --col-group-size 1 --flip-count 2 --seed 1
```

Outputs:
- `dag_viz/<viz-prefix>_step_XX_<row_or_col_group>.png`
