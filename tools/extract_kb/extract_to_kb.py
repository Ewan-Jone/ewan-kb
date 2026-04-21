#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
知识库内容提炼脚本
从 confluence_data 中读取文档，用 Claude API 提炼后写入 knowledgeBase 目录

特性：
  - 断点续传：progress.json 记录每个文件的处理状态，重跑自动跳过已完成
  - 重试机制：API 失败最多重试 3 次，指数退避
  - 错误隔离：单文件失败写入 errors.json，不中断全局
  - 可重复运行：已完成文件直接跳过

用法：
  python extract_to_kb.py              # 处理全部待处理文件
  python extract_to_kb.py --retry      # 只重试之前失败的文件
  python extract_to_kb.py --stats      # 只看进度统计，不运行
"""

import os
import sys
import json
import time
import re
import argparse
import threading
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import anthropic

# ============================================================
# 配置加载（从新架构的 config_loader.py 读取）
# ============================================================
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools import config_loader as cfg

BASE_DIR       = cfg.get_kb_dir()
SOURCE_DIR     = cfg.get_source_dir()
DOMAINS_DIR    = cfg.get_domains_dir()
KNOWLEDGE_BASE = cfg.get_knowledge_base_dir()
PROGRESS_FILE  = cfg.get_knowledge_base_dir() / "_state/progress.json"
ERRORS_FILE    = cfg.get_knowledge_base_dir() / "_state/errors.json"
LOG_FILE       = cfg.get_knowledge_base_dir() / "_state/extract.log"

# NOTE: _AUTH_TOKEN and _BASE_URL are evaluated lazily at runtime,
# not at module import time, to support subprocess invocation via ewankb CLI.
# Use the getter functions below instead of the module-level vars directly.

MAX_RETRIES = 3
RETRY_BASE  = 2   # 退避基数（秒），实际等待 2^attempt 秒


def _get_auth_token() -> str:
    pcfg = cfg.get_project_config()
    if pcfg.get("api_key"):
        return pcfg["api_key"]
    return cfg.get_global_config().api_key


def _get_base_url() -> str:
    pcfg = cfg.get_project_config()
    if pcfg.get("base_url"):
        return pcfg["base_url"]
    return cfg.get_global_config().base_url


def _get_model() -> str:
    pcfg = cfg.get_project_config()
    if pcfg.get("model"):
        return pcfg["model"]
    return cfg.get_global_config().default_model


def _get_max_tokens() -> int:
    return cfg.get_global_config().extraction_max_tokens


def _get_parallel_workers() -> int:
    return cfg.get_global_config().parallel_workers

DOC_TYPE_RULES   = cfg.get_doc_type_rules()
_SYSTEM_NAME      = cfg.get_project_config().get("system_name", "业务系统")

# Lazy-loaded: domains.json may not exist at import time (created by discover step)
_biz_domain_rules_cache = None
_domains_str_cache = None
_valid_domains_cache = None

def _get_biz_domain_rules():
    global _biz_domain_rules_cache
    if _biz_domain_rules_cache is None:
        _biz_domain_rules_cache = cfg.get_domain_classification_rules()
    return _biz_domain_rules_cache

def _get_domains_str():
    global _domains_str_cache
    if _domains_str_cache is None:
        _domains_str_cache = "、".join(cfg.get_domains()) or "待分类"
    return _domains_str_cache

def _get_valid_domains():
    global _valid_domains_cache
    if _valid_domains_cache is None:
        _valid_domains_cache = set(cfg.get_domains())
    return _valid_domains_cache

# 源文档目录
EMPTY_SIZE     = 200   # 小于此字节视为空文件，跳过

# ============================================================
# 提炼 Prompt 模板（按文档类型）
# ============================================================
_DOC_TYPES_STR = "、".join(cfg.STANDARD_DOC_TYPES)


def _build_prompts() -> dict[str, str]:
    """Build prompt templates lazily (domains.json must exist by this point)."""
    domains_str = _get_domains_str()

    _type_instruction = (
        f"   - type: 判断文档类型（只允许以下值：{_DOC_TYPES_STR}）"
    )

    return {
        "需求文档": f"""你是{_SYSTEM_NAME}的知识库整理助手。
请从以下需求/方案文档中，提炼出核心业务规则和功能说明，输出标准 Markdown 文件。

输出格式要求：
1. 文件开头必须有 YAML frontmatter（用 --- 包裹），字段：
   - id: req-{{page_id}}
   - domain: 判断所属业务域（选项：{domains_str}）
   {_type_instruction}
   - title: 从文档中提取功能名称
   - source: Page ID {{page_id}}
   - status: active
   - updated: {{today}}
2. 正文按以下结构提炼（跳过无内容的部分）：
   ## 功能背景
   （现状/痛点/改造原因，1-3句）

   ## 功能说明
   （核心功能点，用编号列表）

   ## 业务规则
   （所有校验规则、业务约束、判断逻辑，用编号列表，这是最重要的部分）

   ## 接口说明
   （如有接口信息：请求方法、路径、参数表、JSON 示例）

   ## 字段说明
   （重要字段的枚举值、格式、约束，用表格或列表）

   ## 测试要点
   （如有测试信息：测试场景、正反例、边界条件）

3. 重点提炼"业务规则"，这是知识库最有价值的部分
4. 去除：截图占位、分支名称、开发人员名字、版本历史表、Confluence 格式噪声

原始文档内容：
{{content}}""",

        "业务规则": f"""你是{_SYSTEM_NAME}的知识库整理助手。
请从以下文档中，提炼结构化的业务规则，输出标准 Markdown 文件。

输出格式要求：
1. 文件开头必须有 YAML frontmatter（用 --- 包裹），字段：
   - id: rule-{{page_id}}
   - domain: 判断所属业务域（选项：{domains_str}）
   {_type_instruction}
   - title: 规则主题
   - source: Page ID {{page_id}}
   - status: active
   - updated: {{today}}
2. 正文：以编号列表形式列出所有业务规则，每条规则要自洽、可理解

原始文档内容：
{{content}}""",

        "其他": f"""你是{_SYSTEM_NAME}的知识库整理助手。
请从以下文档中，提炼核心知识内容，输出标准 Markdown 文件。

输出格式要求：
1. 文件开头必须有 YAML frontmatter（用 --- 包裹），字段：
   - id: doc-{{page_id}}
   - domain: 判断所属业务域（选项：{domains_str}）
   {_type_instruction}
   - title: 从内容提取主题
   - source: Page ID {{page_id}}
   - status: active
   - updated: {{today}}
2. 正文：保留所有有价值的业务知识（规则/流程/字段定义/约束/变更记录），去除格式噪声

原始文档内容：
{{content}}""",
    }

_prompts_cache = None

def _get_prompts() -> dict[str, str]:
    global _prompts_cache
    if _prompts_cache is None:
        _prompts_cache = _build_prompts()
    return _prompts_cache

# ============================================================
# 工具函数
# ============================================================

_log_lock = threading.Lock()


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with _log_lock:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()
    except Exception:
        pass  # Silently ignore logging errors to not interrupt processing


def load_json(path: Path) -> dict:
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())


def classify_by_name(name: str) -> tuple[str, str]:
    """
    基于文件名关键词快速分类，返回 (doc_type, biz_domain)。
    无法判断时返回 (None, None) 交给 AI 处理。
    """
    doc_type = None
    for dtype, patterns in DOC_TYPE_RULES:
        if any(re.search(p, name, re.I) for p in patterns):
            doc_type = dtype
            break

    biz_domain = None
    for domain, patterns in _get_biz_domain_rules():
        if any(re.search(p, name, re.I) for p in patterns):
            biz_domain = domain
            break

    return doc_type, biz_domain


def extract_page_id(filename: str) -> str:
    m = re.match(r"^(\d+)_", filename)
    return m.group(1) if m else "unknown"


def get_output_path(biz_domain: str, doc_type: str, page_id: str, title_slug: str) -> Path:
    domain_type_dir = DOMAINS_DIR / biz_domain / doc_type
    domain_type_dir.mkdir(parents=True, exist_ok=True)
    safe_slug = re.sub(r'[\\/:*?"<>|]', "_", title_slug)[:60]
    return domain_type_dir / f"{page_id}_{safe_slug}.md"


def call_claude(client: anthropic.Anthropic, prompt: str) -> str:
    """调用 Claude API，带重试逻辑。"""
    # 去除 emoji 等 BMP 以外字符，避免 GBK 编码问题
    clean_prompt = prompt.encode("utf-8", errors="replace").decode("utf-8")
    for attempt in range(MAX_RETRIES):
        try:
            resp = client.messages.create(
                model=_get_model(),
                max_tokens=_get_max_tokens(),
                messages=[{"role": "user", "content": clean_prompt}]
            )
            # Find first TextBlock (skip ThinkingBlock etc.)
            for block in resp.content:
                if hasattr(block, 'text'):
                    return block.text
            # Fallback: try first block anyway
            return resp.content[0].text
        except anthropic.RateLimitError:
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_BASE ** (attempt + 2)
                time.sleep(wait)
            # Silent retry - don't log from worker threads
        except anthropic.APIStatusError:
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_BASE ** (attempt + 1)
                time.sleep(wait)
            # Silent retry
        except Exception:
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_BASE ** (attempt + 1)
                time.sleep(wait)
            # Silent retry
    raise RuntimeError("超过最大重试次数")


def clean_output(output: str) -> str:
    """清理 AI 输出：去掉 frontmatter 外的 ```yaml 代码块包裹。"""
    output = output.strip()
    # 场景1: ```yaml\n---\n...---\n```\n后接正文
    if output.startswith("```yaml\n---") or output.startswith("```yaml\r\n---"):
        output = output[8:]          # 去掉 "```yaml\n"
        output = re.sub(r"\n---\n```\n", "\n---\n", output, count=1)
        output = re.sub(r"\n---\n```\r?\n", "\n---\n", output, count=1)
    # 场景2: 开头是 ```yaml 但没有 ---
    elif output.startswith("```yaml\n") or output.startswith("```yaml\r\n"):
        output = re.sub(r"^```yaml\r?\n", "", output)
        output = re.sub(r"\n```\s*\n", "\n", output, count=1)
    return output.strip()


def extract_title_from_output(output: str, fallback: str) -> str:
    """从 AI 输出的 frontmatter 中提取 title 字段。"""
    m = re.search(r"^title:\s*(.+)$", output, re.MULTILINE)
    if m:
        return m.group(1).strip().strip('"').strip("'")
    return fallback


def extract_domain_from_output(output: str, fallback: str) -> str:
    """从 AI 输出的 frontmatter 中提取 domain 字段，校验是否为合法域名。"""
    valid_domains = _get_valid_domains()
    m = re.search(r"^domain:\s*(.+)$", output, re.MULTILINE)
    if m:
        domain = m.group(1).strip().strip('"').strip("'")
        if domain in valid_domains:
            return domain
        # 模糊匹配：AI 输出的域名可能与配置的域名部分匹配
        for valid in valid_domains:
            if valid in domain or domain in valid:
                return valid
        return fallback
    return fallback


def extract_doctype_from_output(output: str, fallback: str) -> str:
    """从 AI 输出的 frontmatter 中提取 type 字段，标准化为配置的文档类型。

    AI 可能返回"详细设计文档"、"接口设计文档"等非标准类型，
    用 doc_type_rules 的 patterns 归一化到标准类型（需求文档/业务文档/业务规则）。
    """
    m = re.search(r"^type:\s*(.+)$", output, re.MULTILINE)
    if not m:
        return fallback
    raw_type = m.group(1).strip().strip('"').strip("'")

    # 标准类型直接返回
    standard_types = {dtype for dtype, _ in DOC_TYPE_RULES}
    if raw_type in standard_types:
        return raw_type

    # 用 doc_type_rules 的 patterns 匹配 AI 输出的类型名
    for dtype, patterns in DOC_TYPE_RULES:
        if any(re.search(p, raw_type, re.I) for p in patterns):
            return dtype

    return fallback


# ============================================================
# 文件列表构建
# ============================================================

def get_source_dir() -> Path:
    """返回源文档目录（source/docs/）。"""
    new_dir = SOURCE_DIR / "docs"
    return new_dir


def build_file_list() -> list[dict]:
    """扫描源文档目录，过滤空文件，返回待处理列表。"""
    source_dir = get_source_dir()
    files = []
    for fname in sorted(os.listdir(source_dir)):
        if not fname.endswith(".md"):
            continue
        fpath = source_dir / fname
        size = fpath.stat().st_size
        if size < EMPTY_SIZE:
            continue
        name_no_id = re.sub(r"^\d+_", "", fname[:-3])  # strip id_ and .md
        page_id = extract_page_id(fname)
        doc_type, biz_domain = classify_by_name(name_no_id)
        files.append({
            "filename":   fname,
            "page_id":    page_id,
            "name":       name_no_id,
            "doc_type":   doc_type,
            "biz_domain": biz_domain,
            "rel_path":   fpath.relative_to(source_dir),
        })
    return files


# ============================================================
# 并行处理工作函数
# ============================================================

_progress_lock = threading.Lock()
_shared_progress: dict = {}
_shared_errors: dict = {}


def _process_one(item: dict, client, today: str) -> dict:
    """处理单个文件，返回结果 dict。"""
    fname      = item["filename"]
    page_id    = item["page_id"]
    name       = item["name"]
    doc_type   = item["doc_type"]
    biz_domain = item["biz_domain"]

    # 每个 worker 用独立 client 连接
    worker_client = anthropic.Anthropic(api_key=_get_auth_token(), base_url=_get_base_url() or None)

    fpath = get_source_dir() / fname
    raw = fpath.read_text(encoding="utf-8")
    content = raw[:8000] if len(raw) > 8000 else raw

    prompts     = _get_prompts()
    prompt_key  = doc_type if doc_type in prompts else "其他"
    prompt_tmpl = prompts[prompt_key]
    prompt      = prompt_tmpl.format(
        page_id = page_id,
        content = content,
        today   = today,
    )

    try:
        output = clean_output(call_claude(worker_client, prompt))
        actual_domain  = extract_domain_from_output(output, biz_domain or "待分类")
        actual_doctype = extract_doctype_from_output(output, doc_type or "其他")
        title          = extract_title_from_output(output, name)

        out_path = get_output_path(actual_domain, actual_doctype, page_id, title)
        out_path.write_text(output, encoding="utf-8")

        result = {
            "filename": fname,
            "status": "done",
            "out_path": f"{actual_domain}/{actual_doctype}/{out_path.name}",
        }
    except Exception as e:
        result = {
            "filename": fname,
            "status": "error",
            "error": f"{type(e).__name__}: {e}",
        }

    return result


# ============================================================
# 主处理循环（并行）
# ============================================================

def _is_truly_done(progress_value: str) -> bool:
    """Check if a file is truly done: progress stores the output path, verify it exists.

    Format: "域名/doc_type/文件名.md" (relative to domains/).
    Legacy formats: "done", "doc_type/文件名.md" (relative to knowledgeBase/).
    """
    if not progress_value or progress_value == "error":
        return False
    if progress_value == "done":
        return True
    # New format: relative to domains/
    out_file = DOMAINS_DIR / progress_value
    if out_file.exists():
        return True
    # Legacy format: relative to knowledgeBase/
    out_file = KNOWLEDGE_BASE / progress_value
    return out_file.exists()


def process_files(retry_errors: bool = False):
    global _shared_progress, _shared_errors
    _shared_progress = load_json(PROGRESS_FILE)
    _shared_errors   = load_json(ERRORS_FILE)
    today = datetime.now().strftime("%Y-%m-%d")

    all_files = build_file_list()
    total     = len(all_files)

    if retry_errors:
        to_run = [f for f in all_files if f["filename"] in _shared_errors]
        log(f"重试模式：共 {len(to_run)} 个失败文件")
    else:
        to_run = [f for f in all_files
                  if not _is_truly_done(_shared_progress.get(f["filename"], ""))]
        done_count = total - len(to_run)
        log(f"共 {total} 个文件，已完成 {done_count}，待处理 {len(to_run)}（并行 {_get_parallel_workers()} workers）")

    done_count = 0
    err_count  = 0

    def _flush():
        # Called only from within _progress_lock — do NOT re-acquire the lock.
        # Also release GIL during slow I/O for better concurrency.
        save_json(PROGRESS_FILE, _shared_progress)
        save_json(ERRORS_FILE, _shared_errors)

    with ThreadPoolExecutor(max_workers=_get_parallel_workers()) as executor:
        futures = {executor.submit(_process_one, item, None, today): item for item in to_run}

        for future in as_completed(futures):
            result = future.result()
            fname  = result["filename"]

            with _progress_lock:
                if result["status"] == "done":
                    _shared_progress[fname] = result["out_path"]
                    if fname in _shared_errors:
                        del _shared_errors[fname]
                    done_count += 1
                    log(f"  [OK] {fname[:55]} -> {result['out_path']}")
                else:
                    _shared_progress[fname] = "error"
                    _shared_errors[fname] = {"error": result["error"], "time": today}
                    err_count += 1
                    log(f"  [FAIL] {fname[:55]}: {result['error'][:80]}")

                # 每 5 个文件保存一次进度（平衡 IO 与安全性）
                if (done_count + err_count) % 5 == 0:
                    _flush()
                    log(f"  [进度] 已完成 {done_count}，失败 {err_count}，剩余 {len(to_run) - done_count - err_count}")

    _flush()
    log(f"=== 完成 === 成功 {done_count} / 失败 {err_count} / 总计 {total}")


def cleanup_empty_dirs(kb_dir: Path) -> None:
    """删除 knowledgeBase/ 下所有不含文件的空目录（自底向上）。"""
    for dirpath, dirnames, filenames in os.walk(str(kb_dir), topdown=False):
        p = Path(dirpath)
        if p == kb_dir or p.name.startswith("_"):
            continue
        # 如果目录里没有任何文件（递归检查子目录也为空）
        if not any(p.rglob("*")):
            try:
                shutil.rmtree(p)
                log(f"  [清理] 删除空目录: {p.relative_to(kb_dir)}")
            except OSError:
                pass


def print_stats():
    progress = load_json(PROGRESS_FILE)
    errors   = load_json(ERRORS_FILE)
    all_files = build_file_list()
    total     = len(all_files)
    done      = sum(1 for v in progress.values() if v == "done")
    err       = sum(1 for v in progress.values() if v == "error")
    pending   = total - done - err
    print(f"总计: {total}  |  已完成: {done}  |  失败: {err}  |  待处理: {pending}")
    if errors:
        print(f"\n失败文件 ({len(errors)}):")
        for fname, info in list(errors.items())[:20]:
            print(f"  {fname[:60]}: {info['error'][:80]}")


def init_kb_structure():
    """初始化知识库目录骨架和元数据文件。

    Creates domains/{域名}/{doc_type}/ directory structure for document extraction.
    Also creates knowledgeBase/ skeleton (will be populated by Step 7 migration).
    """
    domains = cfg.get_domains()
    doc_types = cfg.STANDARD_DOC_TYPES

    # 创建 domains/{域名}/{doc_type}/ 目录（嵌套结构，用于提炼阶段）
    domains_dir = cfg.get_domains_dir()
    for domain in domains:
        for dtype in doc_types:
            (domains_dir / domain / dtype).mkdir(parents=True, exist_ok=True)

    # 创建 knowledgeBase/ 骨架（搬迁后使用）
    for dtype in doc_types:
        (KNOWLEDGE_BASE / dtype).mkdir(parents=True, exist_ok=True)

    # README（写到 domains/ 下）
    _project_name = cfg.get_project_config().get("system_name", "业务系统")
    readme = domains_dir / "README.md"
    domain_lines = [f"- [{d}](./{d}/)" for d in domains]
    readme.write_text(
        f"# {_project_name}业务知识库 — 域定义\n\n"
        "本目录由 ewankb 自动发现并生成，每个子目录代表一个业务域。\n\n"
        "## 业务域\n\n"
        + "\n".join(domain_lines)
        + "\n\n> 更新时间：" + datetime.now().strftime("%Y-%m-%d") + "\n",
        encoding="utf-8"
    )

    # _meta/biz-domains.md（域列表索引，放 knowledgeBase/_meta/ 下；域定义在 domains/_meta/domains.json）
    meta_dir = KNOWLEDGE_BASE / "_meta"
    meta_dir.mkdir(exist_ok=True)
    biz_meta = meta_dir / "biz-domains.md"
    descriptions = cfg.get_domain_descriptions()
    rows = [f"| {name} | {desc} |" for name, desc in descriptions.items()]
    biz_meta.write_text(
        f"# 业务域定义\n\n| 业务域 | 说明 |\n|--------|------|\n" + "\n".join(rows) + "\n",
        encoding="utf-8"
    )
    log("知识库目录骨架初始化完成")


# ============================================================
# 入口
# ============================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Confluence 知识库提炼脚本")
    parser.add_argument("--retry",  action="store_true", help="只重试失败文件")
    parser.add_argument("--stats",  action="store_true", help="只显示进度统计")
    parser.add_argument("--init",   action="store_true", help="只初始化目录结构")
    args = parser.parse_args()

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    log(f"===== 启动 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} =====")

    if args.stats:
        print_stats()
    elif args.init:
        init_kb_structure()
    else:
        init_kb_structure()
        process_files(retry_errors=args.retry)
