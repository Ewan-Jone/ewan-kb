#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
BM25 索引构建与查询 — 基于 rank_bm25 + jieba 分词。

索引覆盖：domains/ + knowledgeBase/ + source/docs/ 下的所有 .md 文件。
缓存位置：graph/.cache/bm25_index.pkl
失效策略：源文件最大 mtime > 索引文件 mtime 时自动重建。
"""
from __future__ import annotations

import pickle
import re
from pathlib import Path
from typing import Any

from rank_bm25 import BM25Okapi

from tools import config_loader as cfg
from tools.text_utils import parse_frontmatter, tokenize


# ── 文档元数据 ──────────────────────────────────────────────────────────────────

class DocEntry:
    __slots__ = ("path", "title", "domain", "doc_type", "tokens")

    def __init__(self, path: Path, title: str, domain: str, doc_type: str, tokens: list[str]):
        self.path = path
        self.title = title
        self.domain = domain
        self.doc_type = doc_type
        self.tokens = tokens


# ── 索引构建 ──────────────────────────────────────────────────────────────────

def _collect_md_files() -> list[Path]:
    """收集所有待索引的 .md 文件。"""
    kb_dir = cfg.get_kb_dir()
    domains_dir = cfg.get_domains_dir()
    knowledge_base = cfg.get_knowledge_base_dir()
    source_docs = cfg.get_source_dir() / "docs"

    files: list[Path] = []

    if domains_dir.exists():
        for md in domains_dir.rglob("*.md"):
            if md.parent.name == "_meta":
                continue
            files.append(md)

    if knowledge_base.exists():
        for type_dir in knowledge_base.iterdir():
            if not type_dir.is_dir() or type_dir.name.startswith("_"):
                continue
            for md in type_dir.glob("*.md"):
                files.append(md)

    if source_docs.exists():
        for md in source_docs.rglob("*.md"):
            files.append(md)

    return files


def _parse_doc(path: Path) -> DocEntry | None:
    """解析单个 .md 文件，提取元数据和 tokens。"""
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None

    fm = parse_frontmatter(content[:500])
    title = fm.get("title", path.stem)
    domain = fm.get("domain", "")
    doc_type = fm.get("type", "")

    # 去掉 frontmatter 再分词
    body = re.sub(r'^---\n.*?\n---\n*', '', content, flags=re.DOTALL)

    # 标题权重：将标题重复 3 次加入 token 流（提升标题匹配权重）
    title_tokens = tokenize(title) * 3
    body_tokens = tokenize(body[:8000])  # 限制长度避免超大文档拖慢索引
    tokens = title_tokens + body_tokens

    if not tokens:
        return None

    return DocEntry(path=path, title=title, domain=domain, doc_type=doc_type, tokens=tokens)


def build_index() -> tuple[BM25Okapi, list[DocEntry]]:
    """扫描所有文档，构建 BM25 索引。"""
    files = _collect_md_files()
    docs: list[DocEntry] = []

    for f in files:
        entry = _parse_doc(f)
        if entry:
            docs.append(entry)

    corpus = [d.tokens for d in docs]
    bm25 = BM25Okapi(corpus) if corpus else BM25Okapi([[""]])
    return bm25, docs


# ── 缓存管理 ──────────────────────────────────────────────────────────────────

def _cache_path() -> Path:
    return cfg.get_knowledge_base_dir() / "_state" / "bm25_index.pkl"


def _max_source_mtime() -> float:
    """获取所有源 .md 文件中最大的 mtime。"""
    max_mt = 0.0
    for f in _collect_md_files():
        try:
            mt = f.stat().st_mtime
            if mt > max_mt:
                max_mt = mt
        except Exception:
            pass
    return max_mt


def load_or_build() -> tuple[BM25Okapi, list[DocEntry]]:
    """加载缓存的索引，如果过期或不存在则重建。"""
    cp = _cache_path()

    if cp.exists():
        try:
            idx_mtime = cp.stat().st_mtime
            if _max_source_mtime() <= idx_mtime:
                with open(cp, "rb") as f:
                    data = pickle.load(f)
                return data["bm25"], data["docs"]
        except Exception:
            pass

    # 重建
    bm25, docs = build_index()

    # 缓存
    try:
        cp.parent.mkdir(parents=True, exist_ok=True)
        with open(cp, "wb") as f:
            pickle.dump({"bm25": bm25, "docs": docs}, f)
    except Exception:
        pass

    return bm25, docs
