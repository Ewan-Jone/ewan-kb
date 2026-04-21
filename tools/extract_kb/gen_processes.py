#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
业务流程文档生成脚本

为每个业务域生成 PROCESSES.md，按 L1/L2/L3 三级流程结构组织。
- 父域：记录跨子域协调流程，引用子域 PROCESSES.md
- 子域：记录该子域完整的 L1/L2/L3 流程

用法：
  python gen_processes.py                    # 全部域（跳过已存在）
  python gen_processes.py --domain 运配管理  # 只处理某域（含子域）
  python gen_processes.py --domain 运配管理/运配任务  # 单个子域
  python gen_processes.py --force           # 强制重新生成
"""
import os, sys, re, json, time, argparse, threading
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import anthropic

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools import config_loader as cfg
from tools.text_utils import parse_frontmatter

# ── 路径配置 ─────────────────────────────────────────────────────────────────

BASE_DIR    = cfg.get_kb_dir()
DOMAINS_DIR = cfg.get_domains_dir()
TODAY       = datetime.now().strftime("%Y-%m-%d")

gcfg        = cfg.get_global_config()
pcfg        = cfg.get_project_config()
_AUTH_TOKEN = pcfg.get("api_key") or gcfg.api_key
_BASE_URL   = pcfg.get("base_url") or gcfg.base_url
MODEL       = pcfg.get("model") or gcfg.default_model
MAX_TOKENS  = 4000
_SYSTEM_NAME = cfg.get_project_config().get("system_name", "业务系统")

SKIP_DOMAINS = cfg.get_skip_domains()

# ── 工具函数 ─────────────────────────────────────────────────────────────────

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def get_doc_title(fpath: Path) -> str:
    try:
        text = fpath.read_text(encoding="utf-8", errors="replace")[:400]
        return parse_frontmatter(text).get("title", fpath.stem)
    except Exception:
        return fpath.stem

def read_doc_content(fpath: Path, max_chars: int = 3000) -> str:
    """读取文档，截取 body 部分（前 max_chars 字符）"""
    try:
        text = fpath.read_text(encoding="utf-8", errors="replace")
        # 去掉 frontmatter
        text = re.sub(r'^---\n.*?\n---\n', '', text, count=1, flags=re.DOTALL)
        return text.strip()[:max_chars]
    except Exception:
        return ""

def call_claude(client, prompt: str) -> str:
    for attempt in range(3):
        try:
            resp = client.messages.create(
                model=MODEL, max_tokens=MAX_TOKENS,
                messages=[{"role": "user",
                           "content": prompt.encode("utf-8", "replace").decode("utf-8")}]
            )
            # 兼容 ThinkingBlock（某些模型会返回 thinking + text）
            for block in resp.content:
                if block.type == "text":
                    return block.text
            raise RuntimeError("API 返回内容中未找到 text 块")
        except Exception as e:
            if attempt < 2:
                time.sleep(2 ** attempt)
            else:
                raise

# ── Prompt ────────────────────────────────────────────────────────────────────

L1_L2_L3_DEFINITIONS = """\
## L1 主流程定义（必须同时满足）
1. 独立触发 — 有独立的触发事件（用户操作 / 系统事件 / 定时任务）
2. 明确终态 — 有可辨识的结束状态（成功 / 失败 / 取消）
3. 业务价值 — 交付可感知的业务结果
4. 独立性 — 可以脱离其他 L1 独立发生

数量约束：每域 3~8 个 L1。

## L2 子流程定义（满足任一）
- 同一 L1 的不同入口/渠道（如手工录入 vs 系统推送）
- 同一 L1 内的条件分支（如状态判断、金额阈值）
- L1 生命周期中的独立阶段（如审批通过后联动创建）

数量约束：每个 L1 下 2~6 个 L2。

## L3 业务规则定义
- 可以用一条 IF-THEN 或 WHEN-DO 表达
- 无独立的起止状态，可被多个 L2/L1 复用
- 格式：触发条件 → 校验内容 → 通过/失败处理

## 横切关注点
不属于任何单一 L1，跨所有流程生效的全局约束（如权限控制、数据隔离、合规审核）。"""


def build_prompt(domain: str, domain_dir: Path, is_parent: bool,
                 child_processes: dict, all_docs_text: str,
                 parent: str) -> str:
    """构建 AI prompt"""

    # 收集子域 PROCESSES.md 的 L1 目录（用于父域识别跨子域流程）
    child_l1_entries = []
    for child_domain, child_content in child_processes.items():
        lines = child_content.split("\n")
        in_toc = False
        for line in lines:
            if "## 目录" in line or "## 索引" in line:
                in_toc = True
                continue
            if in_toc and line.startswith("## "):
                break
            if in_toc and line.strip() and not line.startswith("---"):
                child_l1_entries.append(f"  [{child_domain}] {line.strip()}")

    # 判断父域还是子域
    if is_parent:
        task_type = "父域"
        instruction = f"""\
## 任务
你是{_SYSTEM_NAME}的流程分析师。请根据以下域内文档和子域流程索引，为父域「{domain}」识别跨子域协调流程。

重点识别：
1. 涉及多个子域协作的主流程（如"创建运单→触发调度→分配司机"）
2. 子域间的数据流转和事件触发关系
3. 父域层面的统一规则（如全局状态定义、跨域权限控制）

只输出以「## L1.X」开头的章节，每个 L1 下包含 L2 子流程。\
不要重复子域内部的独立流程。\
输出格式见下方模板。\
"""
        context_info = f"""\
## 子域流程索引（各子域已有的 L1/L2，来自子域 PROCESSES.md）
{chr(10).join(child_l1_entries) if child_l1_entries else "（暂无子域 PROCESSES.md）"}
"""
    else:
        task_type = "子域"
        instruction = f"""\
## 任务
你是{_SYSTEM_NAME}的流程分析师。请根据以下域内文档，为子域「{domain}」识别完整的三级流程结构。

请严格按照以下步骤：
1. 识别所有 L1 主流程（必须满足：独立触发 + 明确终态 + 业务价值 + 独立性）
2. 为每个 L1 识别 L2 子流程（变体/分支/阶段）
3. 从 L2 步骤中提取可复用的 L3 业务规则
4. 识别跨 L1 的横切关注点

只输出以「## L1.X」或「## 横切规则」开头的章节，不要输出其他内容。\
输出格式见下方模板。\
"""
        context_info = f"""\
> 父域：{parent if parent else '（顶级域）'}\
"""

    return f"""\
你是{_SYSTEM_NAME}的业务流程分析师。请根据以下信息，为「{domain}」生成流程文档。

{L1_L2_L3_DEFINITIONS}

## 域信息
- 域路径：{domain}
- 域类型：{task_type}
{context_info}

## 域内文档内容摘要
{all_docs_text[:8000] if all_docs_text else '（无相关文档）'}

{instruction}

## 输出模板（严格遵循此格式）
```
# {domain} — 业务流程详情

> 来源：{domain}下 N 篇知识文件
{f"> 父域：[父域名](../PROCESSES.md)" if parent else "> 父域：（顶级域）"}
> ⚠️ 本文件为 AI 自动生成，内容基于文档摘要整理，如有不准确之处请修正。

## 目录
- L1.X {{主流程名}}
  - L2: {{子流程名}}

---

## L1.X {{主流程名}}

**触发** / **终态** / **涉及角色**

### L2: {{子流程名}}

**触发** / **步骤** / **状态流转**

#### L3 业务规则

| 规则 | 触发条件 | 校验内容 | 通过/失败处理 |
|------|---------|---------|------------|

（重复 L1/L2/L3 ...）

---

## 横切规则

### {{横切主题}}

（跨 L1 生效的全局约束）
```"""


# ── 文档收集 ─────────────────────────────────────────────────────────────────

def collect_domain_docs(domain: str) -> dict:
    """收集 domains/{域名}/{doc_type}/ 下的所有文档"""
    domain_dir = DOMAINS_DIR / domain
    result = {}
    if not domain_dir.exists():
        return result
    for dtype_dir in sorted(domain_dir.iterdir()):
        if not dtype_dir.is_dir() or dtype_dir.name.startswith("_"):
            continue
        dtype = dtype_dir.name
        result[dtype] = []
        for f in sorted(dtype_dir.glob("*.md")):
            if f.name == "README.md":
                continue
            title = get_doc_title(f)
            content = read_doc_content(f)
            if content:
                result[dtype].append((title, content))
    return result


def is_parent_domain(domain: str) -> bool:
    """判断是否父域：检查 domains.json 中是否有子域"""
    all_domains = cfg.get_domains()
    prefix = domain + "/"
    return any(d.startswith(prefix) for d in all_domains)


def build_docs_summary(docs: dict, max_per_type: int = 5) -> str:
    """将文档整理为 AI 可读的摘要文本"""
    lines = []
    total = sum(len(v) for v in docs.values())
    if total == 0:
        return ""

    for dtype, items in docs.items():
        if not items:
            continue
        lines.append(f"\n### [{dtype}]（共 {len(items)} 篇）\n")
        for title, content in items[:max_per_type]:
            # 取前 500 字符作为摘要
            snippet = content[:500].replace("\n", " ").strip()
            lines.append(f"**{title}**：{snippet}")
            if len(content) > 500:
                lines.append(f"  ...（省略 {len(content)-500} 字符）")
        if len(items) > max_per_type:
            lines.append(f"  ... 还有 {len(items) - max_per_type} 篇文档")
    return "\n".join(lines)


# ── 子域 PROCESSES.md 读取 ────────────────────────────────────────────────────

def read_child_processes(domain: str) -> dict:
    """读取所有子域的 PROCESSES.md，供父域使用"""
    result = {}
    domain_dir = DOMAINS_DIR / domain
    if not domain_dir.exists():
        return result
    for child_dir in domain_dir.iterdir():
        if not child_dir.is_dir() or child_dir.name.startswith("_"):
            continue
        pf = child_dir / "PROCESSES.md"
        if pf.exists():
            child_domain = f"{domain}/{child_dir.name}"
            try:
                result[child_domain] = pf.read_text(encoding="utf-8")
            except Exception:
                pass
    return result


# ── PROCESSES.md 生成 ────────────────────────────────────────────────────────

def gen_processes_md(client, domain: str, is_parent: bool) -> str:
    parent = cfg.get_parent_domain(domain)
    domain_dir = DOMAINS_DIR / domain

    # 1. 收集本域文档
    docs = collect_domain_docs(domain)
    docs_summary = build_docs_summary(docs)

    # 2. 读取子域 PROCESSES.md（供父域识别跨子域流程）
    child_processes = {}
    if is_parent:
        child_processes = read_child_processes(domain)

    # 3. 构建 prompt
    prompt = build_prompt(domain, domain_dir, is_parent, child_processes, docs_summary, parent)

    # 4. 调用 AI
    ai_content = call_claude(client, prompt).strip()

    # 5. 清理 AI 输出，丢弃 AI 自带的 header（到 ## 目录 之前的所有内容）
    # AI 按模板输出时，会在 ## 目录 之前生成标题/引用行/分隔线，这些都丢弃
    toc_match = re.search(r'(## 目录|## 索引|## L1)', ai_content)
    if toc_match:
        ai_content = ai_content[toc_match.start():]
    else:
        ai_content = ai_content.strip()

    # 6. 构建最终文件内容
    total_docs = sum(len(v) for v in docs.values())

    frontmatter = f"""\
---
type: 流程文档
domain: {domain}
updated: {TODAY}
---

"""

    if is_parent:
        header = f"""# {domain.rsplit("/", 1)[-1]} — 业务流程详情

> 本文件记录跨子域的全局流程。子域内部流程见各子域的 PROCESSES.md。
> ⚠️ 本文件为 AI 自动生成，内容基于文档摘要整理，如有不准确之处请修正。

"""
    else:
        parent_link = f"[{parent}](../{parent}/PROCESSES.md)" if parent else "（顶级域）"
        header = f"""# {domain.rsplit("/", 1)[-1]} — 业务流程详情

> 来源：{domain}下 {total_docs} 篇知识文件
> 父域：{parent_link}
> ⚠️ 本文件为 AI 自动生成，内容基于文档摘要整理，如有不准确之处请修正。

"""

    return frontmatter + header + ai_content


# ── 主流程 ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="生成各域 PROCESSES.md")
    parser.add_argument("--domain", help="只处理指定域（支持子域路径，如 运配管理/运配任务）")
    parser.add_argument("--force",  action="store_true", help="强制重新生成")
    args = parser.parse_args()

    client = (anthropic.Anthropic(api_key=_AUTH_TOKEN, base_url=_BASE_URL)
              if _BASE_URL else anthropic.Anthropic())

    if args.domain:
        domain_dir = DOMAINS_DIR / args.domain
        if not domain_dir.exists():
            domain_dir.mkdir(parents=True, exist_ok=True)

        is_parent = is_parent_domain(args.domain)

        pf = domain_dir / "PROCESSES.md"
        if pf.exists() and not args.force:
            log(f"跳过(已存在): {args.domain}")
            return

        log(f"生成: {args.domain} (类型: {'父域' if is_parent else '子域'})")
        try:
            content = gen_processes_md(client, args.domain, is_parent)
            pf.write_text(content, encoding="utf-8")
            log(f"  -> {args.domain}/PROCESSES.md")
        except Exception as e:
            log(f"  [失败] {args.domain}: {e}")
        return

    # 扫描所有域（从 domains.json）
    all_domains = cfg.get_domains()
    target_domains = []

    for domain_path in all_domains:
        if domain_path in SKIP_DOMAINS or domain_path == "待分类":
            continue
        domain_dir = DOMAINS_DIR / domain_path
        pf = domain_dir / "PROCESSES.md"
        if pf.exists() and not args.force:
            log(f"  跳过(已存在): {domain_path}")
            continue
        target_domains.append(domain_path)

    # 分离父域和子域：父域依赖子域的 PROCESSES.md，必须后处理
    child_domains = [d for d in target_domains if not is_parent_domain(d)]
    parent_domains = [d for d in target_domains if is_parent_domain(d)]

    workers = cfg.get_global_config().parallel_workers
    log_lock = threading.Lock()
    done = 0
    errs = 0

    def _process_one(domain_path: str, is_parent: bool) -> bool:
        nonlocal done, errs
        worker_client = (anthropic.Anthropic(api_key=_AUTH_TOKEN, base_url=_BASE_URL)
                         if _BASE_URL else anthropic.Anthropic())
        domain_dir = DOMAINS_DIR / domain_path
        domain_dir.mkdir(parents=True, exist_ok=True)
        try:
            with log_lock:
                log(f"  生成: {domain_path} ({'父域' if is_parent else '子域'})")
            content = gen_processes_md(worker_client, domain_path, is_parent)
            pf = domain_dir / "PROCESSES.md"
            pf.write_text(content, encoding="utf-8")
            with log_lock:
                done += 1
            return True
        except Exception as e:
            with log_lock:
                errs += 1
                log(f"    [失败] {domain_path}: {e}")
            return False

    total = len(target_domains)
    log(f"共 {total} 个域待处理（{len(child_domains)} 子域 + {len(parent_domains)} 父域，并行 {workers} workers）")

    # Phase 1: 子域并发处理
    if child_domains:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(_process_one, d, False): d for d in child_domains}
            for future in as_completed(futures):
                future.result()

    # Phase 2: 父域并发处理（子域已完成，父域可读取子域 PROCESSES.md）
    if parent_domains:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(_process_one, d, True): d for d in parent_domains}
            for future in as_completed(futures):
                future.result()

    log(f"=== 完成 === 共:{total} 完成:{done} 失败:{errs}")


if __name__ == "__main__":
    log(f"===== 启动 {TODAY} =====")
    main()
