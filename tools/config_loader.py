#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Ewan-kb configuration loader.

Loads from three levels:
  - ~/.config/ewankb/ewankb.toml (global defaults)
  - project_dir/project_config.json (project metadata, safe to commit)
  - project_dir/llm_config.json (LLM credentials, git-ignored)
"""
from __future__ import annotations

import os
import json
import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib
from dataclasses import dataclass, field
from typing import Any


# ── Standard document types (the only allowed folder names under domain dirs) ─

STANDARD_DOC_TYPES = ["需求文档", "接口文档", "业务规则", "测试用例", "研发设计文档", "其他"]


# ── Path resolution ──────────────────────────────────────────────────────────

def _get_config_dir() -> Path:
    """Global config directory (~/.config/ewankb/)."""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path.home() / ".config"
    return base / "ewankb"


def _get_ewankb_dir() -> Path:
    """Current knowledge base directory (EWANKB_DIR env or global default)."""
    env = os.environ.get("EWANKB_DIR", "")
    if env:
        return Path(env)
    cfg_dir = _get_config_dir()
    cfg_file = cfg_dir / "ewankb.toml"
    if cfg_file.exists():
        try:
            with open(cfg_file, "rb") as f:
                data = tomllib.load(f)
            default_dir = data.get("kb", {}).get("default_dir", "")
            if default_dir:
                return Path(default_dir)
        except Exception:
            pass
    return Path.cwd()


# ── Global config (ewankb.toml) ─────────────────────────────────────────────

@dataclass
class GlobalConfig:
    default_traversal: str = "bfs"
    max_nodes: int = 100
    chars_per_token: int = 4
    cache_dir: str = ".cache"
    default_model: str = "claude-haiku-4-5-20251001"
    extraction_max_tokens: int = 4096
    parallel_workers: int = 8
    skip_semantic: bool = False
    incremental: bool = True
    default_max_tokens: int = 8192
    show_node_type: bool = True
    show_trust_tags: bool = False
    community_algorithm: str = "leiden"
    max_community_fraction: float = 0.25
    min_community_size: int = 3
    api_key: str = ""
    base_url: str = ""


_global_cfg: GlobalConfig | None = None


def get_global_config() -> GlobalConfig:
    """Load and cache global config from ewankb.toml."""
    global _global_cfg
    if _global_cfg is not None:
        return _global_cfg

    cfg = GlobalConfig()
    cfg_file = _get_config_dir() / "ewankb.toml"
    if cfg_file.exists():
        try:
            with open(cfg_file, "rb") as f:
                data = tomllib.load(f)
            g = data.get("graph", {})
            cfg.default_traversal = g.get("default_traversal", "bfs")
            cfg.max_nodes = g.get("max_nodes", 100)
            cfg.chars_per_token = g.get("chars_per_token", 4)
            cfg.cache_dir = g.get("cache_dir", ".cache")
            api = data.get("api", {})
            cfg.default_model = api.get("default_model", cfg.default_model)
            cfg.extraction_max_tokens = api.get("extraction_max_tokens", 4096)
            cfg.api_key = api.get("api_key", os.environ.get("ANTHROPIC_API_KEY", ""))
            cfg.base_url = api.get("base_url", os.environ.get("ANTHROPIC_BASE_URL", ""))
            bld = data.get("build", {})
            cfg.parallel_workers = bld.get("parallel_workers", 4)
            cfg.skip_semantic = bld.get("skip_semantic", False)
            cfg.incremental = bld.get("incremental", True)
            qry = data.get("query", {})
            cfg.default_max_tokens = qry.get("default_max_tokens", 8192)
            cfg.show_node_type = qry.get("show_node_type", True)
            cfg.show_trust_tags = qry.get("show_trust_tags", False)
            com = data.get("community", {})
            cfg.community_algorithm = com.get("algorithm", "leiden")
            cfg.max_community_fraction = com.get("max_community_fraction", 0.25)
            cfg.min_community_size = com.get("min_community_size", 3)
        except Exception:
            pass

    # Env var overrides
    if os.environ.get("ANTHROPIC_API_KEY"):
        cfg.api_key = os.environ["ANTHROPIC_API_KEY"]
    if os.environ.get("ANTHROPIC_BASE_URL"):
        cfg.base_url = os.environ["ANTHROPIC_BASE_URL"]

    _global_cfg = cfg
    return cfg


# ── Project config (project_config.json) ─────────────────────────────────────

_project_cfg: dict[str, Any] | None = None


def get_project_config() -> dict[str, Any]:
    """Load project_config.json from the current kb directory. Auto-fills empty segment_stopwords on first load."""
    global _project_cfg
    if _project_cfg is not None:
        return _project_cfg
    kb_dir = get_kb_dir()
    cfg_path = kb_dir / "project_config.json"
    if not cfg_path.exists():
        return {}
    with open(cfg_path, encoding="utf-8") as f:
        _project_cfg = json.load(f)

    # Auto-fill empty segment_stopwords from built-in defaults
    data = _project_cfg.get("segment_stopwords", {})
    needs_fill = not data or any(
        not data.get(key, {}).get("words")
        for key in ("segment_stopwords", "package_wrappers", "generic_noise")
    )
    if needs_fill:
        builtin = _load_builtin_stopwords()
        _fill_empty_stopwords_to_config(builtin)
        _project_cfg = None  # reset cache so next call reads the updated file
        with open(cfg_path, encoding="utf-8") as f:
            _project_cfg = json.load(f)

    return _project_cfg


_llm_cfg: dict[str, Any] | None = None


def get_llm_config() -> dict[str, Any]:
    """Load llm_config.json from the current kb directory."""
    global _llm_cfg
    if _llm_cfg is not None:
        return _llm_cfg
    kb_dir = get_kb_dir()
    cfg_path = kb_dir / "llm_config.json"
    if not cfg_path.exists():
        return {}
    with open(cfg_path, encoding="utf-8") as f:
        _llm_cfg = json.load(f)
    return _llm_cfg


def get_kb_dir() -> Path:
    """Knowledge base root directory."""
    return _get_ewankb_dir()


def get_source_dir() -> Path:
    """Source documents and repos directory."""
    return get_kb_dir() / "source"


def get_knowledge_base_dir() -> Path:
    """Refined knowledge base directory."""
    return get_kb_dir() / "knowledgeBase"


def get_domains_dir() -> Path:
    """Domains directory (domain folders with README.md, PROCESSES.md)."""
    return get_kb_dir() / "domains"


def get_graph_dir() -> Path:
    """Graph output directory."""
    return get_kb_dir() / "graph"


def get_cache_dir() -> Path:
    """File hash cache directory."""
    return get_graph_dir() / get_global_config().cache_dir


# ── Domain helpers (read from domains/_meta/domains.json) ──────────────

def _load_domains_json() -> dict:
    """Load domains.json. Checks domains/_meta/ first, falls back to knowledgeBase/_meta/ for backward compat."""
    # New location: domains/_meta/domains.json
    domains_file = get_domains_dir() / "_meta" / "domains.json"
    if not domains_file.exists():
        # Fallback: old location for backward compatibility
        domains_file = get_knowledge_base_dir() / "_meta" / "domains.json"
    if not domains_file.exists():
        return {"domains": {}, "domain_list": [], "english_to_chinese": {}}
    with open(domains_file, encoding="utf-8") as f:
        return json.load(f)


def get_domains() -> list[str]:
    """Flat list of domain names (Chinese) from auto-discovered domains.json."""
    return _load_domains_json().get("domain_list", [])


def get_domain_classification_rules() -> list[tuple[str, list[str]]]:
    """Derive classification rules from domains.json doc_keywords + english_keys."""
    data = _load_domains_json()
    rules = []
    for name, info in data.get("domains", {}).items():
        keywords = list(info.get("doc_keywords", []))
        # Also include english_keys as fallback patterns
        keywords.extend(info.get("english_keys", []))
        if keywords:
            rules.append((name, keywords))
    return rules


def get_doc_type_rules() -> list[tuple[str, list[str]]]:
    raw = get_project_config().get("doc_type_rules", [])
    return [(r["type"], r["patterns"]) for r in raw]


def get_code_structure() -> dict:
    return get_project_config().get("code_structure", {})


# ── Legacy paths (for extract_kb scripts) ──────────────────────────────────────

def get_repos_dir() -> Path:
    """Code repos directory (source/repos/)."""
    return get_source_dir() / "repos"


def get_schema_index_path() -> Path:
    """DB schema index file path."""
    return get_kb_dir() / "tools" / "fetch_db_schema" / "schema_index.json"


# ── Domain → mapping helpers (derived from domains.json) ──────────────────────

def get_domain_to_modules() -> dict[str, list[str]]:
    """Map domain name → list of module names, from domains.json."""
    data = _load_domains_json()
    return {name: info.get("modules", [])
            for name, info in data.get("domains", {}).items()}


def get_domain_descriptions() -> dict[str, str]:
    """Map domain name → description, from domains.json."""
    data = _load_domains_json()
    return {name: info.get("description", "")
            for name, info in data.get("domains", {}).items()}


def get_parent_domain(domain: str) -> str:
    """Get parent domain from hierarchical path.

    E.g. '物流订单/订舱管理' → '物流订单', '合同管理' → ''
    """
    if "/" in domain:
        return domain.rsplit("/", 1)[0]
    return ""


# ── Skip settings ─────────────────────────────────────────────────────────────

def get_skip_domains() -> set:
    return set(get_project_config().get("skip_domains", []))


def get_skip_doc_types_for_enrich() -> set:
    return set(get_project_config().get("skip_doc_types_for_enrich", []))


def get_system_fields() -> set:
    return set(get_project_config().get("system_fields", []))


def get_segment_stopwords() -> tuple[frozenset, frozenset, frozenset]:
    """Read segment stopwords from project_config.json. Empty word lists are auto-filled by get_project_config()."""
    pcfg = get_project_config()
    data = pcfg.get("segment_stopwords", {})
    return (
        frozenset(data.get("segment_stopwords", {}).get("words", [])),
        frozenset(data.get("package_wrappers", {}).get("words", [])),
        frozenset(data.get("generic_noise", {}).get("words", [])),
    )


def _fill_empty_stopwords_to_config(builtin: dict) -> None:
    """Fill empty segment_stopwords word lists into project_config.json from built-in defaults.

    Only fills empty lists; never overwrites existing words.
    """
    global _project_cfg
    kb_dir = get_kb_dir()
    cfg_path = kb_dir / "project_config.json"
    if not cfg_path.exists():
        return
    try:
        with open(cfg_path, encoding="utf-8") as f:
            raw = json.load(f)
        existing = raw.get("segment_stopwords", {})
        if not existing:
            raw["segment_stopwords"] = builtin
        else:
            for key in ("segment_stopwords", "package_wrappers", "generic_noise"):
                if not existing.get(key, {}).get("words"):
                    existing.setdefault(key, {})["words"] = builtin.get(key, {}).get("words", [])
            raw["segment_stopwords"] = existing
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(raw, f, indent=2, ensure_ascii=False)
        _project_cfg = raw
        print(f"  Filled empty segment_stopwords into {cfg_path}", file=sys.stderr)
    except Exception:
        pass


# ── Domain directory helpers ──────────────────────────────────────────────────

_DEFAULT_DOC_TYPE_RULES = [
    {"type": "业务规则", "patterns": ["规则", "规范", "校验", "标准"]},
    {"type": "需求文档", "patterns": ["需求", "方案", "PRD", "功能设计", "功能说明"]},
    {"type": "接口文档", "patterns": ["接口", "API", "POST", "GET", "REST"]},
    {"type": "测试用例", "patterns": ["测试", "用例", "test", "验收"]},
    {"type": "研发设计文档", "patterns": ["设计", "详细设计", "技术方案", "架构", "开发设计"]},
]


def create_project_config(target_dir: Path, project_name: str) -> dict:
    """Create project_config.json (metadata) and llm_config.json (LLM credentials). Returns project config dict."""
    gcfg = get_global_config()

    # Load built-in stopwords from tools/discover/segment_stopwords.json
    stopwords_data = _load_builtin_stopwords()

    # project_config.json — safe to commit
    project_cfg = {
        "project_name": project_name,
        "system_name": target_dir.name,
        "doc_type_rules": _DEFAULT_DOC_TYPE_RULES,
        "source_dirs": [],
        "code_structure": {},
        "segment_stopwords": stopwords_data,
    }
    with open(target_dir / "project_config.json", "w", encoding="utf-8") as f:
        json.dump(project_cfg, f, indent=2, ensure_ascii=False)

    # llm_config.json — git-ignored, user must fill in
    llm_cfg = {
        "api_key": "",
        "base_url": gcfg.base_url,
        "model": gcfg.default_model,
        "api_protocol": "anthropic",
    }
    with open(target_dir / "llm_config.json", "w", encoding="utf-8") as f:
        json.dump(llm_cfg, f, indent=2, ensure_ascii=False)

    return project_cfg


def _load_builtin_stopwords() -> dict:
    """Read built-in segment_stopwords.json from the ewankb tools directory."""
    import importlib.resources
    try:
        # Try reading from package data first (pip install)
        pkg_path = Path(__file__).resolve().parent.parent / "tools" / "discover" / "segment_stopwords.json"
        if pkg_path.exists():
            return json.loads(pkg_path.read_text(encoding="utf-8"))
    except Exception:
        pass
    # Fallback: empty structure
    return {
        "segment_stopwords": {"words": []},
        "package_wrappers": {"words": []},
        "generic_noise": {"words": []},
    }


# ── LLM 统一调用层 ──────────────────────────────────────────────────────────

def _resolve_llm_config() -> dict:
    """从 llm_config.json 读取 LLM 配置（兼容旧版 project_config.json）。"""
    llm = get_llm_config()
    pcfg = get_project_config()
    return {
        "api_key": llm.get("api_key") or pcfg.get("api_key", ""),
        "base_url": llm.get("base_url") or pcfg.get("base_url", ""),
        "model": llm.get("model") or pcfg.get("model", "claude-haiku-4-5-20251001"),
        "protocol": llm.get("api_protocol") or pcfg.get("api_protocol", "anthropic"),
    }


def create_llm_client():
    """创建 LLM 客户端（根据 api_protocol 自动选择 Anthropic 或 OpenAI SDK）。"""
    c = _resolve_llm_config()
    if c["protocol"] == "openai":
        from openai import OpenAI
        return OpenAI(api_key=c["api_key"], base_url=c["base_url"] or None)
    else:
        import anthropic
        return anthropic.Anthropic(api_key=c["api_key"], base_url=c["base_url"] or None)


def get_llm_model() -> str:
    """返回当前配置的模型名称。"""
    return _resolve_llm_config()["model"]


def get_llm_protocol() -> str:
    """返回当前 API 协议类型：'anthropic' 或 'openai'。"""
    return _resolve_llm_config()["protocol"]


def call_llm(prompt: str, *, max_tokens: int = 4096, client=None) -> str:
    """统一 LLM 调用入口，自动适配 Anthropic / OpenAI 协议。

    Args:
        prompt: 用户 prompt 文本
        max_tokens: 最大输出 token 数
        client: 可选，复用已有客户端（多线程场景各线程自建 client 传入）
    """
    import time

    c = _resolve_llm_config()
    model = c["model"]
    protocol = c["protocol"]
    if client is None:
        client = create_llm_client()

    clean_prompt = prompt.encode("utf-8", errors="replace").decode("utf-8")

    for attempt in range(3):
        try:
            if protocol == "openai":
                resp = client.chat.completions.create(
                    model=model,
                    max_tokens=max_tokens,
                    messages=[{"role": "user", "content": clean_prompt}],
                )
                return resp.choices[0].message.content
            else:
                resp = client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    messages=[{"role": "user", "content": clean_prompt}],
                )
                for block in resp.content:
                    if getattr(block, "type", None) == "text":
                        return block.text
                for block in resp.content:
                    if getattr(block, "type", None) != "thinking" and hasattr(block, "text"):
                        return block.text
                return ""
        except Exception:
            if attempt < 2:
                time.sleep(2 ** attempt)
            else:
                raise
    return ""


def ensure_domain_dirs(domains_dir: Path, doc_types: list[str] | None = None) -> None:
    """Ensure domain root directories exist under domains_dir.

    Only creates domain-level dirs (for README.md and PROCESSES.md).
    """
    domains = get_domains()
    for domain_name in domains:
        (domains_dir / domain_name).mkdir(parents=True, exist_ok=True)
