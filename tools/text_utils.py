"""Shared text utilities used across ewankb tools."""

import re

_CHINESE_RE = re.compile(r"[\u4e00-\u9fff]+")
_ALNUM_RE = re.compile(r"[a-zA-Z0-9_]+")

# 中文停用词（高频无意义词）
_CN_STOPWORDS = frozenset(
    "的 了 在 是 我 有 和 就 不 人 都 一 一个 上 也 很 到 说 要 去 你 会 着 没有 看 好 自己 这"
    " 他 她 它 们 这个 那个 什么 怎么 如果 但是 因为 所以 可以 已经 还是 或者 以及 对于 关于"
    " 进行 通过 使用 支持 包括 其中 以下 根据 需要 相关 以上 同时 目前 主要 其他 具体".split()
)


def parse_frontmatter(text: str) -> dict:
    """Parse YAML frontmatter from a markdown string."""
    m = re.match(r'^---\n(.*?)\n---', text, re.DOTALL)
    if not m:
        return {}
    fm = {}
    for line in m.group(1).splitlines():
        if ':' in line:
            k, _, v = line.partition(':')
            fm[k.strip()] = v.strip().strip('"')
    return fm


def extract_keywords(text: str) -> set[str]:
    """Extract significant Chinese and alphanumeric words from text."""
    words = set()
    for match in _CHINESE_RE.findall(text):
        if len(match) >= 2:
            words.add(match)
    for match in _ALNUM_RE.findall(text):
        if len(match) >= 3:
            words.add(match.lower())
    return words


def tokenize(text: str) -> list[str]:
    """对文本做 jieba 分词 + 英文保留，去停用词，返回 token 列表。"""
    import jieba

    tokens = []
    for word in jieba.cut(text):
        word = word.strip()
        if not word:
            continue
        # 纯标点 / 空白跳过
        if re.fullmatch(r'[\s\W]+', word):
            continue
        lower = word.lower()
        if lower in _CN_STOPWORDS:
            continue
        # 单字中文跳过（区分度低）
        if len(word) == 1 and _CHINESE_RE.fullmatch(word):
            continue
        tokens.append(lower)
    return tokens
