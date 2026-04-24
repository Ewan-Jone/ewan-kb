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
from tools.text_utils import tokenize


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
    query_keywords = tokenize(query)
    if not query_keywords:
        query_keywords = list({w.lower() for w in re.findall(r"\w{3,}", query.lower())})

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
        sig = (node.get("signature") or node.get("sig") or "").lower()
        doc = (node.get("docstring") or node.get("doc") or "").lower()
        # 兼容 graphify 字段名：file_type -> type
        ntype = node.get("type") or node.get("file_type", "unknown")
        # 兼容 source_file 和 source_location
        source_file = (node.get("source_file") or node.get("file") or "").lower()

        for kw in query_keywords:
            kw_lower = kw.lower()
            if kw_lower in label:
                score += 3.0 if kw_lower == label else 1.5
            if kw_lower in sig:
                score += 0.8
            if kw_lower in doc:
                score += 0.5
            # source_file 匹配（捕获路径中的模块名）
            if kw_lower in source_file:
                score += 0.3

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


def query_graph_json(
    query_text: str,
    graph_file: Path | None = None,
    traversal: str | None = None,
    max_nodes: int | None = None,
    verbose: bool = False,
) -> dict[str, Any]:
    """
    Full query pipeline returning structured JSON.

    Returns a dict with matched nodes, traversal results, and metadata.
    """
    import time

    graph_data, G = load_graph(graph_file)
    gcfg = cfg.get_global_config()

    if traversal is None:
        traversal = gcfg.default_traversal or "bfs"
    if max_nodes is None:
        max_nodes = gcfg.max_nodes

    # Step 1: Score nodes with timing
    start_time = time.time()
    scored = score_nodes(G, query_text)
    score_time = time.time() - start_time

    # 获取分词后的关键词
    query_keywords = tokenize(query_text)
    used_jieba = bool(query_keywords)
    if not query_keywords:
        query_keywords = list({w.lower() for w in re.findall(r"\w{3,}", query_text.lower())})

    result: dict[str, Any] = {
        "query_analysis": {
            "original_query": query_text,
            "extracted_keywords": list(query_keywords),
            "tokenization_method": "jieba" if used_jieba else "regex",
            "total_nodes_scored": len(G.nodes()),
            "scoring_time_ms": round(score_time * 1000, 1),
        },
        "matched_start_nodes": [],
        "traversal": {
            "method": traversal,
            "max_nodes": max_nodes,
            "visited_nodes": 0,
            "visited_edges": 0,
        },
        "nodes": [],
        "edges": [],
        "total_nodes": len(G.nodes()),
        "total_edges": len(G.edges()),
        "message": "",
    }

    if verbose:
        result["query_analysis"]["top_10_scores"] = [
            {"id": nid, "score": round(score, 2)} for nid, score in scored[:10]
        ]

    if not scored:
        result["message"] = "No matching nodes found in graph"
        return result

    # 构建 matched_start_nodes
    for nid, score in scored[:10]:
        node = G.nodes[nid]
        result["matched_start_nodes"].append({
            "id": nid,
            "label": node.get("label", nid),
            "type": node.get("type") or node.get("file_type", "unknown"),
            "score": round(score, 2),
            "source_file": node.get("source_file") or node.get("file", ""),
        })

    # Step 2: Traverse
    start_time = time.time()
    top_nodes = [nid for nid, _ in scored[:5]]

    if traversal == "dfs":
        visited = dfs_traverse(G, top_nodes, max_nodes)
    else:
        visited = bfs_traverse(G, top_nodes, max_nodes)

    traverse_time = time.time() - start_time

    # 构建节点和边的数据
    node_map = {n["id"]: n for n in graph_data["nodes"]}
    for node_id, visit_info in visited.items():
        node = node_map.get(node_id)
        if not node:
            continue
        result["nodes"].append({
            "id": node_id,
            "label": node.get("label", node_id),
            "type": node.get("type") or node.get("file_type", "unknown"),
            "source_file": node.get("source_file") or node.get("file", ""),
            "source_location": node.get("source_location", ""),
            "depth": visit_info.get("depth", 0),
            "distance": visit_info.get("distance", 0),
            "signature": node.get("signature", ""),
            "docstring": (node.get("docstring") or node.get("doc") or "")[:200],
        })

    # 收集边
    for node_id in visited.keys():
        for _, target, data in G.out_edges(node_id, data=True):
            if target in visited:
                result["edges"].append({
                    "source": node_id,
                    "target": target,
                    "relation": data.get("type", "relates"),
                    "confidence": data.get("confidence", ""),
                    "trust": data.get("trust", ""),
                })

    result["traversal"]["visited_nodes"] = len(result["nodes"])
    result["traversal"]["visited_edges"] = len(result["edges"])
    result["traversal"]["traverse_time_ms"] = round(traverse_time * 1000, 1)
    result["message"] = f"Found {len(result['matched_start_nodes'])} matched start nodes, visited {len(result['nodes'])} nodes"

    return result


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
