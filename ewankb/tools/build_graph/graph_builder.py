#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Build graph.json using graphify library.

Inputs:
  - source/repos/ — source code files
  - domains/ — domain documents (README.md, PROCESSES.md)

Output:
  - graph/graph.json
  - graph/code_analysis.json (raw extraction results)

Replaces the old custom AST + semantic extraction pipeline with graphify's
tree-sitter based extraction + NetworkX graph construction + Leiden clustering.
"""
from __future__ import annotations

import json
import hashlib
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

from .. import config_loader as cfg


def build_graph(
    incremental: bool = True,
    source_dir: Path | None = None,
    domains_dir: Path | None = None,
    graph_dir: Path | None = None,
) -> dict[str, Any]:
    """
    Build graph.json from source code + domain documents using graphify.

    AST extraction handles code files (via graphify tree-sitter).
    Semantic extraction of domain documents is done by the skill layer
    and written to graph/.semantic_extraction.json — auto-detected here.

    Returns the graph dict and writes graph.json to graph_dir.
    """
    from graphify.extract import extract, collect_files
    from graphify.build import build_from_json
    from graphify.cluster import cluster

    if source_dir is None:
        source_dir = cfg.get_source_dir()
    if domains_dir is None:
        domains_dir = cfg.get_domains_dir()
    if graph_dir is None:
        graph_dir = cfg.get_graph_dir()

    graph_dir.mkdir(parents=True, exist_ok=True)

    # ── Redirect graphify cache to graph/.cache/ast/ ────────────────────
    # graphify's extract() creates graphify-out/cache/ under the common
    # root of input files. This would pollute source/ which must be read-only.
    import graphify.cache as _gfcache
    _ast_cache = graph_dir / ".cache" / "ast"
    _ast_cache.mkdir(parents=True, exist_ok=True)
    _gfcache.cache_dir = lambda root=None: _ast_cache

    # ── Step 1: AST extraction (code files only) ────────────────────────

    repos_dir = source_dir / "repos"
    code_files = collect_files(repos_dir) if repos_dir.exists() else []
    print(f"  Code files: {len(code_files)}")

    print("  Running AST extraction via graphify...")
    code_extraction = extract(code_files) if code_files else {"nodes": [], "edges": []}
    print(f"  AST extraction: {len(code_extraction.get('nodes', []))} nodes, "
          f"{len(code_extraction.get('edges', []))} edges")

    # ── Step 2: Load semantic extraction (written by skill layer) ───────

    semantic_file = graph_dir / ".semantic_extraction.json"
    sem_nodes: list[dict] = []
    sem_edges: list[dict] = []
    if semantic_file.exists():
        with open(semantic_file, encoding="utf-8") as f:
            semantic = json.load(f)
        sem_nodes = semantic.get("nodes", [])
        sem_edges = semantic.get("edges", [])
        print(f"  Semantic extraction: {len(sem_nodes)} nodes, {len(sem_edges)} edges")
    else:
        print("  Semantic extraction: not found (skill layer did not produce graph/.semantic_extraction.json)")

    # ── Step 3: Merge AST + semantic ────────────────────────────────────

    print("  Building graph...")
    seen_ids = {n["id"] for n in code_extraction.get("nodes", [])}
    merged_nodes = list(code_extraction.get("nodes", []))
    for n in sem_nodes:
        if n["id"] not in seen_ids:
            merged_nodes.append(n)
            seen_ids.add(n["id"])

    # Build fuzzy lookup for AST node IDs so semantic edges can reference
    # code nodes by class name (e.g. "path/to/File::ClassName" → "classname")
    ast_id_lookup: dict[str, str] = {}  # lowercase_name → actual_id
    for nid in seen_ids:
        ast_id_lookup[nid.lower()] = nid
    # Also index by label if present (some AST nodes have a human-readable label)
    for n in code_extraction.get("nodes", []):
        label = n.get("label", "")
        if label:
            ast_id_lookup[label.lower()] = n["id"]

    def _resolve_id(raw_id: str) -> str:
        """Resolve a semantic edge endpoint to an existing node ID.

        Tries exact match first, then extracts the class/method name
        portion from formats like 'path/to/File::ClassName' or
        'path/to/File::ClassName_methodName' and does case-insensitive
        lookup against AST node IDs.
        """
        if raw_id in seen_ids:
            return raw_id
        # Try case-insensitive exact match
        lower = raw_id.lower()
        if lower in ast_id_lookup:
            return ast_id_lookup[lower]
        # Extract class name after last "::"
        if "::" in raw_id:
            class_part = raw_id.rsplit("::", 1)[1]  # "ClassName" or "ClassName_method"
            cl = class_part.lower()
            if cl in ast_id_lookup:
                return ast_id_lookup[cl]
        # Extract last path segment (filename without extension) as fallback
        name = raw_id.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        name = name.rsplit(".", 1)[0]  # strip .java etc
        nl = name.lower()
        if nl in ast_id_lookup:
            return ast_id_lookup[nl]
        return raw_id  # unchanged — will be filtered by build_from_json

    # Resolve semantic edge endpoints
    resolved_count = 0
    unresolved_targets: list[str] = []
    resolved_edges = []
    for e in sem_edges:
        orig_src, orig_tgt = e.get("source", ""), e.get("target", "")
        new_src = _resolve_id(orig_src)
        new_tgt = _resolve_id(orig_tgt)
        if new_src != orig_src or new_tgt != orig_tgt:
            resolved_count += 1
        resolved_e = {**e, "source": new_src, "target": new_tgt}
        resolved_edges.append(resolved_e)
        # Track unresolvable targets for warning
        if new_tgt not in seen_ids:
            unresolved_targets.append(orig_tgt)

    if resolved_count > 0:
        print(f"  Semantic edge ID resolution: {resolved_count} edges remapped to AST node IDs")
    if unresolved_targets:
        print(f"  WARNING: {len(unresolved_targets)} semantic edges have unresolvable targets "
              f"(will be dropped by graph builder)")
        for t in unresolved_targets[:5]:
            print(f"    - {t}")
        if len(unresolved_targets) > 5:
            print(f"    ... and {len(unresolved_targets) - 5} more")

    merged_edges = code_extraction.get("edges", []) + resolved_edges
    combined = {"nodes": merged_nodes, "edges": merged_edges}

    print(f"  Merged input: {len(merged_nodes)} nodes, {len(merged_edges)} edges")
    G = build_from_json(combined, directed=True)
    dedup_nodes = len(merged_nodes) - G.number_of_nodes()
    dropped_edges = len(merged_edges) - G.number_of_edges()
    print(f"  Graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
    if dedup_nodes > 0:
        print(f"    Deduplicated: {dedup_nodes} nodes (same id from different files)")
    if dropped_edges > 0:
        print(f"    Filtered: {dropped_edges} edges (target/source node not in graph, e.g. external imports)")

    # ── Step 4: Community detection ─────────────────────────────────────

    print("  Running community detection...")
    communities = cluster(G)
    print(f"  Communities: {len(communities)}")

    # ── Step 5: Export to graph.json ────────────────────────────────────

    # Convert NetworkX graph to ewankb graph.json format
    nodes_list = []
    for nid, attrs in G.nodes(data=True):
        node = {"id": nid, **attrs}
        # Assign community
        for cid, members in communities.items():
            if nid in members:
                node["community"] = cid
                break
        nodes_list.append(node)

    links_list = []
    for src, tgt, attrs in G.edges(data=True):
        link = {
            "source": attrs.get("_src", src),
            "target": attrs.get("_tgt", tgt),
            **{k: v for k, v in attrs.items() if k not in ("_src", "_tgt")},
        }
        if "trust" not in link:
            link["trust"] = "EXTRACTED"
        links_list.append(link)

    # Compute hashes
    source_hash = _dir_hash(source_dir)
    kb_hash = _dir_hash(domains_dir)

    graph = {
        "nodes": nodes_list,
        "links": links_list,
        "metadata": {
            "version": "0.2.0",
            "source_hash": source_hash[:12],
            "kb_hash": kb_hash[:12],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "num_nodes": len(nodes_list),
            "num_links": len(links_list),
            "incremental": incremental,
            "code_files": len(code_files),
            "semantic_nodes": len(sem_nodes),
            "semantic_edges": len(sem_edges),
            "communities": len(communities),
            "engine": "graphify",
        },
        "communities": {
            str(cid): members for cid, members in communities.items()
        },
    }

    # Write graph.json
    graph_file = graph_dir / "graph.json"
    with open(graph_file, "w", encoding="utf-8") as f:
        json.dump(graph, f, indent=2, ensure_ascii=False)

    # Write code_analysis.json (raw extraction for inspection)
    analysis_file = graph_dir / "code_analysis.json"
    analysis = {
        "code_extraction": {
            "nodes": len(code_extraction.get("nodes", [])),
            "edges": len(code_extraction.get("edges", [])),
        },
        "semantic_extraction": {
            "nodes": len(sem_nodes),
            "edges": len(sem_edges),
            "source": str(semantic_file) if semantic_file.exists() else None,
        },
        "merged": {
            "nodes_before_build": len(merged_nodes),
            "edges_before_build": len(merged_edges),
            "nodes_after_build": G.number_of_nodes(),
            "edges_after_build": G.number_of_edges(),
        },
    }
    with open(analysis_file, "w", encoding="utf-8") as f:
        json.dump(analysis, f, indent=2, ensure_ascii=False)

    # Generate domain suggestions
    try:
        _generate_domain_suggestions(graph, communities, graph_dir)
    except Exception as e:
        print(f"  (domain suggestions skipped: {e})")

    return graph


def detect_communities(
    graph: dict[str, Any] | None = None,
    graph_file: Path | None = None,
) -> list[dict[str, Any]]:
    """
    Detect communities from graph.json.
    Returns list of community dicts with id, size, nodes.
    """
    if graph is None:
        if graph_file is None:
            graph_file = cfg.get_graph_dir() / "graph.json"
        with open(graph_file, encoding="utf-8") as f:
            graph = json.load(f)

    # Use pre-computed communities if available
    communities_data = graph.get("communities", {})
    if communities_data:
        result = []
        for cid, members in sorted(communities_data.items(), key=lambda x: -len(x[1])):
            result.append({
                "id": int(cid) if cid.isdigit() else cid,
                "size": len(members),
                "nodes": members,
            })
        return result

    # Fall back to re-running community detection via graphify
    from graphify import build_from_json, cluster

    # Remap links→edges for graphify compat
    extraction = {
        "nodes": graph.get("nodes", []),
        "edges": graph.get("links", []),
    }
    G = build_from_json(extraction, directed=True)
    communities = cluster(G)

    result = []
    for cid, members in sorted(communities.items(), key=lambda x: -len(x[1])):
        result.append({
            "id": cid,
            "size": len(members),
            "nodes": members,
        })
    return result


def find_surprising_connections(
    graph: dict[str, Any] | None = None,
    communities: list[dict[str, Any]] | None = None,
    top_n: int = 20,
) -> list[dict[str, Any]]:
    """
    Find surprising cross-community connections (edges between different communities).
    """
    if graph is None:
        graph_file = cfg.get_graph_dir() / "graph.json"
        with open(graph_file, encoding="utf-8") as f:
            graph = json.load(f)

    if communities is None:
        communities = detect_communities(graph)

    # Build node → community mapping
    node_community: dict[str, Any] = {}
    for comm in communities:
        for nid in comm["nodes"]:
            node_community[nid] = comm["id"]

    # Find cross-community edges
    node_map = {n["id"]: n for n in graph["nodes"]}
    surprising = []
    for link in graph["links"]:
        src, tgt = link["source"], link["target"]
        src_c = node_community.get(src)
        tgt_c = node_community.get(tgt)
        if src_c is not None and tgt_c is not None and src_c != tgt_c:
            src_node = node_map.get(src, {})
            tgt_node = node_map.get(tgt, {})
            # Surprise score: inverse of community size (smaller communities = more surprising)
            src_size = next((c["size"] for c in communities if c["id"] == src_c), 1)
            tgt_size = next((c["size"] for c in communities if c["id"] == tgt_c), 1)
            score = round(1.0 / (min(src_size, tgt_size) + 1), 3)
            surprising.append({
                "source": src_node.get("label", src),
                "target": tgt_node.get("label", tgt),
                "type": link.get("type", "unknown"),
                "trust": link.get("trust", "EXTRACTED"),
                "surprise_score": score,
                "src_community": src_c,
                "tgt_community": tgt_c,
            })

    surprising.sort(key=lambda x: -x["surprise_score"])
    return surprising[:top_n]


def _dir_hash(d: Path) -> str:
    """Compute a combined hash of all files in a directory."""
    if not d.exists():
        return "dir_not_found"
    h = hashlib.sha256()
    for f in sorted(d.rglob("*")):
        if f.is_file():
            try:
                h.update(f.read_bytes())
            except OSError:
                pass
    return h.hexdigest()


def _generate_domain_suggestions(graph: dict, communities: dict, graph_dir: Path) -> None:
    """Compare community structure with domain assignments, output suggestions."""
    # Build community → domains mapping
    node_map = {n["id"]: n for n in graph["nodes"]}
    suggestions = []

    for cid, members in communities.items():
        domains_in_comm = set()
        for nid in members:
            node = node_map.get(nid, {})
            domain = node.get("domain", "")
            if domain:
                domains_in_comm.add(domain)

        if len(domains_in_comm) > 1:
            suggestions.append({
                "type": "cross_domain_community",
                "community": cid,
                "domains": sorted(domains_in_comm),
                "size": len(members),
                "reason": f"Community {cid} ({len(members)} nodes) spans {len(domains_in_comm)} domains: {', '.join(sorted(domains_in_comm))}",
            })

    suggestions.sort(key=lambda x: -x["size"])
    out = graph_dir / "domain_suggestions.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"suggestions": suggestions}, f, indent=2, ensure_ascii=False)
