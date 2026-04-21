#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
ewankb build-graph — Build graph.json using graphify.

Usage:
    python -m tools.build_graph
    python -m tools.build_graph --full   # Force full rebuild (no incremental)
    python -m tools.build_graph --stats   # Show graph statistics
    python -m tools.build_graph --communities  # Detect and show communities
    python -m tools.build_graph --surprising   # Show surprising cross-domain connections
"""
from __future__ import annotations

import json
import sys
import argparse
from pathlib import Path

# Add parent dir to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.build_graph import graph_builder
from tools import config_loader as cfg


def main() -> None:
    parser = argparse.ArgumentParser(description="Build knowledge graph using graphify")
    parser.add_argument("--full", action="store_true", help="Force full rebuild (skip incremental)")
    parser.add_argument("--stats", action="store_true", help="Show graph statistics")
    parser.add_argument("--communities", action="store_true", help="Detect and show communities")
    parser.add_argument("--surprising", action="store_true", help="Show surprising cross-domain connections")
    parser.add_argument("--output", type=str, help="Output file for stats/communities (default: stdout)")
    args = parser.parse_args()

    graph_dir = cfg.get_graph_dir()

    if args.stats or args.communities or args.surprising:
        graph_file = graph_dir / "graph.json"
        if not graph_file.exists():
            print("Error: graph.json not found. Run build first.", file=sys.stderr)
            sys.exit(1)

        with open(graph_file, encoding="utf-8") as f:
            graph = json.load(f)

        output_file = Path(args.output) if args.output else None
        out_handle = open(output_file, "w", encoding="utf-8") if output_file else sys.stdout

        try:
            if args.stats:
                _print_stats(graph, out_handle)
            if args.communities:
                communities = graph_builder.detect_communities(graph)
                _print_communities(communities, graph, out_handle)
            if args.surprising:
                communities = graph_builder.detect_communities(graph)
                surprising = graph_builder.find_surprising_connections(graph, communities)
                _print_surprising(surprising, out_handle)
        finally:
            if output_file:
                out_handle.close()
        return

    # Default: build graph
    incremental = not args.full
    print(f"Building graph (incremental={incremental})...")

    graph = graph_builder.build_graph(incremental=incremental)

    meta = graph["metadata"]
    print(f"Done. graph.json written.")
    print(f"  Nodes: {meta['num_nodes']}")
    print(f"  Links: {meta['num_links']}")
    print(f"  Code files: {meta.get('code_files', '?')}")
    print(f"  Doc files: {meta.get('doc_files', '?')}")
    print(f"  Communities: {meta.get('communities', '?')}")
    print(f"  Engine: {meta.get('engine', '?')}")
    print(f"  Source hash: {meta['source_hash']}")
    print(f"  KB hash: {meta['kb_hash']}")


def _print_stats(graph: dict, out=sys.stdout) -> None:
    meta = graph.get("metadata", {})
    print(f"Graph Statistics", file=out)
    print(f"  Version: {meta.get('version', '?')}", file=out)
    print(f"  Created: {meta.get('created_at', '?')}", file=out)
    print(f"  Nodes: {meta.get('num_nodes', len(graph.get('nodes', [])))}", file=out)
    print(f"  Links: {meta.get('num_links', len(graph.get('links', [])))}", file=out)
    print(f"  Engine: {meta.get('engine', 'unknown')}", file=out)
    print(f"  Source hash: {meta.get('source_hash', '?')}", file=out)
    print(f"  KB hash: {meta.get('kb_hash', '?')}", file=out)

    # Node type distribution
    type_counts: dict[str, int] = {}
    for node in graph.get("nodes", []):
        t = node.get("type", node.get("file_type", "unknown"))
        type_counts[t] = type_counts.get(t, 0) + 1
    print(f"  Node types:", file=out)
    for t, cnt in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"    {t}: {cnt}", file=out)

    # Trust tag distribution
    trust_counts: dict[str, int] = {}
    for link in graph.get("links", []):
        t = link.get("trust", "EXTRACTED")
        trust_counts[t] = trust_counts.get(t, 0) + 1
    if trust_counts:
        print(f"  Trust tags:", file=out)
        for t, cnt in sorted(trust_counts.items(), key=lambda x: -x[1]):
            print(f"    {t}: {cnt}", file=out)

    # Edge type distribution
    edge_types: dict[str, int] = {}
    for link in graph.get("links", []):
        t = link.get("type", "unknown")
        edge_types[t] = edge_types.get(t, 0) + 1
    if edge_types:
        print(f"  Edge types:", file=out)
        for t, cnt in sorted(edge_types.items(), key=lambda x: -x[1]):
            print(f"    {t}: {cnt}", file=out)


def _print_communities(communities: list, graph: dict, out=sys.stdout) -> None:
    print(f"\nCommunities ({len(communities)} found):", file=out)

    # Build id→node map
    node_map = {n["id"]: n for n in graph.get("nodes", [])}

    for comm in communities[:30]:  # Show top 30
        print(f"\n  Community {comm['id']} ({comm['size']} nodes):", file=out)
        sample_nodes = comm["nodes"][:5]
        for nid in sample_nodes:
            node = node_map.get(nid, {})
            label = node.get("label", nid)
            ntype = node.get("type", node.get("file_type", "?"))
            print(f"    [{ntype}] {label}", file=out)
        if comm["size"] > 5:
            print(f"    ... and {comm['size'] - 5} more", file=out)


def _print_surprising(surprising: list, out=sys.stdout) -> None:
    print(f"\nSurprising Cross-Domain Connections (top {len(surprising)}):", file=out)
    for i, item in enumerate(surprising, 1):
        src = item["source"]
        tgt = item["target"]
        link_type = item["type"]
        trust = item["trust"]
        score = item["surprise_score"]
        src_c = item.get("src_community", "?")
        tgt_c = item.get("tgt_community", "?")
        print(f"\n  {i}. Score={score} | {src} → {tgt}", file=out)
        print(f"     Type: {link_type} | Trust: {trust}", file=out)
        if src_c != tgt_c:
            print(f"     Cross-community: {src_c} → {tgt_c}", file=out)


if __name__ == "__main__":
    main()
