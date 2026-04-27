"""Per-KB context: wraps loaded graph, BM25 index, and config for a single knowledge base."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import networkx as nx
from rank_bm25 import BM25Okapi


class KBContext:
    """Per-KB context holding loaded graph, BM25 index, and config.

    Loads configs by reading JSON files directly from kb_dir for project config,
    and using the global (user-wide) config_loader for global settings.
    No EWANKB_DIR env manipulation or config cache resets needed.
    """

    def __init__(self, kb_dir: Path) -> None:
        self.kb_dir = kb_dir.resolve()
        self.graph_data: dict[str, Any] | None = None
        self.G: nx.DiGraph | None = None
        self.bm25: BM25Okapi | None = None
        self.docs: list[Any] | None = None
        self.gcfg: Any = None  # GlobalConfig
        self.pcfg: dict[str, Any] | None = None
        self._load_config()

    def _load_config(self) -> None:
        """Load global + project config for this KB dir.

        Global config is user-wide (from ~/.config/ewankb/ewankb.toml), not KB-specific.
        Project config is KB-specific — read directly from kb_dir/project_config.json.
        """
        from ewankb.tools.config_loader import get_global_config

        self.gcfg = get_global_config()

        pcfg_path = self.kb_dir / "project_config.json"
        if pcfg_path.exists():
            with open(pcfg_path, encoding="utf-8") as f:
                self.pcfg = json.load(f)
        else:
            self.pcfg = {}

    def load_graph(self) -> None:
        """Load graph.json and build NetworkX DiGraph for this KB."""
        graph_file = self.kb_dir / "graph" / "graph.json"
        with open(graph_file, encoding="utf-8") as f:
            self.graph_data = json.load(f)

        self.G = nx.DiGraph()
        for node in self.graph_data["nodes"]:
            self.G.add_node(node["id"], **node)
        for link in self.graph_data["links"]:
            if link["source"] in self.G and link["target"] in self.G:
                self.G.add_edge(link["source"], link["target"], **link)

    def load_bm25(self) -> None:
        """Build or load BM25 index for this KB."""
        from ewankb.tools.graph_runtime.bm25_index import load_or_build

        self.bm25, self.docs = load_or_build(kb_dir=self.kb_dir)

    def query_graph(
        self,
        query_text: str,
        traversal: str | None = None,
        max_nodes: int | None = None,
        max_tokens: int | None = None,
        verbose: bool = False,
    ) -> str | dict[str, Any]:
        """Query the knowledge graph.

        Returns rendered text (if verbose=False) or structured dict (if verbose=True).
        """
        from ewankb.tools.graph_runtime.query_engine import (
            query as _query,
            query_graph_json as _query_graph_json,
        )

        if traversal is None:
            traversal = self.gcfg.default_traversal
        if max_nodes is None:
            max_nodes = self.gcfg.max_nodes

        if verbose:
            return _query_graph_json(
                query_text,
                graph_file=self.kb_dir / "graph" / "graph.json",
                traversal=traversal,
                max_nodes=max_nodes,
                verbose=True,
                gcfg=self.gcfg,
            )
        if max_tokens is None:
            max_tokens = self.gcfg.default_max_tokens
        return _query(
            query_text,
            graph_file=self.kb_dir / "graph" / "graph.json",
            traversal=traversal,
            max_nodes=max_nodes,
            max_tokens=max_tokens,
            gcfg=self.gcfg,
        )

    def query_kb(
        self,
        query_text: str,
        max_results: int = 8,
        max_chars: int = 12000,
        domain_filter: str | None = None,
    ) -> str:
        """Search knowledge base documents using BM25."""
        from ewankb.tools.graph_runtime.kb_query import query_kb as _query_kb

        return _query_kb(
            query_text,
            max_results=max_results,
            max_chars=max_chars,
            domain_filter=domain_filter,
            kb_dir=self.kb_dir,
        )

    def preflight(self) -> dict[str, Any]:
        """Run preflight check for this KB, returning structured result.

        Reimplements the check logic directly (instead of calling cmd_preflight)
        to avoid sys.stdout hijacking and SystemExit issues.
        """
        import json as _json

        target = self.kb_dir
        result: dict[str, Any] = {
            "kb_dir": str(target),
            "dirs": {},
            "counts": {},
            "api": {},
            "graph": {},
            "ready": True,
            "blockers": [],
        }

        # Directory checks
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

        # File counts
        repos_dir = target / "source" / "repos"
        docs_dir = target / "source" / "docs"
        java_files = list(repos_dir.rglob("*.java")) if repos_dir.exists() else []
        doc_files = list(docs_dir.rglob("*.md")) if docs_dir.exists() else []
        result["counts"]["java_files"] = len(java_files)
        result["counts"]["doc_files"] = len(doc_files)

        # API config
        llm = self.gcfg  # already loaded
        api_key = ""
        base_url = ""
        model = ""
        if self.pcfg:
            llm_data = {}
            llm_path = target / "llm_config.json"
            if llm_path.exists():
                with open(llm_path, encoding="utf-8") as f:
                    llm_data = _json.load(f)
            api_key = llm_data.get("api_key") or self.pcfg.get("api_key", "")
            base_url = llm_data.get("base_url") or self.pcfg.get("base_url", "")
            model = llm_data.get("model") or self.pcfg.get("model", "")
        result["api"] = {
            "key_configured": bool(api_key),
            "key_preview": (api_key[:8] + "...") if api_key else "",
            "base_url": base_url,
            "model": model,
        }

        # Graph status
        graph_file = target / "graph" / "graph.json"
        if graph_file.exists():
            try:
                with open(graph_file, encoding="utf-8") as f:
                    gdata = _json.load(f)
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

        # Blockers
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

        return result

    def info(self) -> dict[str, Any]:
        """Return summary info about this KB context."""
        return {
            "kb_dir": str(self.kb_dir),
            "graph_loaded": self.G is not None,
            "graph_nodes": len(self.G.nodes()) if self.G else 0,
            "graph_edges": len(self.G.edges()) if self.G else 0,
            "bm25_loaded": self.bm25 is not None,
            "bm25_docs": len(self.docs) if self.docs else 0,
            "project_name": self.pcfg.get("project_name", "") if self.pcfg else "",
        }