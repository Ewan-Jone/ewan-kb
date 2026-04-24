#!/usr/bin/env python
# -*- coding: utf-8 -*-
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
    ewankb config --edit        Edit project_config.json
    ewankb config --edit-llm    Edit llm_config.json (API credentials)
"""
from __future__ import annotations

import os
import sys
import json
import shutil
import argparse
import subprocess
from pathlib import Path

# Fix Windows Chinese output encoding
if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


EWANKB_ROOT = Path(__file__).resolve().parent.parent


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
    query_p.add_argument("--traversal", choices=["bfs", "dfs"])
    query_p.add_argument("--depth", type=int, help="Max traversal depth")
    query_p.add_argument("--max-tokens", type=int, help="Max output tokens")
    query_p.add_argument("--json", action="store_true", help="Output structured JSON")
    query_p.add_argument("--limit", type=int, default=None, help="Max nodes to visit (overrides config default)")
    query_p.add_argument("--verbose", action="store_true", help="Show debug info")

    qg_p = sub.add_parser("query-graph", help="Query via knowledge graph (alias for query)")
    qg_p.add_argument("text", type=str, help="Query text")
    qg_p.add_argument("--traversal", choices=["bfs", "dfs"])
    qg_p.add_argument("--depth", type=int, help="Max traversal depth")
    qg_p.add_argument("--max-tokens", type=int, help="Max output tokens")
    qg_p.add_argument("--json", action="store_true", help="Output structured JSON")
    qg_p.add_argument("--limit", type=int, default=None, help="Max nodes to visit (overrides config default)")
    qg_p.add_argument("--verbose", action="store_true", help="Show debug info")

    qkb_p = sub.add_parser("query-kb", help="Query knowledge base directly (domains + knowledgeBase + source)")
    qkb_p.add_argument("text", type=str, help="Query text")
    qkb_p.add_argument("--domain", type=str, help="Filter by domain")
    qkb_p.add_argument("--max-results", type=int, default=8, help="Max documents to return")

    sub.add_parser("graph-stats", help="Show graph statistics")
    sub.add_parser("stats", help="Show graph statistics")
    sub.add_parser("communities", help="Show detected communities")
    sub.add_parser("surprising", help="Show surprising cross-domain connections")

    pf_p = sub.add_parser("preflight", help="Check environment readiness (JSON output)")
    pf_p.add_argument("--fix", action="store_true", help="Auto-create missing dirs and config")
    pf_p.add_argument("--dir", type=str, help="Target knowledge base directory (default: .)")

    sub.add_parser("diff", help="Detect source changes and show affected domains")
    sub.add_parser("rebuild", help="Delete all generated artifacts (domains/, knowledgeBase/, graph/, source/.cache/) for a clean rebuild")
    sub.add_parser("install", help="Install ewankb skills to Claude Code")

    cfg_p = sub.add_parser("config", help="Manage project configuration")
    cfg_p.add_argument("--edit", action="store_true", help="Edit project_config.json")
    cfg_p.add_argument("--edit-llm", action="store_true", help="Edit llm_config.json (API credentials)")
    cfg_p.add_argument("--show", action="store_true", help="Show current config")

    args = parser.parse_args()

    try:
        if args.command == "init":
            cmd_init(args)
        elif args.command == "discover":
            cmd_discover()
        elif args.command == "knowledgebase":
            cmd_knowledgebase(skip_discover=getattr(args, 'skip_discover', False))
        elif args.command == "analyze-code":
            cmd_analyze(args)
        elif args.command == "build-graph":
            cmd_build_graph()
        elif args.command == "build":
            if args.kb:
                cmd_knowledgebase(skip_discover=getattr(args, 'skip_discover', False))
            elif args.graph:
                cmd_build_graph()
            else:
                cmd_knowledgebase(skip_discover=getattr(args, 'skip_discover', False))
                cmd_build_graph()
        elif args.command in ("query", "query-graph"):
            cmd_query(args)
        elif args.command == "query-kb":
            cmd_query_kb(args)
        elif args.command in ("stats", "graph-stats"):
            cmd_stats()
        elif args.command == "communities":
            cmd_communities()
        elif args.command == "surprising":
            cmd_surprising()
        elif args.command == "preflight":
            cmd_preflight(args)
        elif args.command == "diff":
            cmd_diff()
        elif args.command == "rebuild":
            cmd_rebuild()
        elif args.command == "install":
            cmd_install()
        elif args.command == "config":
            cmd_config(args)
        else:
            parser.print_help()
    except Exception as e:
        import traceback
        print(f"Error: {e}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)


# ── Commands ────────────────────────────────────────────────────────────────

def cmd_init(args: argparse.Namespace) -> None:
    kb_dir = Path(args.name).resolve()
    if kb_dir.exists():
        print(f"Error: directory '{kb_dir}' already exists.", file=sys.stderr)
        sys.exit(1)

    print(f"Initializing knowledge base at {kb_dir}...")

    # Copy knowledgeBase template (templates/knowledgeBase/knowledgeBase/ → <kb>/knowledgeBase/)
    template_dir = EWANKB_ROOT / "templates" / "knowledgeBase" / "knowledgeBase"
    shutil.copytree(template_dir, kb_dir / "knowledgeBase")

    # Create source/, domains/, and graph/ directories
    (kb_dir / "source").mkdir()
    (kb_dir / "source" / "docs").mkdir()
    (kb_dir / "source" / "repos").mkdir()
    (kb_dir / "domains").mkdir()
    (kb_dir / "domains" / "_meta").mkdir()
    (kb_dir / "graph").mkdir()
    (kb_dir / "graph" / ".cache").mkdir()

    # Create .gitignore for the knowledge base
    gitignore = kb_dir / ".gitignore"
    gitignore.write_text(
        "# Build state (rebuilt automatically)\n"
        "graph/.cache/\n"
        "knowledgeBase/_state/\n\n"
        "# Environment and config (contains API keys)\n"
        ".env\n"
        "llm_config.json\n",
        encoding="utf-8",
    )

    # Build project config using shared helper
    sys.path.insert(0, str(EWANKB_ROOT))
    from tools.config_loader import create_project_config
    create_project_config(kb_dir, args.name)
    print(f"  Created project_config.json + llm_config.json")

    print(f"\nCreated {kb_dir}/")
    print(f"Next steps:")
    print(f"  1. cd {kb_dir}")
    print(f"  2. Edit llm_config.json — fill in your API key (see examples/llm_config.example.json)")
    print(f"  3. Place backend Java code in source/repos/")
    print(f"  4. Place .md documents in source/docs/ (optional)")
    print(f"  5. ewankb build")
    print(f"  6. ewankb query 'your question'")
    print(f"")
    print(f"Directory structure:")
    print(f"  source/         Raw materials (code + docs)")
    print(f"  domains/        Auto-discovered business domains")
    print(f"  knowledgeBase/  AI-refined documents by type")
    print(f"  graph/          Knowledge graph")


def cmd_diff() -> None:
    """Detect source changes and show affected domains."""
    sys.path.insert(0, str(EWANKB_ROOT))
    kb_dir = _resolve_kb_dir()
    os.chdir(kb_dir)

    from tools.incremental import diff
    result = diff()

    if not result["has_changes"]:
        print("源数据无变化。")
        return

    changes = result["changes"]
    for cat in ("repos", "docs"):
        c = changes[cat]
        if any(c.values()):
            print(f"\n{cat}:")
            if c["added"]:
                print(f"  新增: {len(c['added'])} 个文件")
                for f in c["added"][:5]:
                    print(f"    + {f}")
                if len(c["added"]) > 5:
                    print(f"    ... 共 {len(c['added'])} 个")
            if c["modified"]:
                print(f"  修改: {len(c['modified'])} 个文件")
                for f in c["modified"][:5]:
                    print(f"    ~ {f}")
                if len(c["modified"]) > 5:
                    print(f"    ... 共 {len(c['modified'])} 个")
            if c["deleted"]:
                print(f"  删除: {len(c['deleted'])} 个文件")
                for f in c["deleted"][:5]:
                    print(f"    - {f}")
                if len(c["deleted"]) > 5:
                    print(f"    ... 共 {len(c['deleted'])} 个")

    domains = result["affected_domains"]
    if domains:
        print(f"\n受影响的域 ({len(domains)}):")
        for d in domains:
            print(f"  - {d}")
    else:
        print("\n未能确定受影响的域（新增文档无映射记录），建议全量构建。")

    # Output JSON for programmatic use
    print(f"\n[JSON] {json.dumps(result, ensure_ascii=False)}")


def cmd_rebuild() -> None:
    """Delete all generated artifacts for a clean rebuild."""
    import shutil
    kb_dir = _resolve_kb_dir()

    targets = [
        kb_dir / "domains",
        kb_dir / "knowledgeBase",
        kb_dir / "graph",
        kb_dir / "source" / ".cache",
    ]

    removed = []
    for t in targets:
        if t.exists():
            shutil.rmtree(t)
            removed.append(str(t.relative_to(kb_dir)))

    if removed:
        print(f"已清理: {', '.join(removed)}")
    else:
        print("无需清理（目录均不存在）。")
    print("可以重新运行 ewankb build 进行全量构建。")


def cmd_discover() -> None:
    """Re-run domain discovery (AI translation)."""
    sys.path.insert(0, str(EWANKB_ROOT))
    kb_dir = _resolve_kb_dir()
    os.chdir(kb_dir)

    from tools.discover.discover_domains import discover
    discover(kb_dir, use_ai=True)

    # Update source hash cache
    from tools.incremental import update_hash
    result = update_hash()
    print(f"Hash cache updated: {result['total_files']} files")


def cmd_knowledgebase(skip_discover: bool = False) -> None:
    """Build domains/ + knowledgeBase/: 7-step pipeline."""
    sys.path.insert(0, str(EWANKB_ROOT))

    kb_dir = _resolve_kb_dir()
    os.chdir(kb_dir)

    def _run_script(script_path: Path, extra_args: list[str] | None = None):
        """Run a Python script in subprocess with EWANKB_DIR set."""
        if not script_path.exists():
            print(f"  ({script_path.name} not found — skipping)")
            return
        env = dict(os.environ)
        env["EWANKB_DIR"] = str(kb_dir)
        env["PYTHONPATH"] = str(EWANKB_ROOT)
        env["PYTHONIOENCODING"] = "utf-8"
        cmd = [sys.executable, str(script_path)]
        if extra_args:
            cmd.extend(extra_args)
        result = subprocess.run(cmd, env=env, capture_output=False)
        if result.returncode != 0:
            print(f"  WARNING: {script_path.name} exited with code {result.returncode}")

    scripts = EWANKB_ROOT / "tools" / "extract_kb"

    # Step 1: Auto-discover domains from backend Java code
    if skip_discover:
        print("Step 1/7: Skipped (--skip-discover)")
    else:
        print("Step 1/7: Discovering domains from backend code...")
        from tools.discover.discover_domains import discover
        discover(kb_dir, use_ai=True)

    # Step 2: Analyze code → code_analysis.json
    print("\nStep 2/7: Analyzing code modules...")
    _run_script(scripts / "analyze_code.py")

    # Step 3a: Extract + classify docs → domains/{域名}/{doc_type}/
    print("\nStep 3/7: Extracting and classifying documents...")
    _run_script(scripts / "extract_to_kb.py")

    # Step 3b: Generate code module docs → domains/{域名}/代码模块说明/
    print("\nStep 3b/7: Generating code module documentation...")
    _run_script(scripts / "gen_code_module_docs.py")

    # Step 4: Enrich docs (add code/doc associations to each file)
    print("\nStep 4/7: Enriching documents with code associations...")
    _run_script(scripts / "enrich_kb.py")

    # Step 5: Generate domain overviews (README.md per domain)
    print("\nStep 5/7: Generating domain overviews...")
    _run_script(scripts / "gen_domain_overview.py")

    # Step 6: Generate process documents (PROCESSES.md per domain)
    print("\nStep 6/7: Generating process documents...")
    _run_script(scripts / "gen_processes.py")

    # Step 7: Migrate docs from domains/ to knowledgeBase/, update README paths
    print("\nStep 7/7: Migrating documents to knowledgeBase/...")
    _run_script(scripts / "migrate_to_kb.py")

    # Cleanup empty directories
    from tools.extract_kb.extract_to_kb import cleanup_empty_dirs
    cleanup_empty_dirs(kb_dir / "knowledgeBase")
    cleanup_empty_dirs(kb_dir / "domains")

    # Update source hash cache + doc→domain mapping
    from tools.incremental import update_hash
    result = update_hash()
    print(f"\nHash cache updated: {result['total_files']} files, {result['doc_mappings']} doc mappings")

    # Build BM25 index for query-kb
    from tools.graph_runtime.bm25_index import load_or_build
    bm25, docs = load_or_build()
    print(f"BM25 index built: {len(docs)} documents")

    print("\n=== Knowledge base build complete ===")


def cmd_analyze(args: argparse.Namespace) -> None:
    """Run AST-based code analysis on a directory using graphify."""
    path = Path(args.path).resolve()
    print(f"Analyzing code at {path}...")

    from graphify import extract, collect_files

    files = collect_files(path)
    if not files:
        print("No source files found.")
        return

    print(f"  Found {len(files)} files")
    result = extract(files)

    nodes = result.get("nodes", [])
    edges = result.get("edges", [])

    from collections import Counter
    type_counts = Counter(n.get("type", "unknown") for n in nodes)
    print(f"  Extracted {len(nodes)} nodes, {len(edges)} edges")
    print(f"  Node types:")
    for t, c in type_counts.most_common():
        print(f"    {t}: {c}")


def cmd_build_graph() -> None:
    """Build graph.json using graphify."""
    sys.path.insert(0, str(EWANKB_ROOT))
    from tools.build_graph.graph_builder import build_graph

    kb_dir = _resolve_kb_dir()
    os.chdir(kb_dir)

    from tools import config_loader as cfg
    incremental = cfg.get_global_config().incremental

    print(f"Building graph (incremental={incremental})...")
    graph = build_graph(incremental=incremental)
    meta = graph["metadata"]
    print(f"Done. {meta['num_nodes']} nodes, {meta['num_links']} links")
    print(f"  Code files: {meta.get('code_files', '?')}")
    print(f"  Semantic nodes: {meta.get('semantic_nodes', 0)}")
    print(f"  Semantic edges: {meta.get('semantic_edges', 0)}")
    print(f"  Communities: {meta.get('communities', '?')}")
    print(f"  Engine: {meta.get('engine', '?')}")
    print(f"  Source hash: {meta['source_hash']}")
    print(f"  KB hash:     {meta['kb_hash']}")


def cmd_query(args: argparse.Namespace) -> None:
    """Query the graph."""
    from ewankb.query import query, query_graph_json

    traversal = args.traversal
    if args.depth and not traversal:
        traversal = "bfs"

    # max_nodes: None means use config default; explicit --limit or --depth overrides
    max_nodes = None
    if args.depth:
        max_nodes = args.depth * 15
        if args.limit and args.limit < max_nodes:
            max_nodes = args.limit
    elif args.limit:
        max_nodes = args.limit

    if args.json:
        result = query_graph_json(
            args.text,
            traversal=traversal,
            max_nodes=max_nodes,
            verbose=args.verbose,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        result = query(
            args.text,
            traversal=traversal,
            max_nodes=max_nodes,
            max_tokens=args.max_tokens,
        )
        if args.verbose:
            print(f"[DEBUG] Query: {args.text}", file=sys.stderr)
            print(f"[DEBUG] Traversal: {traversal}, max_nodes: {max_nodes}", file=sys.stderr)
        print(result)


def cmd_query_kb(args: argparse.Namespace) -> None:
    """Query the knowledge base directly."""
    from ewankb.query import query_kb

    result = query_kb(
        args.text,
        domain_filter=args.domain,
        max_results=args.max_results,
    )
    print(result)


def cmd_preflight(args: argparse.Namespace) -> None:
    """Check environment readiness, output JSON. With --fix, auto-create missing items."""
    target = Path(args.dir).resolve() if args.dir else Path.cwd().resolve()
    result: dict = {
        "ewankb_root": str(EWANKB_ROOT),
        "kb_dir": str(target),
        "installed": True,
        "dirs": {},
        "counts": {},
        "api": {},
        "graph": {},
        "ready": True,
        "blockers": [],
    }

    # ── Directory checks ──
    dir_checks = {
        "project_config": target / "project_config.json",
        "llm_config": target / "llm_config.json",
        "source": target / "source",
        "source_repos": target / "source" / "repos",
        "source_docs": target / "source" / "docs",
        "domains": target / "domains",
        "knowledgeBase": target / "knowledgeBase",
        "graph": target / "graph",
    }
    for key, path in dir_checks.items():
        result["dirs"][key] = path.exists()

    # ── --fix: create missing directories and config ──
    if args.fix:
        for d in ["source/repos", "source/docs", "domains/_meta",
                   "knowledgeBase/_meta", "knowledgeBase/_state", "graph/.cache"]:
            (target / d).mkdir(parents=True, exist_ok=True)
        # Re-check after fix
        for key, path in dir_checks.items():
            result["dirs"][key] = path.exists()

        # Create project_config.json + llm_config.json if missing
        cfg_path = target / "project_config.json"
        llm_path = target / "llm_config.json"
        if not cfg_path.exists() or not llm_path.exists():
            sys.path.insert(0, str(EWANKB_ROOT))
            from tools.config_loader import create_project_config, get_global_config
            gcfg = get_global_config()
            create_project_config(target, f"{target.name}业务知识库")
            result["dirs"]["project_config"] = True
            result["dirs"]["llm_config"] = True
            result["config_created"] = True
            result["config_values"] = {
                "base_url": gcfg.base_url or "(default: api.anthropic.com)",
                "model": gcfg.default_model,
            }

    # ── File counts ──
    repos_dir = target / "source" / "repos"
    docs_dir = target / "source" / "docs"
    java_files = list(repos_dir.rglob("*.java")) if repos_dir.exists() else []
    doc_files = list(docs_dir.rglob("*.md")) if docs_dir.exists() else []
    result["counts"]["java_files"] = len(java_files)
    result["counts"]["doc_files"] = len(doc_files)

    # ── API config ──
    sys.path.insert(0, str(EWANKB_ROOT))
    try:
        os.environ["EWANKB_DIR"] = str(target)
        from tools.config_loader import get_project_config, get_llm_config
        # Reset cached config so it reads from target dir
        import tools.config_loader as _cfg_mod
        _cfg_mod._global_cfg = None
        _cfg_mod._project_cfg = None
        _cfg_mod._llm_cfg = None

        llm = get_llm_config()
        pcfg = get_project_config()
        api_key = llm.get("api_key") or pcfg.get("api_key", "")
        base_url = llm.get("base_url") or pcfg.get("base_url", "")
        model = llm.get("model") or pcfg.get("model", "")
        result["api"] = {
            "key_configured": bool(api_key),
            "key_preview": (api_key[:8] + "...") if api_key else "",
            "base_url": base_url,
            "model": model,
        }
    except Exception as e:
        result["api"] = {"key_configured": False, "error": str(e)}

    # ── Graph status ──
    graph_file = target / "graph" / "graph.json"
    if graph_file.exists():
        try:
            with open(graph_file, encoding="utf-8") as f:
                gdata = json.load(f)
            meta = gdata.get("metadata", {})
            result["graph"] = {
                "exists": True,
                "nodes": meta.get("num_nodes", len(gdata.get("nodes", []))),
                "links": meta.get("num_links", len(gdata.get("links", []))),
                "engine": meta.get("engine", "?"),
                "created_at": meta.get("created_at", "?"),
            }
        except Exception:
            result["graph"] = {"exists": True, "error": "parse_failed"}
    else:
        result["graph"] = {"exists": False}

    # ── Blockers ──
    blockers = []
    for required_dir in ("source", "domains", "knowledgeBase", "graph"):
        if not result["dirs"].get(required_dir):
            blockers.append(f"no_{required_dir}")
    if not result["dirs"]["project_config"]:
        blockers.append("no_project_config")
    if not result["dirs"]["llm_config"]:
        blockers.append("no_llm_config")
    if result["counts"]["java_files"] == 0:
        blockers.append("no_java_files")
    if not result["api"].get("key_configured"):
        blockers.append("no_api_key")
    result["blockers"] = blockers
    result["ready"] = len(blockers) == 0

    print(json.dumps(result, indent=2, ensure_ascii=False))
    if not result["ready"]:
        sys.exit(1)


def _resolve_kb_dir() -> Path:
    """Resolve the knowledge base directory."""
    # EWANKB_DIR env var takes precedence
    env_dir = os.environ.get("EWANKB_DIR", "")
    if env_dir:
        return Path(env_dir).resolve()
    # Otherwise use current directory
    cwd = Path.cwd()
    # Check if cwd has project_config.json
    if (cwd / "project_config.json").exists():
        return cwd
    # Check if we're inside the ewan-kb tool repo (wrong location)
    if (cwd / "pyproject.toml").exists() and (cwd / "tools").exists():
        print("Error: Run this command from your knowledge base directory, "
              "or set EWANKB_DIR.", file=sys.stderr)
        sys.exit(1)
    print("Error: project_config.json not found in current directory.", file=sys.stderr)
    print("Run 'ewankb init <name>' first, or 'cd' to your knowledge base directory.", file=sys.stderr)
    sys.exit(1)


def _graph_file() -> Path:
    """Get the graph.json path."""
    kb_dir = _resolve_kb_dir()
    gf = kb_dir / "graph" / "graph.json"
    if not gf.exists():
        print("Error: graph.json not found. Run 'ewankb build' first.", file=sys.stderr)
        sys.exit(1)
    return gf


def cmd_stats() -> None:
    """Show graph stats."""
    sys.path.insert(0, str(EWANKB_ROOT))
    from tools.build_graph.__main__ import _print_stats

    gf = _graph_file()
    with open(gf, encoding="utf-8") as f:
        graph = json.load(f)
    _print_stats(graph)


def cmd_communities() -> None:
    """Show communities."""
    sys.path.insert(0, str(EWANKB_ROOT))
    from tools.build_graph.graph_builder import detect_communities
    from tools.build_graph.__main__ import _print_communities

    gf = _graph_file()
    with open(gf, encoding="utf-8") as f:
        graph = json.load(f)
    communities = detect_communities(graph)
    _print_communities(communities, graph)


def cmd_surprising() -> None:
    """Show surprising connections."""
    sys.path.insert(0, str(EWANKB_ROOT))
    from tools.build_graph.graph_builder import detect_communities, find_surprising_connections
    from tools.build_graph.__main__ import _print_surprising

    gf = _graph_file()
    with open(gf, encoding="utf-8") as f:
        graph = json.load(f)
    communities = detect_communities(graph)
    surprising = find_surprising_connections(graph, communities)
    _print_surprising(surprising)


def cmd_install() -> None:
    """Install ewankb skills to Claude Code (~/.claude/skills/)."""
    # Try pip-installed package location first, then source repo location
    skills_src = EWANKB_ROOT / "ewankb" / "skills"
    if not skills_src.exists():
        skills_src = EWANKB_ROOT / ".claude" / "skills"
    if not skills_src.exists():
        print("Error: skill files not found.", file=sys.stderr)
        print("Please reinstall ewankb or copy skill files manually.", file=sys.stderr)
        sys.exit(1)

    # Determine target directory
    if os.name == "nt":
        home = Path(os.environ.get("USERPROFILE", Path.home()))
    else:
        home = Path.home()
    skills_dst = home / ".claude" / "skills"
    skills_dst.mkdir(parents=True, exist_ok=True)

    # Copy each skill subdirectory (with SKILL.md + references/ etc.)
    copied = []
    for skill_dir in sorted(skills_src.iterdir()):
        if not skill_dir.is_dir() or not (skill_dir / "SKILL.md").exists():
            continue
        dst_dir = skills_dst / skill_dir.name
        if dst_dir.exists():
            shutil.rmtree(dst_dir)
        shutil.copytree(skill_dir, dst_dir)
        copied.append(skill_dir.name)

    print(f"Installed {len(copied)} skill(s) to {skills_dst}/")
    for d in copied:
        print(f"  - {skills_dst / d}/SKILL.md")

    # Update CLAUDE.md with ewankb trigger
    claude_md = home / ".claude" / "CLAUDE.md"
    ewankb_section = (
        "# ewankb\n"
        "- **ewankb** (`~/.claude/skills/ewankb/`) — build knowledge base from Java code + docs. Trigger: `/ewankb`\n"
        "When the user types `/ewankb`, invoke the Skill tool with `skill: \"ewankb\"` before doing anything else.\n"
    )

    if claude_md.exists():
        content = claude_md.read_text(encoding="utf-8")
        if "# ewankb" not in content:
            content = content.rstrip() + "\n\n" + ewankb_section
            claude_md.write_text(content, encoding="utf-8")
            print(f"\nAdded ewankb trigger to {claude_md}")
        else:
            print(f"\newankb trigger already in {claude_md}")
    else:
        claude_md.parent.mkdir(parents=True, exist_ok=True)
        claude_md.write_text(ewankb_section, encoding="utf-8")
        print(f"\nCreated {claude_md} with ewankb trigger")

    print(f"\nDone. Use /ewankb in Claude Code to build a knowledge base.")


def cmd_config(args: argparse.Namespace) -> None:
    """Show or edit project config."""
    kb_dir = _resolve_kb_dir()
    config_file = kb_dir / "project_config.json"
    llm_file = kb_dir / "llm_config.json"

    if getattr(args, 'edit_llm', False):
        editor = os.environ.get("EDITOR", "notepad" if os.name == "nt" else "vim")
        os.system(f'"{editor}" "{llm_file}"')
    elif args.edit:
        editor = os.environ.get("EDITOR", "notepad" if os.name == "nt" else "vim")
        os.system(f'"{editor}" "{config_file}"')
    elif args.show:
        with open(config_file, encoding="utf-8") as f:
            print(f.read())
    else:
        with open(config_file, encoding="utf-8") as f:
            data = json.load(f)
        print(f"project_name: {data.get('project_name', '?')}")
        print(f"system_name:  {data.get('system_name', '?')}")
        # Show domains from domains.json (auto-discovered)
        domains_file = kb_dir / "domains" / "_meta" / "domains.json"
        if domains_file.exists():
            with open(domains_file, encoding="utf-8") as f:
                domains_data = json.load(f)
            domain_list = domains_data.get("domain_list", [])
            print(f"domains:      {len(domain_list)} (auto-discovered)")
            for d in domain_list[:10]:
                print(f"  - {d}")
            if len(domain_list) > 10:
                print(f"  ... and {len(domain_list) - 10} more")
        else:
            print("domains:      (not yet discovered — run ewankb extract)")


if __name__ == "__main__":
    main()
