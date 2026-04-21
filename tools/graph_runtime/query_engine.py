#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Graph query engine — traverse and render subgraphs within token budget.

Core algorithm (matching graphify's serve.py):
  1. Score nodes by keyword match with query
  2. BFS or DFS traversal from matched nodes
  3. Render subgraph to text within token budget

Token budget: ~budget_tokens * chars_per_token characters.
BFS: breadth-first — good for getting an overview of connected concepts
DFS: depth-first — good for tracing a single execution path
"""
from __future__ import annotations

import json
import re
import networkx as nx
from pathlib import Path
from typing import Any

from tools import config_loader as cfg
from tools.text_utils import extract_keywords


# ── Graph loading ────────────────────────────────────────────────────────────

def load_graph(graph_file: Path | None = None) -> tuple[dict[str, Any], nx.DiGraph]:
    """Load graph.json and build NetworkX DiGraph for traversal."""
    if graph_file is None:
        graph_file = cfg.get_graph_dir() / "graph.json"

    with open(graph_file, encoding="utf-8") as f:
        data = json.load(f)

    G = nx.DiGraph()
    for node in data["nodes"]:
        G.add_node(node["id"], **node)
    for link in data["links"]:
        if link["source"] in G and link["target"] in G:
            G.add_edge(link["source"], link["target"], **link)

    return data, G


# ── Node scoring ─────────────────────────────────────────────────────────────

def score_nodes(G: nx.DiGraph, query: str) -> list[tuple[str, float]]:
    """
    Score all nodes by relevance to query keywords.

    Returns [(node_id, score), ...] sorted descending by score.
    Score factors:
      - Exact keyword match in label (weight: 3.0)
      - Partial keyword match in label (weight: 1.5)
      - Match in docstring/signature (weight: 0.8)
      - Node type bonus (function > class > module > concept > document)
    """
    query_keywords = extract_keywords(query)
    if not query_keywords:
        query_keywords = {w.lower() for w in re.findall(r"\w{3,}", query.lower())}

    type_weights = {
        "function": 1.5,
        "method": 1.3,
        "class": 1.2,
        "module": 1.0,
        "concept": 1.4,
        "document": 0.8,
        "file_python": 1.0,
        "file_java": 1.0,
        "file_javascript": 1.0,
        "file_typescript": 1.0,
        "file_go": 1.0,
        "file_rust": 1.0,
    }

    scored: list[tuple[str, float]] = []
    for node_id in G.nodes():
        node = G.nodes[node_id]
        score = 0.0

        label = node.get("label", "").lower()
        sig = node.get("signature", "").lower()
        doc = node.get("docstring", "").lower()
        ntype = node.get("type", "unknown")

        for kw in query_keywords:
            kw_lower = kw.lower()
            if kw_lower in label:
                score += 3.0 if kw_lower == label else 1.5
            if kw_lower in sig:
                score += 0.8
            if kw_lower in doc:
                score += 0.5

        score *= type_weights.get(ntype, 1.0)

        # Domain bonus (matching domain keywords)
        domain = node.get("domain", "")
        if domain:
            for kw in query_keywords:
                if kw in domain:
                    score += 0.5

        if score > 0:
            scored.append((node_id, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


# ── Traversal ───────────────────────────────────────────────────────────────

def bfs_traverse(
    G: nx.DiGraph,
    start_nodes: list[str],
    max_nodes: int,
) -> dict[str, dict[str, Any]]:
    """Breadth-first traversal from start nodes, collecting neighbor context."""
    visited: dict[str, dict[str, Any]] = {}
    queue: list[tuple[str, int]] = [(n, 0) for n in start_nodes]

    while queue and len(visited) < max_nodes:
        node_id, depth = queue.pop(0)
        if node_id in visited:
            continue
        visited[node_id] = {"depth": depth, "distance": depth}
        for neighbor in G.neighbors(node_id):
            if neighbor not in visited:
                queue.append((neighbor, depth + 1))
        # Also incoming edges (reverse traversal)
        for predecessor in G.predecessors(node_id):
            if predecessor not in visited:
                queue.append((predecessor, depth + 1))

    return visited


def dfs_traverse(
    G: nx.DiGraph,
    start_nodes: list[str],
    max_nodes: int,
) -> dict[str, dict[str, Any]]:
    """Depth-first traversal from start nodes."""
    visited: dict[str, dict[str, Any]] = {}

    def _dfs(node_id: str, depth: int) -> None:
        if node_id in visited or len(visited) >= max_nodes:
            return
        visited[node_id] = {"depth": depth, "distance": depth}
        for neighbor in G.neighbors(node_id):
            _dfs(neighbor, depth + 1)
        if len(visited) < max_nodes:
            for predecessor in G.predecessors(node_id):
                _dfs(predecessor, depth + 1)

    for start in start_nodes:
        _dfs(start, 0)
        if len(visited) >= max_nodes:
            break

    return visited


# ── Subgraph rendering ──────────────────────────────────────────────────────

def subgraph_to_text(
    G: nx.DiGraph,
    visited: dict[str, dict[str, Any]],
    graph_data: dict[str, Any],
    max_chars: int,
    show_node_type: bool = True,
    show_trust: bool = False,
) -> str:
    """Render visited subgraph to readable text within char budget."""
    gcfg = cfg.get_global_config()
    if max_chars <= 0:
        max_chars = gcfg.default_max_tokens * gcfg.chars_per_token
    if show_node_type:
        show_trust = gcfg.show_trust_tags

    # Build node map
    node_map = {n["id"]: n for n in graph_data["nodes"]}

    lines: list[str] = []
    current_chars = 0

    def add_line(line: str) -> bool:
        nonlocal current_chars
        needed = len(line) + 1
        if current_chars + needed > max_chars:
            return False
        lines.append(line)
        current_chars += needed
        return True

    # Sort by depth then by score
    for node_id in sorted(visited.keys(), key=lambda n: (visited[n]["depth"], -visited[n]["distance"])):
        node = node_map.get(node_id)
        if not node:
            continue

        label = node.get("label", node_id)
        ntype = node.get("type", "?")
        domain = node.get("domain", "")
        docstring = node.get("docstring", "")
        file_path = node.get("file", "")
        lineno = node.get("lineno", 0)
        depth = visited[node_id]["depth"]

        indent = "  " * depth

        if not add_line(f"{indent}[{ntype}] {label}"):
            break

        if domain and show_node_type:
            add_line(f"{indent}  domain: {domain}")
        if file_path:
            location = f"{file_path}"
            if lineno:
                location += f":{lineno}"
            add_line(f"{indent}  location: {location}")
        if docstring:
            preview = docstring[:100].replace("\n", " ")
            add_line(f"{indent}  doc: {preview}")

        # Show outgoing edges with labels
        out_edges = list(G.out_edges(node_id, data=True))
        in_edges = list(G.in_edges(node_id, data=True))

        shown_edges = 0
        for _, target, data in out_edges[:5]:
            if shown_edges >= 5:
                break
            rel_type = data.get("type", "?")
            trust = data.get("trust", "") if show_trust else ""
            trust_str = f" [{trust}]" if trust else ""
            t_label = node_map.get(target, {}).get("label", target)
            if not add_line(f"{indent}  → {rel_type} → {t_label}{trust_str}"):
                break
            shown_edges += 1

        for src, _, data in in_edges[:3]:
            if shown_edges >= 7:
                break
            rel_type = data.get("type", "?")
            trust = data.get("trust", "") if show_trust else ""
            trust_str = f" [{trust}]" if trust else ""
            s_label = node_map.get(src, {}).get("label", src)
            if not add_line(f"{indent}  ← {rel_type} ← {s_label}{trust_str}"):
                break
            shown_edges += 1

    if not lines:
        return "(No results within token budget)"

    result = "\n".join(lines)
    return result


# ── Full query pipeline ─────────────────────────────────────────────────────

def query(
    query_text: str,
    graph_file: Path | None = None,
    traversal: str | None = None,
    max_nodes: int | None = None,
    max_tokens: int | None = None,
) -> str:
    """
    Full query pipeline: score → traverse → render.

    Returns rendered subgraph as readable text.
    """
    graph_data, G = load_graph(graph_file)
    gcfg = cfg.get_global_config()

    if traversal is None:
        traversal = gcfg.default_traversal
    if max_nodes is None:
        max_nodes = gcfg.max_nodes
    if max_tokens is None:
        max_tokens = gcfg.default_max_tokens

    # Step 1: Score nodes
    scored = score_nodes(G, query_text)
    if not scored:
        return "(No matching nodes found in graph)"

    # Take top-scored nodes as starting points
    top_nodes = [nid for nid, _ in scored[:5]]

    # Step 2: Traverse
    if traversal == "dfs":
        visited = dfs_traverse(G, top_nodes, max_nodes)
    else:
        visited = bfs_traverse(G, top_nodes, max_nodes)

    # Step 3: Render
    max_chars = max_tokens * gcfg.chars_per_token
    return subgraph_to_text(
        G, visited, graph_data, max_chars,
        show_node_type=gcfg.show_node_type,
        show_trust=gcfg.show_trust_tags,
    )


# ── Utility ─────────────────────────────────────────────────────────────────

def get_node_info(node_id: str, graph_file: Path | None = None) -> dict[str, Any] | None:
    """Get full info for a specific node."""
    graph_data, G = load_graph(graph_file)
    node_map = {n["id"]: n for n in graph_data["nodes"]}
    return node_map.get(node_id)


def get_neighbors(
    node_id: str,
    graph_file: Path | None = None,
    direction: str = "out",
) -> list[dict[str, Any]]:
    """Get neighbors of a node (outgoing, incoming, or both)."""
    graph_data, G = load_graph(graph_file)
    node_map = {n["id"]: n for n in graph_data["nodes"]}

    results = []
    if direction in ("out", "both"):
        for _, target, data in G.out_edges(node_id, data=True):
            info = node_map.get(target, {}).copy()
            info["_rel_type"] = data.get("type", "?")
            info["_trust"] = data.get("trust", "")
            results.append(info)
    if direction in ("in", "both"):
        for src, _, data in G.in_edges(node_id, data=True):
            info = node_map.get(src, {}).copy()
            info["_rel_type"] = data.get("type", "?")
            info["_trust"] = data.get("trust", "")
            results.append(info)

    return results
