"""Graphviz-based visualization for the hash-node graph."""

from __future__ import annotations

from pathlib import Path

from hash_dag import HashGraph

try:
    # Python package: `pip install graphviz`
    from graphviz import Graph  # type: ignore

except ImportError:  # pragma: no cover
    Graph = None  # type: ignore


def render_hash_dag_png(
    dag: HashGraph,
    out_path: str,
    mismatched_node_ids: set[str],
    *,
    show_edge_weights: bool = True,
    matched_color: str = "#d9ead3",
    mismatched_color: str = "#f4cccc",
) -> str:
    """
    Render a graph PNG.

    Nodes are colored as mismatched vs matched relative to the baseline digests
    (based on `mismatched_node_ids`).
    """

    if Graph is None:  # pragma: no cover
        raise RuntimeError(
            "Missing dependency for graph rendering. Install Python package "
            "`graphviz` (e.g., `pip install graphviz`). Also ensure the Graphviz "
            "`dot` binary is installed system-wide."
        )

    out_file = Path(out_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    # The graphviz Python API uses `filename` + `directory`.
    filename_no_ext = out_file.stem
    directory = str(out_file.parent)

    dot = Graph(name=filename_no_ext, format="png")
    dot.attr(rankdir="LR", concentrate="true")
    dot.attr("node", shape="box", style="filled", fontname="Helvetica")

    for node_id in sorted(dag.nodes.keys()):
        node = dag.nodes[node_id]
        is_mismatched = node_id in mismatched_node_ids
        fillcolor = mismatched_color if is_mismatched else matched_color
        dot.node(
            node_id,
            label=node.node_id,
            fillcolor=fillcolor,
            fontcolor="black",
        )

    for edge in dag.edges:
        edge_attrs: dict[str, str] = {}
        if show_edge_weights:
            edge_attrs["label"] = str(edge.weight)
            edge_attrs["fontsize"] = "9"
        dot.edge(edge.src, edge.dst, **edge_attrs)

    # cleanup=True removes the intermediate .dot file.
    rendered_path = dot.render(
        filename=filename_no_ext,
        directory=directory,
        cleanup=True,
    )
    return rendered_path

