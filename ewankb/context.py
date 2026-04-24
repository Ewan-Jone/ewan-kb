"""Per-KB context: wraps loaded graph, BM25 index, and config for a single knowledge base."""
from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Any

import networkx as nx
from rank_bm25 import BM25Okapi


class KBContext:
    """Per-KB context holding loaded graph, BM25 index, and config.

    Bypasses config_loader's singleton by temporarily setting EWANKB_DIR
    and clearing caches during init. After init, all data is held in this
    object and config_loader is no longer consulted for queries.
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

        Temporarily sets EWANKB_DIR and resets config_loader caches
        so it reads from the correct KB directory.
        """
        import tools.config_loader as cfg

        old_env = os.environ.get("EWANKB_DIR", "")
        os.environ["EWANKB_DIR"] = str(self.kb_dir)

        # Reset all cached configs
        cfg._global_cfg = None
        cfg._project_cfg = None
        cfg._llm_cfg = None

        self.gcfg = cfg.get_global_config()
        self.pcfg = cfg.get_project_config()

        # Restore env (other KBs may need different values)
        if old_env:
            os.environ["EWANKB_DIR"] = old_env
        else:
            os.environ.pop("EWANKB_DIR", None)
        cfg._global_cfg = None
        cfg._project_cfg = None
        cfg._llm_cfg = None

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
        import tools.config_loader as cfg
        from tools.graph_runtime.bm25_index import load_or_build

        old_env = os.environ.get("EWANKB_DIR", "")
        os.environ["EWANKB_DIR"] = str(self.kb_dir)
        cfg._global_cfg = None
        cfg._project_cfg = None
        cfg._llm_cfg = None

        self.bm25, self.docs = load_or_build()

        if old_env:
            os.environ["EWANKB_DIR"] = old_env
        else:
            os.environ.pop("EWANKB_DIR", None)
        cfg._global_cfg = None
        cfg._project_cfg = None
        cfg._llm_cfg = None

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
        from tools.graph_runtime.query_engine import (
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
                traversal=traversal,
                max_nodes=max_nodes,
                verbose=True,
            )
        if max_tokens is None:
            max_tokens = self.gcfg.default_max_tokens
        return _query(
            query_text,
            traversal=traversal,
            max_nodes=max_nodes,
            max_tokens=max_tokens,
        )

    def query_kb(
        self,
        query_text: str,
        max_results: int = 8,
        max_chars: int = 12000,
        domain_filter: str | None = None,
    ) -> str:
        """Search knowledge base documents using BM25."""
        from tools.graph_runtime.kb_query import query_kb as _query_kb

        return _query_kb(
            query_text,
            max_results=max_results,
            max_chars=max_chars,
            domain_filter=domain_filter,
        )

    def preflight(self) -> dict[str, Any]:
        """Run preflight check for this KB, returning structured result."""
        from ewankb.__main__ import cmd_preflight

        # Build a fake args namespace
        import argparse
        args = argparse.Namespace(dir=str(self.kb_dir), fix=False)
        # Capture output by redirecting stdout
        import io
        old_stdout = io.StringIO()
        import sys
        real_stdout = sys.stdout
        sys.stdout = old_stdout
        try:
            cmd_preflight(args)
        except SystemExit:
            pass
        finally:
            sys.stdout = real_stdout
        output = old_stdout.getvalue()
        try:
            return json.loads(output)
        except json.JSONDecodeError:
            return {"raw_output": output}

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