"""Public query API — re-exports core query functions and KBContext."""
from __future__ import annotations

from ewankb.context import KBContext

from ewankb.tools.graph_runtime.query_engine import (
    query,
    query_graph_json,
    load_graph,
    score_nodes,
    bfs_traverse,
    dfs_traverse,
    subgraph_to_text,
    get_node_info,
    get_neighbors,
)

from ewankb.tools.graph_runtime.kb_query import query_kb

from ewankb.tools.graph_runtime.bm25_index import load_or_build, DocEntry

__all__ = [
    "KBContext",
    "query",
    "query_graph_json",
    "load_graph",
    "score_nodes",
    "bfs_traverse",
    "dfs_traverse",
    "subgraph_to_text",
    "get_node_info",
    "get_neighbors",
    "query_kb",
    "load_or_build",
    "DocEntry",
]