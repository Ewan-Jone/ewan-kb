#!/usr/bin/env python
"""
ewankb — Build and query structured knowledge bases.

Usage:
    ewankb init <name>          Initialize a new knowledge base
    ewankb knowledgebase        Build knowledgeBase/ (discover + extract + enrich + overview + processes)
    ewankb analyze-code <path>  Analyze code files (AST pass)
    ewankb build-graph          Build graph.json from source + domains
    ewankb build                knowledgebase + build-graph (full pipeline)
    ewankb build --kb           Only build domains + knowledgeBase
    ewankb build --graph        Only build graph
    ewankb query <text>         Query the knowledge graph
    ewankb query-graph <text>   Query the knowledge graph (alias)
    ewankb query-kb <text>      Query knowledge base directly (domains + knowledgeBase + source)
    ewankb graph-stats          Show graph statistics
    ewankb communities          Show detected communities
    ewankb surprising           Show surprising cross-domain connections
    ewankb diff                 Detect source changes and show affected domains
    ewankb update               Incremental update: rebuild affected domains only
    ewankb rebuild              Delete all generated artifacts for a clean rebuild
    ewankb config --edit        Edit project_config.json
    ewankb config --edit-llm    Edit llm_config.json (API credentials)
"""
from __future__ import annotations

import sys
import argparse
from argparse import Namespace

if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

from .cli._helpers import resolve_kb_dir as _resolve_kb_dir
from .cli._helpers import graph_file as _graph_file
from .cli._helpers import EWANKB_ROOT

from .cli.init_cmd import run as _run_init
from .cli.discover_cmd import run as _run_discover
from .cli.knowledgebase_cmd import run as _run_knowledgebase
from .cli.analyze_cmd import run as _run_analyze
from .cli.build_graph_cmd import run as _run_build_graph
from .cli.query_cmd import run as _run_query
from .cli.query_cmd import run_kb as _run_query_kb
from .cli.preflight_cmd import run as _run_preflight
from .cli.diff_cmd import run as _run_diff
from .cli.update_cmd import run as _run_update
from .cli.rebuild_cmd import run as _run_rebuild
from .cli.install_cmd import run as _run_install
from .cli.config_cmd import run as _run_config
from .cli.stats_cmd import run_stats as _run_stats
from .cli.stats_cmd import run_communities as _run_communities
from .cli.stats_cmd import run_surprising as _run_surprising


def cmd_init(args): return _run_init(args)
def cmd_discover(): return _run_discover(Namespace())
def cmd_knowledgebase(skip_discover=False): return _run_knowledgebase(Namespace(skip_discover=skip_discover))
def cmd_analyze(args): return _run_analyze(args)
def cmd_build_graph(): return _run_build_graph(Namespace())
def cmd_query(args): return _run_query(args)
def cmd_query_kb(args): return _run_query_kb(args)
def cmd_preflight(args): return _run_preflight(args)
def cmd_diff(): return _run_diff(Namespace())
def cmd_update(): return _run_update(Namespace())
def cmd_rebuild(): return _run_rebuild(Namespace())
def cmd_install(): return _run_install(Namespace())
def cmd_config(args): return _run_config(args)
def cmd_stats(): return _run_stats(Namespace())
def cmd_communities(): return _run_communities(Namespace())
def cmd_surprising(): return _run_surprising(Namespace())


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="ewankb",
        description="Build and query structured knowledge bases.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    init_p = sub.add_parser("init", help="Initialize a new knowledge base")
    init_p.add_argument("name", type=str, help="Knowledge base name (directory)")

    sub.add_parser("discover", help="Re-run domain discovery (AI translation)")
    kb_p = sub.add_parser("knowledgebase", help="Build domains/ + knowledgeBase/ (7-step pipeline)")
    kb_p.add_argument("--skip-discover", action="store_true", help="Skip Step 1 (domain discovery), start from Step 2")

    analyze_p = sub.add_parser("analyze-code", help="Analyze code with AST extraction")
    analyze_p.add_argument("path", type=str, nargs="?", default=".", help="Path to analyze")

    sub.add_parser("build-graph", help="Build graph.json")

    build_p = sub.add_parser("build", help="knowledgebase + build-graph")
    build_p.add_argument("--kb", action="store_true", help="Only build domains + knowledgeBase")
    build_p.add_argument("--graph", action="store_true", help="Only build graph")
    build_p.add_argument("--skip-discover", action="store_true", help="Skip domain discovery step")

    query_p = sub.add_parser("query", help="Query the knowledge graph")
    query_p.add_argument("text", type=str, help="Query text")
    query_p.add_argument("--dir", type=str, help="Knowledge base directory (default: current dir or EWANKB_DIR)")
    query_p.add_argument("--traversal", choices=["bfs", "dfs"])
    query_p.add_argument("--depth", type=int, help="Max traversal depth")
    query_p.add_argument("--max-tokens", type=int, help="Max output tokens")
    query_p.add_argument("--json", action="store_true", help="Output structured JSON")
    query_p.add_argument("--limit", type=int, default=None, help="Max nodes to visit (overrides config default)")
    query_p.add_argument("--verbose", action="store_true", help="Show debug info")

    qg_p = sub.add_parser("query-graph", help="Query via knowledge graph (alias for query)")
    qg_p.add_argument("text", type=str, help="Query text")
    qg_p.add_argument("--dir", type=str, help="Knowledge base directory (default: current dir or EWANKB_DIR)")
    qg_p.add_argument("--traversal", choices=["bfs", "dfs"])
    qg_p.add_argument("--depth", type=int, help="Max traversal depth")
    qg_p.add_argument("--max-tokens", type=int, help="Max output tokens")
    qg_p.add_argument("--json", action="store_true", help="Output structured JSON")
    qg_p.add_argument("--limit", type=int, default=None, help="Max nodes to visit (overrides config default)")
    qg_p.add_argument("--verbose", action="store_true", help="Show debug info")

    qkb_p = sub.add_parser("query-kb", help="Query knowledge base directly (domains + knowledgeBase + source)")
    qkb_p.add_argument("text", type=str, help="Query text")
    qkb_p.add_argument("--dir", type=str, help="Knowledge base directory (default: current dir or EWANKB_DIR)")
    qkb_p.add_argument("--domain", type=str, help="Filter by domain")
    qkb_p.add_argument("--max-results", type=int, default=8, help="Max documents to return")

    sub.add_parser("graph-stats", help="Show graph statistics")
    sub.add_parser("stats", help="Show graph statistics")
    sub.add_parser("communities", help="Show detected communities")
    sub.add_parser("surprising", help="Show surprising cross-domain connections")

    pf_p = sub.add_parser("preflight", help="Check environment readiness (JSON output)")
    pf_p.add_argument("--fix", action="store_true", help="Auto-create missing dirs and config")
    pf_p.add_argument("--dir", type=str, help="Target knowledge base directory (default: .)")
    pf_p.add_argument("--query", action="store_true", help="Skip LLM-related checks (no_llm_config, no_api_key)")

    sub.add_parser("diff", help="Detect source changes and show affected domains")
    sub.add_parser("update", help="Incremental update: detect changes, rebuild affected domains only")
    sub.add_parser("rebuild", help="Delete all generated artifacts (domains/, knowledgeBase/, graph/, source/.cache/) for a clean rebuild")
    sub.add_parser("install", help="Install ewankb skills to Claude Code")

    cfg_p = sub.add_parser("config", help="Manage project configuration")
    cfg_p.add_argument("--edit", action="store_true", help="Edit project_config.json")
    cfg_p.add_argument("--edit-llm", action="store_true", help="Edit llm_config.json (API credentials)")
    cfg_p.add_argument("--show", action="store_true", help="Show current config")

    args = parser.parse_args()

    try:
        _dispatch(args)
    except Exception as e:
        import traceback
        print(f"Error: {e}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)


def _dispatch(args):
    cmd = args.command

    if cmd == "init":
        _run_init(args)
    elif cmd == "discover":
        _run_discover(args)
    elif cmd == "knowledgebase":
        _run_knowledgebase(args)
    elif cmd == "analyze-code":
        _run_analyze(args)
    elif cmd == "build-graph":
        _run_build_graph(args)
    elif cmd == "build":
        if args.kb:
            _run_knowledgebase(args)
        elif args.graph:
            _run_build_graph(args)
        else:
            _run_knowledgebase(args)
            _run_build_graph(args)
    elif cmd in ("query", "query-graph"):
        _run_query(args)
    elif cmd == "query-kb":
        _run_query_kb(args)
    elif cmd in ("stats", "graph-stats"):
        _run_stats(args)
    elif cmd == "communities":
        _run_communities(args)
    elif cmd == "surprising":
        _run_surprising(args)
    elif cmd == "preflight":
        _run_preflight(args)
    elif cmd == "diff":
        _run_diff(args)
    elif cmd == "update":
        _run_update(args)
    elif cmd == "rebuild":
        _run_rebuild(args)
    elif cmd == "install":
        _run_install(args)
    elif cmd == "config":
        _run_config(args)


if __name__ == "__main__":
    main()
