#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
知识库深度提炼脚本

功能：
  - 逐一阅读 domains/{域名}/{doc_type}/ 下的知识文件，结合代码仓库实现进行内容校验
  - 文档与代码有差异时以代码为准，并注明差异
  - 在文档末尾补充「关联代码」和「关联文档」章节，便于 LLM 检索时找到上下游信息

用法：
  python enrich_kb.py                         # 全量提炼（跳过已完成）
  python enrich_kb.py --stats                 # 查看进度
  python enrich_kb.py --domain 任务中心        # 只处理某个域
  python enrich_kb.py --type 需求文档          # 只处理某种文档类型
  python enrich_kb.py --domain 任务中心 --type 需求文档  # 组合过滤
"""
import os, sys, re, json, time, argparse, threading
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import anthropic

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools import config_loader as cfg
from tools.text_utils import parse_frontmatter

# ── 路径配置（从配置文件加载）─────────────────────────────────────────────────

BASE_DIR    = cfg.get_kb_dir()
DOMAINS_DIR = cfg.get_domains_dir()           # domains/{域名}/{doc_type}/ 下工作
REPOS       = cfg.get_repos_dir()
PROGRESS    = cfg.get_knowledge_base_dir() / "_state/enrich_progress.json"
TODAY       = datetime.now().strftime("%Y-%m-%d")

gcfg        = cfg.get_global_config()
pcfg        = cfg.get_project_config()
_AUTH_TOKEN = pcfg.get("api_key") or gcfg.api_key
_BASE_URL   = pcfg.get("base_url") or gcfg.base_url
MODEL       = pcfg.get("model") or gcfg.default_model
MAX_TOKENS  = 4000
_SYSTEM_NAME = cfg.get_project_config().get("system_name", "业务系统")

# ── 域 → 代码模块映射（从 domains.json 加载）──────────────────────────────────

DOMAIN_TO_MODULES = cfg.get_domain_to_modules()  # {domain: [module_name, ...]}
SKIP_DOMAINS = cfg.get_skip_domains()
SKIP_TYPES   = cfg.get_skip_doc_types_for_enrich()

# ── Prompt ───────────────────────────────────────────────────────────────────

APPEND_PROMPT = f"""\
你是{_SYSTEM_NAME}知识库整理助手。请根据以下信息，生成两个 Markdown 章节内容。

## 知识文件摘要
标题：{{title}}
域：{{domain}}
类型：{{doc_type}}
{{frontmatter_extra}}

## 对应代码实现（来自代码仓库，如有）
{{code_snippets}}

## 相关知识文件（候选列表）
{{related_docs}}

## 任务
只输出以下两个章节的内容，不要输出其他内容：

### 关联代码
列出与本文档直接相关的核心类/接口文件（从上方代码片段中选取），格式：
- `仓库名/模块路径/文件名.java` — 一句话说明该文件与本文档的关系

### 关联文档
列出最相关的知识文件（从候选列表中选 2-4 个），格式：
- [文档标题](相对路径) — 一句话说明关联原因

若代码与文档描述存在明显差异（如接口路径、参数名、业务规则不符），额外输出：

### 实现备注
说明具体差异：文档描述是X，代码实际是Y

只输出上述章节，不要重写文档正文，不要加解释性文字。
"""

# ── 工具函数 ─────────────────────────────────────────────────────────────────

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def load_json(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}

def save_json(p: Path, data):
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def get_module_dir(repo_name: str, module: str) -> Path:
    pattern = cfg.get_code_structure().get("atomic_service_pattern", "atomic-service/{module}-atomic-service")
    return REPOS / repo_name / pattern.replace("{module}", module)

def get_kb_files(domain_filter=None, type_filter=None):
    """Scan domains/{域名}/{doc_type}/*.md, domain from directory structure."""
    files = []
    if not DOMAINS_DIR.exists():
        return files
    for domain_dir in sorted(DOMAINS_DIR.iterdir()):
        if not domain_dir.is_dir() or domain_dir.name.startswith("_"):
            continue
        domain = domain_dir.name
        if domain in SKIP_DOMAINS:
            continue
        if domain_filter and domain != domain_filter:
            continue
        for dtype_dir in sorted(domain_dir.iterdir()):
            if not dtype_dir.is_dir() or dtype_dir.name.startswith("_"):
                continue
            dtype = dtype_dir.name
            if dtype in SKIP_TYPES:
                continue
            if type_filter and dtype != type_filter:
                continue
            for f in sorted(dtype_dir.glob("*.md")):
                if f.name == "README.md":
                    continue
                files.append(f)
    return files

# ── 代码索引 ─────────────────────────────────────────────────────────────────

def build_code_index():
    """
    预扫描所有模块目录，构建：
      code_idx[domain] = { java_path_str: {"path": Path, "descs": [str], "endpoints": [str]} }
      code_kw_idx = { chinese_word: [java_path_str, ...] }
      endpoint_idx = { endpoint_path_fragment: [java_path_str, ...] }
    """
    log("构建代码索引...")
    code_idx = {}   # domain -> { file_str -> info }
    kw_idx   = defaultdict(list)   # chinese kw -> file_strs
    ep_idx   = defaultdict(list)   # endpoint fragment -> file_strs

    for domain, modules in DOMAIN_TO_MODULES.items():
        code_idx[domain] = {}
        for module in modules:
            if not REPOS.exists():
                continue
            # modules 路径可能以仓库名开头（如 "my-service/my-application/..."）
            # 在仓库目录内搜索时去掉仓库名前缀
            mod_dir = None
            for repo_dir in REPOS.iterdir():
                if not repo_dir.is_dir() or repo_dir.name.startswith("."):
                    continue
                inner = module[len(repo_dir.name) + 1:] if module.startswith(repo_dir.name + "/") else module
                candidate = repo_dir / inner
                if candidate.exists() and candidate.is_dir():
                    mod_dir = candidate
                    break
            if mod_dir is None:
                continue
            for jf in mod_dir.rglob("*.java"):
                if "Test" in jf.stem or "test" in str(jf):
                    continue
                try:
                    content = jf.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue

                # Extract @Desc values
                descs = re.findall(r'@Desc\s*\(\s*["\']([^"\']+)["\']', content)
                # Extract endpoint fragments from @RequestMapping / @PostMapping
                endpoints = re.findall(
                    r'@(?:Request|Get|Post|Put|Delete)Mapping\s*\(\s*["\']([^"\']+)["\']',
                    content
                )

                # Derive repo name from path
                try:
                    _repo_name = jf.relative_to(REPOS).parts[0]
                except ValueError:
                    _repo_name = module
                file_str = f"{_repo_name}/{jf.relative_to(REPOS / _repo_name)}".replace("\\", "/")
                info = {"path": jf, "repo": _repo_name, "descs": descs, "endpoints": endpoints, "file_str": file_str}
                code_idx[domain][file_str] = info

                # Index by Chinese words in @Desc
                for desc in descs:
                    words = re.findall(r'[\u4e00-\u9fff]{2,8}', desc)
                    for w in words:
                        if file_str not in kw_idx[w]:
                            kw_idx[w].append(file_str)

                # Index by endpoint fragments
                for ep in endpoints:
                    parts = [p for p in ep.strip("/").split("/") if p and not p.startswith("{")]
                    for part in parts:
                        if part not in ep_idx[ep]:
                            ep_idx[part].append(file_str)

    log(f"代码索引完成：{sum(len(v) for v in code_idx.values())} 个 Java 文件")
    return code_idx, kw_idx, ep_idx


def build_doc_index(files):
    """构建文档标题关键词索引: chinese_word → [file_path, ...]"""
    idx = defaultdict(list)
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")[:400]
        except Exception:
            continue
        fm = parse_frontmatter(text)
        title = fm.get("title", f.stem)
        words = re.findall(r'[\u4e00-\u9fff]{2,6}', title)
        for w in words:
            if f not in idx[w]:
                idx[w].append(f)
    return idx

# ── 代码片段查找 ─────────────────────────────────────────────────────────────

def extract_java_skeleton(java_path: Path, max_lines=70) -> str:
    """提取 Java 文件的类骨架：注解、类声明、方法签名，不含方法体"""
    try:
        lines = java_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return ""

    result = []
    for line in lines:
        s = line.strip()
        _java_pkg_prefix = cfg.get_code_structure().get("java_package_prefix", "com.example")
        if not s or s.startswith(f"import {_java_pkg_prefix}") or s.startswith("package "):
            # Keep package and key imports
            if s.startswith("package "):
                result.append(s)
            continue
        # Include: annotations, class/interface decl, method signatures (lines with parentheses)
        if (s.startswith("@") or
                re.match(r'.*(class|interface|enum)\s+\w+', s) or
                re.match(r'\s*(public|protected|private).*\(', line) or
                (s.startswith("//") and len(result) < 8)):
            result.append(line.rstrip())
        if len(result) >= max_lines:
            break

    return "\n".join(result)


def find_code_snippets(domain: str, fm: dict, title: str,
                       code_idx: dict, kw_idx: dict, ep_idx: dict) -> list[dict]:
    """为文档找最相关的代码文件（最多5个）"""
    domain_files = code_idx.get(domain, {})
    if not domain_files:
        return []

    scored = defaultdict(int)

    # 1. 含 path 字段的文档：用 path 字段精确匹配 endpoint
    endpoint_path = fm.get("path", "")
    if endpoint_path:
        parts = [p for p in endpoint_path.strip("/").split("/") if p and not p.startswith("{")]
        for part in parts:
            for file_str in ep_idx.get(part, []):
                if file_str in domain_files:
                    scored[file_str] += 3

    # 2. 所有类型：用标题中文关键词匹配 @Desc
    cn_words = re.findall(r'[\u4e00-\u9fff]{2,6}', title)
    for w in cn_words:
        for file_str in kw_idx.get(w, []):
            if file_str in domain_files:
                scored[file_str] += 1

    # 3. 无匹配时，fallback 到 domain 中带 "Rest" 或 "Service" 的文件
    if not scored:
        for file_str, info in domain_files.items():
            stem = Path(file_str).stem
            if "Rest" in stem or "Controller" in stem:
                scored[file_str] += 1

    top = sorted(scored.items(), key=lambda x: -x[1])[:5]

    snippets = []
    for file_str, _ in top:
        info = domain_files[file_str]
        skeleton = extract_java_skeleton(info["path"])
        if skeleton:
            snippets.append({
                "file_str": file_str,
                "repo": info["repo"],
                "skeleton": skeleton,
                "descs": info["descs"][:5],
            })
    return snippets


# ── 关联文档查找 ─────────────────────────────────────────────────────────────

def find_related_docs(fpath: Path, title: str, domain: str,
                      doc_idx: dict, max_results=5) -> list[dict]:
    """基于标题关键词重叠找关联文档"""
    words = re.findall(r'[\u4e00-\u9fff]{2,6}', title)
    score = defaultdict(int)
    for w in words:
        for other in doc_idx.get(w, []):
            if other != fpath:
                score[other] += 1

    ranked = sorted(score.items(),
                    key=lambda x: -x[1])

    results = []
    for p, s in ranked[:max_results]:
        if s < 2:
            continue  # require at least 2 overlapping words
        try:
            text = p.read_text(encoding="utf-8", errors="replace")[:300]
        except Exception:
            continue
        fm  = parse_frontmatter(text)
        rel = p.relative_to(DOMAINS_DIR)
        results.append({
            "title":  fm.get("title", p.stem),
            "path":   str(rel).replace("\\", "/"),
            "domain": p.parent.parent.name,
        })
    return results


# ── Claude 调用 ──────────────────────────────────────────────────────────────

def call_claude(client, prompt: str) -> str:
    for attempt in range(3):
        try:
            resp = client.messages.create(
                model=MODEL, max_tokens=MAX_TOKENS,
                messages=[{"role": "user",
                           "content": prompt.encode("utf-8", "replace").decode("utf-8")}]
            )
            for block in resp.content:
                if hasattr(block, 'text'):
                    return block.text
            return resp.content[0].text
        except Exception as e:
            if attempt < 2:
                time.sleep(2 ** attempt)
            else:
                raise


def clean_output(text: str) -> str:
    text = text.strip()
    text = re.sub(r'^```(?:yaml|markdown)?\s*\n', '', text)
    text = re.sub(r'\n```\s*$', '', text)
    return text


# ── 单文件提炼 ───────────────────────────────────────────────────────────────

def fix_frontmatter_domain(text: str, correct_domain: str) -> str:
    """更新 frontmatter 中的 domain 和 updated 字段"""
    def replacer(m):
        block = m.group(1)
        block = re.sub(r'^domain:.*$', f'domain: {correct_domain}', block, flags=re.MULTILINE)
        block = re.sub(r'^updated:.*$', f'updated: {TODAY}', block, flags=re.MULTILINE)
        if not re.search(r'^updated:', block, re.MULTILINE):
            block = block.rstrip() + f'\nupdated: {TODAY}'
        return f'---\n{block}\n---'
    return re.sub(r'---\n(.*?)\n---', replacer, text, count=1, flags=re.DOTALL)


def strip_existing_sections(text: str) -> str:
    """移除已有的关联代码/关联文档/实现备注章节（重新生成）"""
    return re.sub(
        r'\n#{1,3}\s*(?:关联代码|关联文档|实现备注)[\s\S]*?(?=\n#{1,3}\s+(?!(?:关联代码|关联文档|实现备注))|$)',
        '',
        text
    ).rstrip()


def enrich_one(client, fpath: Path,
               code_idx: dict, kw_idx: dict, ep_idx: dict,
               doc_idx: dict) -> None:
    original = fpath.read_text(encoding="utf-8", errors="replace")
    fm       = parse_frontmatter(original)

    # domain from directory structure: domains/{域名}/{doc_type}/{file}.md
    dir_domain = fpath.parent.parent.name
    title      = fm.get("title", fpath.stem)
    doc_type   = fm.get("type", fpath.parent.name)

    # 额外 frontmatter 信息（如 path/method/service）
    extra_fields = []
    for field in ("path", "method", "service"):
        if fm.get(field):
            extra_fields.append(f"{field}: {fm[field]}")
    fm_extra = "\n".join(extra_fields)

    # ── 找代码片段 ──
    snippets = find_code_snippets(dir_domain, fm, title, code_idx, kw_idx, ep_idx)
    if snippets:
        code_str = "\n\n".join(
            f"**{s['file_str']}**\n"
            f"@Desc: {', '.join(s['descs'][:3]) or '—'}\n"
            f"```java\n{s['skeleton'][:1200]}\n```"
            for s in snippets
        )
    else:
        code_str = "（未找到直接对应的代码文件）"

    # ── 找关联文档 ──
    related = find_related_docs(fpath, title, dir_domain, doc_idx)
    related_str = "\n".join(
        f"- [{r['title']}]({r['path']}) — {r['domain']}"
        for r in related
    ) or "（无）"

    prompt = APPEND_PROMPT.format(
        title=title,
        domain=dir_domain,
        doc_type=doc_type,
        frontmatter_extra=fm_extra,
        code_snippets=code_str[:2500],
        related_docs=related_str[:800],
    )

    appended = call_claude(client, prompt)
    appended = clean_output(appended)

    # 修正 frontmatter domain/updated，移除旧关联章节，追加新章节
    body = fix_frontmatter_domain(original, dir_domain)
    body = strip_existing_sections(body)
    body = body.rstrip() + "\n\n" + appended.strip() + "\n"

    fpath.write_text(body, encoding="utf-8")


# ── 统计 ─────────────────────────────────────────────────────────────────────

def print_stats(domain_filter=None, type_filter=None):
    from collections import Counter
    files    = get_kb_files(domain_filter, type_filter)
    progress = load_json(PROGRESS)
    done     = sum(1 for f in files
                   if progress.get(str(f.relative_to(DOMAINS_DIR))) == "done")
    total    = len(files)
    # Count by domain from directory structure
    domain_cnt = Counter(f.parent.parent.name for f in files)
    print(f"待处理: {total} | 已完成: {done} | 剩余: {total - done}")
    for d, c in domain_cnt.most_common():
        done_d = sum(1 for f in files
                     if f.parent.parent.name == d
                     and progress.get(str(f.relative_to(DOMAINS_DIR))) == "done")
        print(f"  {d:20s} {done_d:3d}/{c:3d}")


# ── 主流程 ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="知识库深度提炼")
    parser.add_argument("--stats",  action="store_true", help="查看进度统计")
    parser.add_argument("--domain", help="只处理指定域")
    parser.add_argument("--type",   help="只处理指定文档类型（如 需求文档、业务文档、业务规则）")
    args = parser.parse_args()

    if args.stats:
        print_stats(args.domain, args.type)
        return

    progress = load_json(PROGRESS)
    workers = cfg.get_global_config().parallel_workers

    all_files = get_kb_files()
    log(f"构建文档索引（{len(all_files)} 个文件）...")
    doc_idx = build_doc_index(all_files)

    code_idx, kw_idx, ep_idx = build_code_index()

    files = get_kb_files(args.domain, args.type)
    # 过滤已完成
    to_run = []
    skip = 0
    for fpath in files:
        key = str(fpath.relative_to(DOMAINS_DIR))
        if progress.get(key) == "done":
            skip += 1
        else:
            to_run.append(fpath)
    total = len(files)

    log(f"共 {total} 个文件，已完成 {skip}，待处理 {len(to_run)}（并行 {workers} workers）")

    progress_lock = threading.Lock()
    log_lock = threading.Lock()
    done = skip
    errs = 0

    def _process_one(fpath: Path) -> bool:
        nonlocal done, errs
        worker_client = (anthropic.Anthropic(api_key=_AUTH_TOKEN, base_url=_BASE_URL)
                         if _BASE_URL else anthropic.Anthropic())
        key = str(fpath.relative_to(DOMAINS_DIR))
        try:
            fm = parse_frontmatter(fpath.read_text(encoding="utf-8", errors="replace")[:400])
            title = fm.get("title", fpath.stem)
            dom = fpath.parent.parent.name
            with log_lock:
                log(f"  {title[:45]} ({dom}/{fpath.parent.name})")
            enrich_one(worker_client, fpath, code_idx, kw_idx, ep_idx, doc_idx)
            with progress_lock:
                progress[key] = "done"
                done += 1
            return True
        except Exception as e:
            with progress_lock:
                progress[key] = f"error:{e}"
                errs += 1
            with log_lock:
                log(f"    [失败] {key}: {e}")
            return False

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_process_one, fp): fp for fp in to_run}
        completed = 0
        for future in as_completed(futures):
            completed += 1
            future.result()  # propagate exceptions if any
            if completed % 20 == 0:
                with progress_lock:
                    save_json(PROGRESS, progress)
                    log(f"  --- 进度 {done}/{total} | 失败:{errs} ---")

    save_json(PROGRESS, progress)
    log(f"=== 完成 === 共:{total} 完成:{done} 失败:{errs}")


if __name__ == "__main__":
    log(f"===== 启动 {TODAY} =====")
    main()
