#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
域自动发现模块。

从后端 Java 代码的 package 结构自动发现业务域，用 AI 做文档微调（合并/拆分/中文命名），
写入 domains/_meta/domains.json。

段发现停用词从 project_config.json 的 segment_stopwords 字段读取，项目级配置完全覆盖内置默认值。

用法：
  python -m tools.discover.discover_domains          # 自动发现
  python -m tools.discover.discover_domains --no-ai   # 不用 AI，英文域名
  python -m tools.discover.discover_domains --stats    # 查看当前 domains.json
"""
from __future__ import annotations

import json
import os
import re
import sys
import argparse
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

# ── Stopwords（从 project_config.json 读取）──────────────────────────────

def _load_stopwords() -> tuple[frozenset, frozenset, frozenset]:
    from ..config_loader import get_segment_stopwords
    return get_segment_stopwords()

_SEGMENT_STOPWORDS, _PACKAGE_WRAPPERS, _GENERIC_NOISE = _load_stopwords()

MIN_FILE_COUNT = 3  # segment 至少出现在这么多文件中


# ── Step 1: 后端代码扫描 ─────────────────────────────────────────────────────

def _is_valid_segment(seg: str) -> bool:
    s = seg.lower()
    if s in _SEGMENT_STOPWORDS or s in _PACKAGE_WRAPPERS or s in _GENERIC_NOISE:
        return False
    if "." in s or s.isdigit() or len(s) <= 2:
        return False
    return True


def _find_domain_segment(parts: list[str]) -> str | None:
    """从包路径片段中提取路径型 segment（如 order/payment）。

    遍历规则：
    - package_wrappers（rest, feign 等）：跳过，继续往后找
    - generic_noise（info, detail 等）：跳过，继续往后找
    - segment_stopwords（service, controller 等）：如果已有有效词则终止，否则跳过
    - 其他无效格式（长度 ≤ 2、纯数字等）：跳过
    - 有效业务词：收集
    """
    segments: list[str] = []
    for p in parts:
        low = p.lower()
        if low in _PACKAGE_WRAPPERS or low in _GENERIC_NOISE:
            continue
        if low in _SEGMENT_STOPWORDS:
            if segments:
                break  # 已有业务词后遇到技术层，终止
            continue
        if "." in low or low.isdigit() or len(low) <= 2:
            continue
        segments.append(low)
        if len(segments) >= 3:
            break
    return "/".join(segments) if segments else None


def _infer_segment_from_classname(stem: str) -> str | None:
    parts = re.findall(r"[A-Z][a-z]+|[A-Z]+(?=[A-Z]|$)|[a-z]+", stem)
    for part in reversed(parts):
        p = part.lower()
        if _is_valid_segment(p):
            return p
    return None


def _find_module_root(java_file: Path, repos_dir: Path) -> str | None:
    """从 Java 文件路径推断 Maven/Gradle 模块根目录（相对于 repos_dir）。

    找 src/main/java 的上级目录作为模块根。如果没有标准结构，取 repos_dir 下前两层。
    """
    rel = java_file.relative_to(repos_dir)
    parts = rel.parts
    for i, p in enumerate(parts):
        if p == "src" and i + 2 < len(parts) and parts[i + 1] == "main" and parts[i + 2] == "java":
            return "/".join(parts[:i])
    # 没有 src/main/java 结构，取前两层目录
    if len(parts) > 2:
        return "/".join(parts[:2])
    return None


def scan_java_domains(repos_dir: Path) -> dict[str, dict]:
    """
    扫描后端 Java 代码，提取域 segments。

    只扫描 *.java 文件（后端代码）。repos_dir 下可能同时存在前端代码（Vue/TS/JS），
    但域发现完全不使用前端代码——前端代码仅在图构建阶段作为节点纳入。

    Returns: {segment: {"file_count": N, "sample_files": [...], "module_dirs": [...]}}
    """
    segment_files: dict[str, int] = Counter()
    segment_samples: dict[str, list] = defaultdict(list)
    segment_modules: dict[str, set] = defaultdict(set)

    for java_file in repos_dir.rglob("*.java"):
        # 跳过测试代码
        path_str = str(java_file).replace("\\", "/")
        if "/test/" in path_str or "/tests/" in path_str:
            continue

        seg_found = None
        try:
            lines = java_file.read_text(encoding="utf-8", errors="ignore").split("\n")
            for line in lines[:20]:
                m = re.match(r"^package\s+([\w.]+)\s*;", line)
                if not m:
                    continue
                pkg = m.group(1)
                parts = pkg.split(".")

                # 找 application/app 后的第一个有意义 segment
                for i, p in enumerate(parts):
                    if p.lower() in ("application", "app", "apps") and i + 1 < len(parts):
                        seg = _find_domain_segment(parts[i + 1:])
                        if seg:
                            seg_found = seg
                        break

                # 没找到 application：扫描全部 parts
                if not seg_found:
                    seg_found = _find_domain_segment(parts)

                # 还没找到：从类名推断
                if not seg_found:
                    seg_found = _infer_segment_from_classname(java_file.stem)

                break
        except (OSError, UnicodeDecodeError):
            continue

        if seg_found:
            segment_files[seg_found] += 1
            if len(segment_samples[seg_found]) < 5:
                segment_samples[seg_found].append(path_str.split("/repos/")[-1] if "/repos/" in path_str else java_file.name)
            mod_root = _find_module_root(java_file, repos_dir)
            if mod_root:
                segment_modules[seg_found].add(mod_root)

    # 频率过滤
    result = {}
    for seg, count in segment_files.most_common():
        if count >= MIN_FILE_COUNT:
            result[seg] = {
                "file_count": count,
                "sample_files": segment_samples.get(seg, []),
                "module_dirs": sorted(segment_modules.get(seg, set())),
            }

    return result


def collect_dir_tree(repos_dir: Path, max_depth: int = 4) -> dict:
    """
    收集 repos 目录结构，返回每个目录的 Java 文件计数。

    返回: {相对路径: java_file_count}，只包含含有 Java 文件的目录。
    """
    tree: dict[str, int] = defaultdict(int)
    if not repos_dir.exists():
        return tree
    for jf in repos_dir.rglob("*.java"):
        path_str = str(jf).replace("\\", "/")
        if "/test/" in path_str or "/tests/" in path_str:
            continue
        try:
            rel = jf.parent.relative_to(repos_dir)
        except ValueError:
            continue
        # 记录从仓库根到文件所在目录的每一层
        parts = rel.parts
        for depth in range(1, min(len(parts), max_depth) + 1):
            dir_path = "/".join(parts[:depth])
            tree[dir_path] += 1
    return dict(sorted(tree.items()))


def generate_module_mapping_context(
    meta_dir: Path, repos_dir: Path,
    segments: dict, domains_data: dict,
) -> Path:
    """
    生成 module_mapping_context.md — 供 AI 编程工具完成 segment→模块目录 的映射。

    输出文件包含：目录树、域列表、待完成的任务说明。
    AI 编程工具（Claude Code / OpenClaw / Codex 等）读取此文件后，
    通过自主探索代码目录完成映射，将结果写回 domains.json。
    """
    dir_tree = collect_dir_tree(repos_dir)

    # 构建目录树文本（只保留叶子级或文件数 ≥ 3 的目录）
    tree_lines = []
    for path, count in dir_tree.items():
        indent = "  " * (path.count("/"))
        name = path.rsplit("/", 1)[-1] if "/" in path else path
        tree_lines.append(f"{indent}{name}/ ({count} java files)")

    # 构建域信息
    domain_lines = []
    for domain_name, info in domains_data.items():
        keys = ", ".join(info.get("english_keys", []))
        fc = info.get("file_count", 0)
        mods = info.get("modules", [])
        status = f"已映射: {', '.join(mods)}" if mods else "**待映射**"
        domain_lines.append(f"- **{domain_name}** (keys: {keys}, {fc} files) — {status}")

    # 统计待映射的域
    unmapped = [name for name, info in domains_data.items() if not info.get("modules")]

    content = f"""\
# 代码模块映射上下文

> 此文件由 `discover_domains.py` 自动生成，供 AI 编程工具完成域→代码模块的映射。
> 生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

## 代码仓库目录树

以下是 `source/repos/` 下的目录结构（含 Java 文件计数）：

```
{chr(10).join(tree_lines) or "(空)"}
```

## 域列表及映射状态

{chr(10).join(domain_lines) or "(无域)"}

## 待完成任务

共 {len(unmapped)} 个域的 modules 为空，需要通过探索代码目录来确定映射。

**目标**：为每个「待映射」的域，找出其业务代码所在的目录路径（相对于 `source/repos/`），
写入 `domains/_meta/domains.json` 对应域的 `modules` 字段。

**方法**：
1. 阅读上方目录树，初步判断每个域的代码可能在哪些目录下
2. 对不确定的目录，查看其中的 Java 文件名和包路径来确认
3. 一个域可能对应多个目录（微服务架构），也可能多个域共享同一个大目录的不同子包（单体架构）
4. `modules` 的值应该是目录路径列表，粒度选择能区分不同域的最细层级
   - 微服务项目：通常是服务模块目录名（如 `contract-atomic-service`）
   - 单体项目：通常是包路径中的业务子目录（如 `myapp/myapp-application/.../rest/contract`）

**约束**：
- 只修改 `domains.json` 中各域的 `modules` 字段
- 不要修改其他字段（english_keys、description 等）
- 如果确实找不到某个域的代码目录，保留 `modules: []`

## 参考：segment 采样文件

以下是每个 segment 的代表性文件路径，可辅助判断目录归属：

{chr(10).join(
    f"- **{seg}**: {', '.join(info.get('sample_files', []))}"
    for seg, info in sorted(segments.items(), key=lambda x: -x[1]['file_count'])
) or "(无)"}
"""

    out_path = meta_dir / "module_mapping_context.md"
    out_path.write_text(content, encoding="utf-8")
    return out_path


def _collect_tables_for_segment(repos_dir: Path, segment: str, modules: list[str]) -> list[str]:
    """收集与某 segment 相关的数据库表。"""
    tables = []
    for sql_file in repos_dir.rglob("*.sql"):
        content = sql_file.read_text(encoding="utf-8", errors="replace")
        found = re.findall(
            r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"]?(\w+)[`\"]?\s*\(",
            content, re.IGNORECASE,
        )
        for t in found:
            if segment in t.lower():
                tables.append(t)
    return sorted(set(tables))[:20]


def _collect_endpoints_for_segment(repos_dir: Path, segment: str, java_constants: dict[str, str] | None = None) -> list[str]:
    """收集与某 segment 相关的 REST 端点。支持常量引用和拼接。"""
    if java_constants is None:
        java_constants = {}
    endpoints = []
    for jf in repos_dir.rglob("*.java"):
        path_str = str(jf).replace("\\", "/")
        if f"/{segment}/" not in path_str.lower():
            continue
        try:
            content = jf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        # Extract class-level @RequestMapping (string literal or constant)
        class_prefix = ""
        class_rm_str = re.findall(r'@RequestMapping\s*\(\s*(?:value\s*=\s*)?["\']([^"\']+)["\']', content)
        if class_rm_str:
            class_prefix = class_rm_str[0]
        else:
            class_rm_const = re.findall(r'@RequestMapping\s*\(\s*(?:value\s*=\s*)?(\w+\.\w+)\s*\)', content)
            if class_rm_const:
                class_prefix = java_constants.get(class_rm_const[0], "")

        # Extract method-level mappings (string literal or constant)
        method_maps_str = re.findall(
            r'@(Get|Post|Put|Delete|Request)Mapping\s*\(\s*(?:value\s*=\s*)?["\']([^"\']+)["\']', content,
        )
        for method, path in method_maps_str:
            # 路径可能已经是完整路径（以 /api 开头），避免重复拼接
            if class_prefix and path.startswith("/api"):
                full = path
            elif class_prefix:
                full = (class_prefix + "/" + path).replace("//", "/")
            else:
                full = path
            endpoints.append(f"[{method.upper()}] {full}")

        method_maps_const = re.findall(
            r'@(Get|Post|Put|Delete|Request)Mapping\s*\(\s*(?:value\s*=\s*)?(\w+\.\w+)\s*\)', content,
        )
        for method, const_ref in method_maps_const:
            resolved = java_constants.get(const_ref, "")
            if not resolved:
                continue
            # 常量值可能已包含 class_prefix，避免重复拼接
            if class_prefix and resolved.startswith(class_prefix):
                full = resolved
            elif class_prefix:
                full = (class_prefix + "/" + resolved).replace("//", "/")
            else:
                full = resolved
            endpoints.append(f"[{method.upper()}] {full}")

        # Bare annotations (no path) with class prefix
        bare = re.findall(r'@(Get|Post|Put|Delete)Mapping\s*\(\s*\)', content)
        if bare and class_prefix:
            endpoints.append(f"[REQUEST] {class_prefix}")

    return list(dict.fromkeys(endpoints))[:20]


# ── Step 2: 文档标题关键词 ───────────────────────────────────────────────────

def scan_doc_titles(docs_dir: Path) -> list[str]:
    """扫描 source/docs/ 的文档标题，返回标题列表。"""
    titles = []
    if not docs_dir.exists():
        return titles
    for md in sorted(docs_dir.rglob("*.md")):
        name = re.sub(r"^\d+_", "", md.stem)  # 去掉 PageID 前缀
        if name and len(name) > 2:
            titles.append(name)
    return titles


# ── Step 3: AI 微调 ──────────────────────────────────────────────────────────

_AI_PROMPT = """\
你是一个业务系统的领域架构分析师。根据以下从后端 Java 代码自动提取的业务域信息，完成域的中文命名和合理整合。

## 代码提取的域 segments（按文件数排序）

{segments_text}

## 文档标题样本（如有）

{doc_titles_text}

## 任务

1. 为每个 segment 给出中文域名（2-4个字，如"合同管理"、"客户管理"）
2. 如果多个 segments 实质上是同一业务域的不同方面，合并它们为一个域
3. 如果某个 segment 的文件数远超其他（如 >100），考虑是否需要拆分子域
4. 域名要体现业务含义，不要用技术术语
5. **硬性约束：每一层级的域数量不得超过 12 个。** 如果某层级候选域超过 12 个：
   - 优先合并业务相近的 segments 为同一域
   - 如果合并后仍超过 12 个，使用层级结构：将相关域组织为父域/子域
   - 层级最多 4 层（支持多级嵌套），每个父域下子域不超过 12 个
   - 无论如何，**顶层 domains 数组的长度不得超过 12**

## 输出格式（严格 JSON）

```json
{{
  "domains": [
    {{
      "chinese_name": "合同管理",
      "english_keys": ["contract", "archive", "renewal"],
      "description": "一句话描述",
      "children": []
    }},
    {{
      "chinese_name": "物流订单",
      "english_keys": ["order"],
      "description": "物流订单总域",
      "children": [
        {{
          "chinese_name": "订舱管理",
          "english_keys": ["booking"],
          "description": "一句话描述"
        }}
      ]
    }}
  ]
}}
```

说明：
- `children` 字段可选。如果不需要层级结构（顶层≤10个），所有域的 children 为空数组或省略
- 如果需要层级结构，父域的 children 列出子域，子域也可以有自己的 children（最多 4 层）
- 每一层级的域数量都不得超过 12
- **顶层 domains 数组长度必须 ≤ 12**

只输出 JSON，不要其他内容。"""


def ai_refine_domains(
    segments: dict[str, dict],
    doc_titles: list[str],
) -> list[dict]:
    """用 AI 单次调用，将英文 segments 转为中文域名并做合并/拆分。"""
    from ..config_loader import call_llm

    # 构建 segments 描述
    lines = []
    for seg, info in sorted(segments.items(), key=lambda x: -x[1]["file_count"]):
        samples_str = ", ".join(info.get("sample_files", [])[:3]) or "无"
        lines.append(f"- **{seg}**（{info['file_count']} 文件，样本: {samples_str}）")
    segments_text = "\n".join(lines) if lines else "（无代码域信息）"

    # 构建文档标题样本（最多50个）
    sample = doc_titles[:50]
    doc_titles_text = "\n".join(f"- {t}" for t in sample) if sample else "（无文档）"

    prompt = _AI_PROMPT.format(
        segments_text=segments_text,
        doc_titles_text=doc_titles_text,
    )

    text = call_llm(prompt, max_tokens=16384)
    if not text:
        raise ValueError("AI 返回空内容")

    # 提取 JSON
    m = re.search(r"```json\s*\n(.*?)\n\s*```", text, re.DOTALL)
    if m:
        text = m.group(1)
    # 兜底：直接尝试解析
    data = json.loads(text)
    return data.get("domains", [])


def fallback_domains(segments: dict[str, dict]) -> list[dict]:
    """无 AI 时退化：英文 segment 直接作为域名，最多 12 个。"""
    sorted_segs = sorted(segments.items(), key=lambda x: -x[1]["file_count"])
    if len(sorted_segs) <= 12:
        return [
            {
                "chinese_name": seg,
                "english_keys": [seg],
                "description": f"{info['file_count']} files",
            }
            for seg, info in sorted_segs
        ]
    # 超过 12 个：取前 11 个，其余合入"其他"域
    result = []
    for seg, info in sorted_segs[:11]:
        result.append({
            "chinese_name": seg,
            "english_keys": [seg],
            "description": f"{info['file_count']} files",
        })
    other_keys = [seg for seg, _ in sorted_segs[11:]]
    other_files = sum(info["file_count"] for _, info in sorted_segs[11:])
    result.append({
        "chinese_name": "其他",
        "english_keys": other_keys,
        "description": f"合并 {len(other_keys)} 个小域，共 {other_files} files",
    })
    return result


# ── 目录重命名 ─────────────────────────────────────────────────────────────

def _rename_domain_dirs(kb_out: Path, old_data: dict, new_data: dict) -> None:
    """
    根据新旧 domains.json 的变化，重命名 knowledgeBase 下的域目录。

    策略：
    1. 从旧 english_to_chinese 和新 english_to_chinese 建立 旧目录名→新目录名 映射
    2. 如果旧目录名是英文 key，新目录名是中文名 → 重命名
    3. 如果旧目录名已经是中文名且映射变了 → 也重命名
    4. _meta、_state 等下划线开头的目录不动
    """
    import shutil

    old_e2c = old_data.get("english_to_chinese", {})
    old_domain_list = set(old_data.get("domain_list", []))
    new_e2c = new_data.get("english_to_chinese", {})
    new_domain_list = set(new_data.get("domain_list", []))

    # 建立 旧目录名→新目录名 的映射
    rename_map: dict[str, str] = {}

    # Case 1: 旧目录是英文 key（如 "contract"），新映射是中文名（如 "合同管理"）
    for eng_key, new_chinese in new_e2c.items():
        old_dir = kb_out / eng_key
        if old_dir.exists() and old_dir.is_dir():
            if eng_key != new_chinese:  # 英文→中文
                rename_map[eng_key] = new_chinese

    # Case 2: 旧目录是旧中文名（旧域列表里有），新域列表里没有了但 english_keys 映射到新名
    for old_domain in old_domain_list:
        old_dir = kb_out / old_domain
        if not old_dir.exists() or not old_dir.is_dir():
            continue
        if old_domain in new_domain_list:
            continue  # 名字没变，不用动
        # 找旧域的 english_keys，看新映射指向哪
        old_info = old_data.get("domains", {}).get(old_domain, {})
        old_keys = old_info.get("english_keys", [])
        for key in old_keys:
            if key in new_e2c and new_e2c[key] != old_domain:
                rename_map[old_domain] = new_e2c[key]
                break

    if not rename_map:
        return

    renamed = 0
    for old_name, new_name in rename_map.items():
        old_dir = kb_out / old_name
        new_dir = kb_out / new_name
        if not old_dir.exists():
            continue

        if new_dir.exists():
            # 目标已存在：把旧目录内容合并过去
            for item in old_dir.iterdir():
                target = new_dir / item.name
                if item.is_dir():
                    if target.exists():
                        # 子目录也合并
                        for sub in item.iterdir():
                            shutil.move(str(sub), str(target / sub.name))
                        item.rmdir()
                    else:
                        shutil.move(str(item), str(target))
                else:
                    shutil.move(str(item), str(target))
            # 删除空的旧目录
            try:
                old_dir.rmdir()
            except OSError:
                pass
            print(f"  域目录合并: {old_name} → {new_name}")
        else:
            old_dir.rename(new_dir)
            print(f"  域目录重命名: {old_name} → {new_name}")
        renamed += 1

    if renamed:
        print(f"发现域: 重命名了 {renamed} 个域目录")


# ── 主函数 ───────────────────────────────────────────────────────────────────

def discover(kb_dir: Path, use_ai: bool = True) -> dict:
    """
    自动发现域。

    1. 扫描后端 Java 代码 → 英文 segments
    2. AI 微调（或退化为英文直接用）
    3. 写入 domains/_meta/domains.json
    """
    repos_dir = kb_dir / "source" / "repos"
    docs_dir = kb_dir / "source" / "docs"
    domains_out = kb_dir / "domains"
    meta_dir = domains_out / "_meta"
    meta_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: 扫描后端代码
    print("发现域: 扫描后端 Java 代码...")
    segments = scan_java_domains(repos_dir)
    if not segments:
        print("  警告: 未从代码中发现任何域 segment，将使用默认域 'uncategorized'")
        segments = {"uncategorized": {"file_count": 0, "sample_files": []}}

    # 解析 Java 常量（用于端点路径的常量引用）
    from ..extract_kb.enrich_kb import resolve_java_endpoint_constants
    java_constants = resolve_java_endpoint_constants(repos_dir)

    print(f"  发现 {len(segments)} 个候选域: {', '.join(segments.keys())}")

    # Step 2: AI 微调 or 退化
    ai_domains = None
    if use_ai:
        try:
            from .. import config_loader as cfg
            llm_cfg = cfg._resolve_llm_config()
            api_key = llm_cfg.get("api_key", "")
            if api_key:
                print("发现域: AI 微调中（中文命名 + 合并/拆分）...")
                doc_titles = scan_doc_titles(docs_dir)
                ai_domains = ai_refine_domains(segments, doc_titles)
                print(f"  AI 输出 {len(ai_domains)} 个域")
            else:
                print("  ⚠ 无 API key，跳过 AI 微调")
        except Exception as e:
            print(f"  ⚠ AI 微调失败 ({e})，使用退化模式")

    translated = ai_domains is not None
    if not translated:
        ai_domains = fallback_domains(segments)
        print("  ⚠ 警告：域名使用英文（AI 翻译未生效）。可稍后单独重跑: ewankb discover")

    # Step 3: 构建 domains.json（支持层级域）
    english_to_chinese = {}
    domains_data = {}

    def _collect_segment_info(keys: list[str]) -> dict:
        """收集一组 english_keys 对应的文件数/表/端点/模块目录。"""
        total_files = 0
        all_tables: list = []
        all_endpoints: list = []
        all_modules: list = []
        for key in keys:
            if key in segments:
                total_files += segments[key]["file_count"]
                tables = _collect_tables_for_segment(repos_dir, key, [])
                endpoints = _collect_endpoints_for_segment(repos_dir, key, java_constants)
                all_tables.extend(tables)
                all_endpoints.extend(endpoints)
                all_modules.extend(segments[key].get("module_dirs", []))
        return {
            "file_count": total_files,
            "modules": sorted(set(all_modules)),
            "tables": sorted(set(all_tables))[:30],
            "endpoints": list(dict.fromkeys(all_endpoints))[:30],
        }

    def _process_domain(d: dict, parent_path: str = "") -> None:
        """递归处理域（支持最多 4 层嵌套）。"""
        name = d["chinese_name"]
        keys = d.get("english_keys", [])
        desc = d.get("description", "")
        children = d.get("children", [])

        full_path = f"{parent_path}/{name}" if parent_path else name

        for key in keys:
            english_to_chinese[key] = full_path

        info = _collect_segment_info(keys)

        if children:
            domains_data[full_path] = {
                "english_keys": keys,
                "description": desc,
                "modules": info["modules"],
                "tables": info["tables"],
                "endpoints": info["endpoints"],
                "doc_keywords": keys,
                "file_count": info["file_count"],
                "is_parent": True,
                "children": [c["chinese_name"] for c in children],
            }
            for child in children:
                _process_domain(child, parent_path=full_path)
        else:
            entry = {
                "english_keys": keys,
                "description": desc,
                "modules": info["modules"],
                "tables": info["tables"],
                "endpoints": info["endpoints"],
                "doc_keywords": keys,
                "file_count": info["file_count"],
            }
            if parent_path:
                entry["parent"] = parent_path
            domains_data[full_path] = entry

    for d in ai_domains:
        _process_domain(d)

    # 写入前，读旧 domains.json 用于目录重命名
    domains_file = meta_dir / "domains.json"
    old_data = {}
    if domains_file.exists():
        try:
            with open(domains_file, encoding="utf-8") as f:
                old_data = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    result = {
        "domains": domains_data,
        "domain_list": list(domains_data.keys()),
        "english_to_chinese": english_to_chinese,
        "translated": translated,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    # 写入
    with open(domains_file, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"发现域: 写入 {domains_file}")
    print(f"  域列表: {', '.join(result['domain_list'])}")

    # Step 4: 生成模块映射上下文文件（供 AI 编程工具完成 modules 映射）
    ctx_path = generate_module_mapping_context(meta_dir, repos_dir, segments, domains_data)
    unmapped_count = sum(1 for info in domains_data.values() if not info.get("modules"))
    if unmapped_count:
        print(f"发现域: {unmapped_count} 个域的 modules 待映射 → {ctx_path}")

    # Step 5: 重命名 domains 下的域目录
    _rename_domain_dirs(domains_out, old_data, result)

    return result


def load_domains(kb_dir: Path) -> dict:
    """从 domains/_meta/domains.json 加载域。回退到旧路径 knowledgeBase/_meta/。"""
    domains_file = kb_dir / "domains" / "_meta" / "domains.json"
    if not domains_file.exists():
        # Backward compat: old location
        domains_file = kb_dir / "knowledgeBase" / "_meta" / "domains.json"
    if not domains_file.exists():
        return {"domains": {}, "domain_list": [], "english_to_chinese": {}}
    with open(domains_file, encoding="utf-8") as f:
        return json.load(f)


def print_stats(kb_dir: Path):
    data = load_domains(kb_dir)
    if not data["domain_list"]:
        print("尚未发现域。运行 ewankb build 自动发现。")
        return
    print(f"域总数: {len(data['domain_list'])}")
    print(f"生成时间: {data.get('generated_at', '未知')}")
    print()
    for name, info in data["domains"].items():
        keys = ", ".join(info.get("english_keys", []))
        fc = info.get("file_count", 0)
        mc = len(info.get("modules", []))
        tc = len(info.get("tables", []))
        ec = len(info.get("endpoints", []))
        print(f"  {name} ({keys}): {fc} 文件, {mc} 模块, {tc} 表, {ec} 端点")


# ── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="域自动发现")
    parser.add_argument("--no-ai", action="store_true", help="不使用 AI，英文域名")
    parser.add_argument("--stats", action="store_true", help="查看当前 domains.json")
    args = parser.parse_args()

    from .. import config_loader as cfg
    kb_dir = cfg.get_kb_dir()

    if args.stats:
        print_stats(kb_dir)
    else:
        discover(kb_dir, use_ai=not args.no_ai)
