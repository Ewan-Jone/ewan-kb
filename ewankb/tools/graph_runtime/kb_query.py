#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Knowledge base direct query — BM25 retrieval over domains/ + knowledgeBase/ + source/docs/.

Uses jieba tokenization + rank_bm25 for scoring, with cached index for fast queries.
"""
from __future__ import annotations

import re
from pathlib import Path

from .. import config_loader as cfg
from .bm25_index import load_or_build
from ..text_utils import tokenize


def query_kb(
    query_text: str,
    max_results: int = 8,
    max_chars: int = 12000,
    domain_filter: str | None = None,
    kb_dir: Path | None = None,
) -> str:
    """
    Search knowledge base documents using BM25 ranking.

    Searches three locations:
      1. domains/ — domain README.md and PROCESSES.md
      2. knowledgeBase/{doc_type}/ — refined documents
      3. source/docs/ — raw source documents

    Returns formatted text with matched document excerpts.
    """
    if kb_dir is None:
        kb_dir = cfg.get_kb_dir()

    query_tokens = tokenize(query_text)
    if not query_tokens:
        return "(无法从查询中提取关键词)"

    bm25, docs = load_or_build(kb_dir=kb_dir)

    if not docs:
        return "(知识库中没有文档)"

    # BM25 评分
    scores = bm25.get_scores(query_tokens)

    # 组合 (score, index)，按分数降序
    scored = sorted(
        ((scores[i], i) for i in range(len(docs)) if scores[i] > 0),
        key=lambda x: -x[0],
    )

    # domain filter
    if domain_filter:
        scored = [
            (s, i) for s, i in scored
            if domain_filter in docs[i].domain or docs[i].domain in domain_filter
            or docs[i].path.parent.name == domain_filter
        ]

    top = scored[:max_results]

    if not top:
        return f"(未找到与 \"{query_text}\" 相关的文档)"

    # 渲染结果
    lines: list[str] = []
    current_chars = 0

    header_line = f"找到 {len(scored)} 个相关文档（展示前 {len(top)} 个）：\n"
    lines.append(header_line)
    current_chars += len(header_line)

    for rank, (score, idx) in enumerate(top, 1):
        doc = docs[idx]

        # 相对路径
        try:
            rel = doc.path.relative_to(kb_dir)
        except ValueError:
            rel = doc.path.name

        # source label
        rel_str = str(rel).replace("\\", "/")
        if rel_str.startswith("domains/"):
            source_label = "domain"
        elif rel_str.startswith("knowledgeBase/"):
            source_label = f"kb/{doc.path.parent.name}"
        else:
            source_label = "source"

        header = f"--- [{rank}] {doc.title} (score={score:.2f}) ---"
        meta_parts = []
        if doc.domain:
            meta_parts.append(f"域: {doc.domain}")
        if doc.doc_type:
            meta_parts.append(f"类型: {doc.doc_type}")
        meta_parts.append(f"来源: {source_label}")
        meta_parts.append(f"路径: {rel}")
        meta_line = "  ".join(meta_parts)

        # 字符预算
        remaining = max_chars - current_chars - len(header) - len(meta_line) - 20
        if remaining < 200:
            lines.append(f"\n{header}")
            lines.append(meta_line)
            lines.append("(已达字符上限，省略内容)")
            break

        # 读取内容（preview）
        try:
            content = doc.path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            content = ""
        content = re.sub(r'^---\n.*?\n---\n*', '', content, flags=re.DOTALL)
        if len(content) > remaining:
            content = content[:remaining] + "\n..."

        block = f"\n{header}\n{meta_line}\n\n{content}"
        lines.append(block)
        current_chars += len(block)

    return "\n".join(lines)