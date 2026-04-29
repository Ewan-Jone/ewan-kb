#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
领域概览生成脚本 v3 — 支持层级业务域

为每个业务域生成 README.md，对标 UAP 知识库质量，包含：
  - 业务定位 & 领域关联（AI 生成）
  - 后端代码：精确到 Rest/Service 文件路径
  - 数据库表结构：表名 + 核心字段（从 SQL DDL 解析）
  - 已知问题：汇总各文档中的「实现备注」
  - 文档索引：按类型列出所有文档

层级域支持：
  - 父域 README 记录跨子域协调流程
  - 子域 README 记录该子域完整信息
  - 层级路径如 '物流订单/订舱管理' 正确解析为嵌套目录

用法：
  python gen_domain_overview.py                    # 全部域（跳过已存在）
  python gen_domain_overview.py --domain 物流订单  # 父域（含所有子域）
  python gen_domain_overview.py --domain 物流订单/订舱管理  # 单个子域
  python gen_domain_overview.py --force            # 强制重新生成
  python gen_domain_overview.py --init-dirs        # 仅初始化域目录
"""
import os, sys, re, json, argparse
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from .. import config_loader as cfg
from ..config_loader import call_llm
from ..text_utils import parse_frontmatter

# ── 路径配置（从配置文件加载）─────────────────────────────────────────────────

BASE_DIR    = cfg.get_kb_dir()
DOMAINS_DIR = cfg.get_domains_dir()
REPOS       = cfg.get_repos_dir()
SCHEMA_IDX  = cfg.get_schema_index_path()
TODAY       = datetime.now().strftime("%Y-%m-%d")

_SYSTEM_NAME = cfg.get_project_config().get("system_name", "业务系统")

# ── 域映射（从配置文件加载）──────────────────────────────────────────────────

DOMAIN_TO_MODULES   = cfg.get_domain_to_modules()
SKIP_DOMAINS        = cfg.get_skip_domains()

DOC_TYPE_ORDER = cfg.STANDARD_DOC_TYPES

# ── Prompt ────────────────────────────────────────────────────────────────────

_all_domains_str = "、".join(d for d in cfg.get_domains() if d not in SKIP_DOMAINS and d != "待分类")

OVERVIEW_PROMPT = f"""\
你是{_SYSTEM_NAME}知识库整理助手。请根据以下信息，为业务域「{{domain}}」生成领域概览的核心内容。

## 代码模块说明（来自业务文档中的代码模块文件）
{{code_module_summary}}

## 该域下的文档标题列表
{{doc_titles}}

## 所有业务域列表（供关联分析）
{_all_domains_str}

## 任务
只输出以下两个部分，不要输出其他内容：

### 业务定位
用 3-5 句话描述该域的核心业务职责：这个域管理什么、解决什么问题、核心用户是谁。

### 领域关联
列出与本域有直接业务关联的其他域，按上游/下游/双向分类：
- **上游**（向本域输入数据/触发本域流程的域）：域名 — 关联说明
- **下游**（本域完成后触发/输出到的域）：域名 — 关联说明
- **双向**（互相调用或共享数据的域，可选）：域名 — 关联说明

若某类为空则写"无"。只列举实质性的业务关联，不要列所有域。
"""

# ── 工具函数 ─────────────────────────────────────────────────────────────────

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def get_doc_title(fpath: Path) -> str:
    try:
        text = fpath.read_text(encoding="utf-8", errors="replace")[:400]
        return parse_frontmatter(text).get("title", fpath.stem)
    except Exception:
        return fpath.stem

# ── 数据库表结构（从 schema_index.json 读取）─────────────────────────────────

_schema_index: dict | None = None

def load_schema_index() -> dict:
    global _schema_index
    if _schema_index is None:
        if SCHEMA_IDX.exists():
            _schema_index = json.loads(SCHEMA_IDX.read_text(encoding="utf-8"))
        else:
            _schema_index = {}
    return _schema_index

def get_domain_tables(domain: str) -> list[dict]:
    """
    从 domains.json 中取该域相关的数据库表名列表。
    返回: [{name, comment, fields: [{name, type, comment}]}]
    """
    domains_data = cfg._load_domains_json()
    domain_info = domains_data.get("domains", {}).get(domain, {})
    table_names = domain_info.get("tables", [])
    if not table_names:
        return []

    # 如果 schema_index 存在，尝试用它补充字段信息
    idx = load_schema_index()
    tables = []
    for tbl_name in table_names:
        info = idx.get(tbl_name, {})
        tables.append({
            "name":    tbl_name,
            "comment": info.get("comment", ""),
            "fields":  info.get("columns", [])[:20],
        })
    return tables


# ── 核心代码文件提取 ──────────────────────────────────────────────────────────

def get_top_code_files(domain: str) -> dict:
    """返回 {rest: [(file_str, descs), ...], service: [file_str, ...]}

    modules 来自 domains.json，是模块目录名列表。
    优先使用细粒度路径（含 rest/feign 等子目录），
    粗粒度路径回退时按域的 english_keys 过滤。
    """
    modules = DOMAIN_TO_MODULES.get(domain, [])
    rest_files = []
    service_files = []

    source_repos = cfg.get_source_dir() / "repos"
    if not source_repos.exists():
        return {"rest": [], "service": []}

    # 获取域的英文关键词用于过滤
    domains_data = cfg._load_domains_json()
    domain_info = domains_data.get("domains", {}).get(domain, {})
    # 层级域：先查自己，再查父域
    if not domain_info and "/" in domain:
        parent = domain.rsplit("/", 1)[0]
        domain_info = domains_data.get("domains", {}).get(parent, {})
    english_keys = [k.lower() for k in domain_info.get("english_keys", [])]

    # 区分细粒度和粗粒度模块
    fine_modules = [m for m in modules if "/rest/" in m or "/feign/" in m or "/service/" in m]
    coarse_modules = [m for m in modules if m not in fine_modules]

    # 优先使用细粒度模块
    search_modules = fine_modules if fine_modules else coarse_modules

    for module_name in search_modules:
        for mod_dir in source_repos.rglob(module_name):
            if not mod_dir.is_dir():
                continue
            for jf in mod_dir.rglob("*.java"):
                if "Test" in jf.stem or "test" in str(jf):
                    continue
                stem = jf.stem
                rel = str(jf.relative_to(source_repos)).replace("\\", "/")

                # 粗粒度模块且有关键词时，按关键词过滤
                if module_name in coarse_modules and english_keys:
                    rel_lower = rel.lower()
                    if not any(k in rel_lower for k in english_keys):
                        continue

                if re.search(r'(Rest|Controller)$', stem):
                    try:
                        content = jf.read_text(encoding="utf-8", errors="replace")
                        descs = re.findall(r'@Desc\s*\(\s*["\']([^"\']+)["\']', content)
                        rest_files.append((rel, descs[:2]))
                    except Exception:
                        rest_files.append((rel, []))
                elif re.search(r'Service$', stem) and not re.search(r'(Feign|Client|Fallback)', stem):
                    service_files.append(rel)
            break  # 找到该模块目录即可

    return {
        "rest": rest_files[:10],
        "service": service_files[:10],
    }

# ── 已知问题提取 ───────────────────────────────────────────────────────────────

def collect_known_issues(domain: str) -> list[str]:
    """扫描 domains/{域名}/{doc_type}/ 下文档的「实现备注」章节，汇总已知问题"""
    issues = []
    domain_dir = DOMAINS_DIR / domain
    if not domain_dir.exists():
        return issues
    for dtype_dir in domain_dir.iterdir():
        if not dtype_dir.is_dir() or dtype_dir.name.startswith("_"):
            continue
        for f in dtype_dir.glob("*.md"):
            if f.name == "README.md":
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            fm = parse_frontmatter(text[:400])
            m = re.search(r'###\s*实现备注\s*\n(.*?)(?=\n###|\Z)', text, re.DOTALL)
            if not m:
                continue
            body = m.group(1).strip()
            if len(body) < 10:
                continue
            title = fm.get("title", f.stem)
            snippet = body[:200].replace("\n", " ").strip()
            issues.append(f"- ⚠️ **[{title}]**: {snippet}")
    return issues[:10]

# ── 文档索引构建 ───────────────────────────────────────────────────────────────

def build_doc_index(domain: str) -> dict:
    """Build doc index for a domain by scanning domains/{域名}/{doc_type}/ directory."""
    index = {t: [] for t in DOC_TYPE_ORDER}
    domain_dir = DOMAINS_DIR / domain
    if not domain_dir.exists():
        return index
    for dtype_dir in sorted(domain_dir.iterdir()):
        if not dtype_dir.is_dir() or dtype_dir.name.startswith("_"):
            continue
        dtype = dtype_dir.name
        if dtype not in index:
            index[dtype] = []
        for f in sorted(dtype_dir.glob("*.md")):
            if f.name == "README.md":
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="replace")[:400]
            except Exception:
                continue
            fm = parse_frontmatter(text)
            title = fm.get("title", f.stem)
            # Relative path from domain dir (e.g. "需求文档/xxx.md")
            rel = f.relative_to(domain_dir)
            index[dtype].append((title, str(rel).replace("\\", "/")))
    return index

# ── README 生成 ────────────────────────────────────────────────────────────────

def _domain_has_content(domain: str, all_domains_list: list[str] | None = None, pruned_dirs: set[str] | None = None) -> bool:
    """检查域是否有实际内容（modules 非空 OR 域目录下有由 extract 产生的文档文件）

    不计入以下内容：
    - README.md / PROCESSES.md（生成产物）
    - 代码模块说明/（生成产物）
    - 子域目录（它们不是 doc_type 子目录）
    - 已被标记裁剪的子域目录
    """
    modules = DOMAIN_TO_MODULES.get(domain, [])
    if modules:
        return True
    domain_dir = DOMAINS_DIR / domain
    if not domain_dir.exists():
        return False

    # 获取所有已知的子域路径的直接子目录名
    if all_domains_list is None:
        all_domains_list = cfg.get_domains()
    prefix = domain + "/"
    child_dir_names = {d[len(prefix):].split("/")[0] for d in all_domains_list if d.startswith(prefix)}

    # 已裁剪的子域目录名也要排除
    if pruned_dirs:
        for pd in pruned_dirs:
            if pd.startswith(prefix):
                child_dir_names.add(pd[len(prefix):].split("/")[0])

    # 检查域目录下是否有真正的 doc_type 子目录中的 .md 文件
    for sub in domain_dir.iterdir():
        if not sub.is_dir():
            continue
        if sub.name.startswith("_") or sub.name == "代码模块说明":
            continue
        # 跳过子域目录
        if sub.name in child_dir_names:
            continue
        if any(sub.glob("*.md")):
            return True
    return False


def prune_empty_domains() -> list[str]:
    """裁剪空域：从 domains.json 中删除无代码无文档的幽灵域，同时删除其目录。

    先裁子域，再裁父域（子域全删后父域也可能变空）。
    Returns: 被删除的域名列表
    """
    import shutil

    domains_file = DOMAINS_DIR / "_meta" / "domains.json"
    if not domains_file.exists():
        return []

    data = json.loads(domains_file.read_text(encoding="utf-8"))
    all_domains = data.get("domains", {})
    domain_list = data.get("domain_list", [])

    # 维护一个实时的域列表和已裁剪集合
    live_domain_list = list(domain_list)
    pruned_set = set()

    # 按层级深度排序：先处理子域（深度大的），再处理父域
    sorted_domains = sorted(list(all_domains.keys()), key=lambda d: d.count("/"), reverse=True)

    pruned = []
    for domain in sorted_domains:
        if not _domain_has_content(domain, live_domain_list, pruned_set):
            pruned.append(domain)
            pruned_set.add(domain)
            # 立即从 dict 和 live list 中移除
            all_domains.pop(domain, None)
            live_domain_list = [d for d in live_domain_list if d != domain]

    if not pruned:
        return []

    # 更新 domain_list
    data["domain_list"] = live_domain_list

    # 写回 domains.json
    domains_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # 删除空域目录（从子域到父域的顺序删除）
    for domain in pruned:
        domain_dir = DOMAINS_DIR / domain
        if domain_dir.exists():
            shutil.rmtree(domain_dir)

    log(f"裁剪 {len(pruned)} 个空域: {', '.join(pruned)}")
    return pruned


def gen_domain_readme(domain: str, frontend_idx: dict | None = None) -> None:
    if frontend_idx is None:
        frontend_idx = {}
    # domain 是域路径字符串，如 "合同管理" 或 "物流订单/订舱管理"
    domain_dir = DOMAINS_DIR / domain

    # 1. 读取代码模块说明（从 domains/{域名}/代码模块说明/ 目录）
    code_summaries = []
    code_mod_dir = domain_dir / "代码模块说明"
    if code_mod_dir.exists():
        for f in sorted(code_mod_dir.glob("*.md")):
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
                body = re.sub(r'^---\n.*?\n---\n', '', text, count=1, flags=re.DOTALL).strip()
                code_summaries.append(f"**{f.stem}**\n{body[:1500]}")
            except Exception:
                pass

    # 2. 收集文档标题
    doc_index = build_doc_index(domain)
    doc_titles_lines = []
    all_docs_count = 0
    for dtype in DOC_TYPE_ORDER:
        items = doc_index.get(dtype, [])
        if not items:
            continue
        doc_titles_lines.append(f"[{dtype}]")
        for title, _ in items[:20]:
            doc_titles_lines.append(f"  - {title}")
        if len(items) > 20:
            doc_titles_lines.append(f"  ...共{len(items)}个")
        all_docs_count += len(items)

    # 3. AI 生成业务定位 + 领域关联
    prompt = OVERVIEW_PROMPT.format(
        domain=domain,
        code_module_summary="\n\n".join(code_summaries)[:3000] or "（无代码模块说明）",
        doc_titles="\n".join(doc_titles_lines)[:1500] or "（无文档）",
    )
    ai_content = call_llm(prompt, max_tokens=3000).strip()
    ai_content = re.sub(r'^#\s+.+\n', '', ai_content).lstrip()

    # 4. 后端代码模块
    modules = DOMAIN_TO_MODULES.get(domain, [])
    module_dirs_md = [f"- `{mod}`" for mod in modules]

    code_files = get_top_code_files(domain)
    rest_md = []
    for rel, descs in code_files["rest"]:
        desc_str = f" — {descs[0]}" if descs else ""
        rest_md.append(f"  - `{rel}`{desc_str}")
    service_md = [f"  - `{rel}`" for rel in code_files["service"]]

    # 5. SQL 表结构（从 schema_index.json 读取）
    tables = get_domain_tables(domain)
    table_md = []
    for tbl in tables:
        comment = f" — {tbl['comment']}" if tbl['comment'] else ""
        table_md.append(f"\n#### `{tbl['name']}`{comment}")
        if tbl['fields']:
            table_md.append("| 字段 | 类型 | 说明 |")
            table_md.append("|------|------|------|")
            for fld in tbl['fields']:
                table_md.append(f"| `{fld['name']}` | {fld['type']} | {fld['comment']} |")

    # 6. 已知问题
    issues = collect_known_issues(domain)

    # 8. 文档索引（路径相对于 domains/{域名}/README.md → {doc_type}/{file}.md）
    doc_index_md = []
    for dtype in DOC_TYPE_ORDER:
        items = doc_index.get(dtype, [])
        if not items:
            continue
        doc_index_md.append(f"\n### {dtype}（{len(items)}）\n")
        for title, rel_path in items:
            doc_index_md.append(f"- [{title}]({rel_path})\n")

    # ── 组装 README ────────────────────────────────────────────────────────────
    sections = []
    # domain 可能是层级路径，标题只取最后一节
    domain_title = domain.rsplit("/", 1)[-1]
    sections.append(f"""---
type: 领域概览
domain: {domain}
updated: {TODAY}
---

# {domain_title}

{ai_content}

---
""")

    sections.append("## 后端代码模块\n")
    sections.append("**模块目录**\n")
    sections.append("\n".join(module_dirs_md) or "- 无")
    sections.append("\n")

    if rest_md:
        sections.append("\n**核心接口文件（Rest/Controller）**\n")
        sections.append("\n".join(rest_md))
        sections.append("\n")

    if service_md:
        sections.append("\n**核心服务文件（Service）**\n")
        sections.append("\n".join(service_md))
        sections.append("\n")

    # 前端代码模块
    fe_entries = frontend_idx.get(domain, [])
    if fe_entries:
        sections.append("\n## 前端代码模块\n")
        for e in fe_entries:
            api_str = ", ".join(e.get("api_paths", [])[:3])
            sections.append(f"- `{e['file_str']}` — API: {api_str}\n")

    if table_md:
        sections.append("\n## 数据库表结构\n")
        sections.append("\n".join(table_md))
        sections.append("\n")

    if issues:
        sections.append("\n## 已知问题 / 实现差异\n")
        sections.append("\n".join(issues))
        sections.append("\n")

    sections.append(f"\n---\n\n## 文档索引\n\n共 {all_docs_count} 个文档。\n")
    sections.append("".join(doc_index_md))

    readme = "\n".join(sections)
    domain_dir.mkdir(parents=True, exist_ok=True)
    out = domain_dir / "README.md"
    out.write_text(readme, encoding="utf-8")
    # domain 可能是层级路径如 "物流订单/订舱管理"
    display_name = domain.replace("/", " / ")
    log(f"  -> {display_name}/README.md  ({len(tables)}表 {len(rest_md)}Rest {len(issues)}已知问题 {all_docs_count}文档)")


# ── 主流程 ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="生成领域概览 README v3")
    parser.add_argument("--domain", help="只处理指定域（支持子域路径，如 物流订单/订舱管理）")
    parser.add_argument("--force",  action="store_true", help="强制重新生成")
    parser.add_argument("--init-dirs", action="store_true", help="仅初始化层级域目录")
    args = parser.parse_args()

    if args.init_dirs:
        cfg.ensure_domain_dirs(DOMAINS_DIR)
        log("层级域目录初始化完成")
        return

    if args.domain:
        domain_dir = DOMAINS_DIR / args.domain
        if not domain_dir.exists():
            domain_dir.mkdir(parents=True, exist_ok=True)
        log(f"生成: {args.domain}")
        try:
            # 单域模式也需要前端索引
            from .enrich_kb import (
                resolve_java_endpoint_constants,
                resolve_frontend_constants,
                build_code_index,
                build_frontend_index,
            )
            java_constants = resolve_java_endpoint_constants(REPOS)
            fe_constants = resolve_frontend_constants(REPOS)
            code_idx_for_fe, _, ep_idx_for_fe = build_code_index(java_constants)
            frontend_idx = build_frontend_index(REPOS, code_idx_for_fe, ep_idx_for_fe, fe_constants)
            gen_domain_readme(args.domain, frontend_idx)
        except Exception as e:
            log(f"  [失败] {args.domain}: {e}")
        return

    # 裁剪空域（无代码无文档的幽灵域直接删除）
    prune_empty_domains()

    # 构建前端→域关联索引
    from .enrich_kb import (
        resolve_java_endpoint_constants,
        resolve_frontend_constants,
        build_code_index,
        build_frontend_index,
    )
    java_constants = resolve_java_endpoint_constants(REPOS)
    fe_constants = resolve_frontend_constants(REPOS)
    code_idx_for_fe, _, ep_idx_for_fe = build_code_index(java_constants)
    frontend_idx = build_frontend_index(REPOS, code_idx_for_fe, ep_idx_for_fe, fe_constants)

    # 扫描所有域（从 domains.json 获取，不依赖目录遍历）
    all_domains = cfg.get_domains()
    target_domains = [d for d in all_domains if d not in SKIP_DOMAINS and d != "待分类"]

    log(f"共 {len(target_domains)} 个域待处理")
    for i, domain in enumerate(target_domains, 1):
        domain_dir = DOMAINS_DIR / domain
        readme_path = domain_dir / "README.md"
        if readme_path.exists() and not args.force:
            log(f"  [{i}/{len(target_domains)}] 跳过(已存在): {domain}")
            continue
        log(f"  [{i}/{len(target_domains)}] 生成: {domain}")
        try:
            gen_domain_readme(domain, frontend_idx)
        except Exception as e:
            log(f"    [失败] {domain}: {e}")

    log("=== 完成 ===")


if __name__ == "__main__":
    log(f"===== 启动 {TODAY} =====")
    main()
