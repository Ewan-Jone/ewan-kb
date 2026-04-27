#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
增量构建支持 — 内容 hash 缓存 + 变更检测 + 域影响映射 + 选择性清理

用法：
  python -m tools.incremental diff           # 检测变更，打印受影响的域
  python -m tools.incremental clean <域1> <域2>  # 清理指定域的输出（准备重跑）
  python -m tools.incremental update-hash    # 更新 hash 缓存（构建成功后调用）
"""
import hashlib
import json
import shutil
import sys
from pathlib import Path

from . import config_loader as cfg


# ── 路径 ──────────────────────────────────────────────────────────────────────

def _get_dirs():
    kb_dir = cfg.get_kb_dir()
    return {
        "kb": kb_dir,
        "repos": kb_dir / "source" / "repos",
        "docs": kb_dir / "source" / "docs",
        "cache": kb_dir / "source" / ".cache",
        "domains": kb_dir / "domains",
        "knowledge_base": kb_dir / "knowledgeBase",
    }


HASH_FILE = "hashes.json"
DOC_MAPPING_FILE = "doc_domain_mapping.json"


# ── Hash 计算 ─────────────────────────────────────────────────────────────────

def _file_hash(path: Path) -> str:
    """计算文件的 SHA-256 hash"""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            while chunk := f.read(8192):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


def scan_source_hashes(dirs: dict) -> dict:
    """扫描 source/repos/ 和 source/docs/ 下所有文件，返回 {相对路径: hash}"""
    result = {"repos": {}, "docs": {}}

    repos_dir = dirs["repos"]
    if repos_dir.exists():
        for f in sorted(repos_dir.rglob("*")):
            if not f.is_file():
                continue
            # 跳过 .git 目录下的文件
            rel = f.relative_to(repos_dir)
            if ".git" in rel.parts:
                continue
            # 只关注代码文件
            if f.suffix in (".java", ".xml", ".sql", ".properties", ".yml", ".yaml", ".json"):
                result["repos"][str(rel).replace("\\", "/")] = _file_hash(f)

    docs_dir = dirs["docs"]
    if docs_dir.exists():
        for f in sorted(docs_dir.rglob("*.md")):
            if not f.is_file():
                continue
            rel = f.relative_to(docs_dir)
            # 跳过 .cache 目录
            if ".cache" in rel.parts:
                continue
            result["docs"][str(rel).replace("\\", "/")] = _file_hash(f)

    return result


def load_cached_hashes(dirs: dict) -> dict:
    """读取缓存的 hash"""
    hf = dirs["cache"] / HASH_FILE
    if hf.exists():
        try:
            return json.loads(hf.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"repos": {}, "docs": {}}


def save_hashes(dirs: dict, hashes: dict):
    """保存 hash 缓存"""
    cache_dir = dirs["cache"]
    cache_dir.mkdir(parents=True, exist_ok=True)
    hf = cache_dir / HASH_FILE
    hf.write_text(json.dumps(hashes, ensure_ascii=False, indent=2), encoding="utf-8")


# ── 变更检测 ──────────────────────────────────────────────────────────────────

def detect_changes(dirs: dict) -> dict:
    """对比当前文件和缓存 hash，返回变更详情

    Returns:
        {
            "repos": {"added": [...], "modified": [...], "deleted": [...]},
            "docs":  {"added": [...], "modified": [...], "deleted": [...]},
            "has_changes": bool,
        }
    """
    current = scan_source_hashes(dirs)
    cached = load_cached_hashes(dirs)

    result = {}
    for category in ("repos", "docs"):
        cur = current.get(category, {})
        old = cached.get(category, {})

        added = sorted(set(cur.keys()) - set(old.keys()))
        deleted = sorted(set(old.keys()) - set(cur.keys()))
        modified = sorted(k for k in cur if k in old and cur[k] != old[k])

        result[category] = {
            "added": added,
            "modified": modified,
            "deleted": deleted,
        }

    result["has_changes"] = any(
        result[cat][change_type]
        for cat in ("repos", "docs")
        for change_type in ("added", "modified", "deleted")
    )
    return result


# ── 变更→域映射 ───────────────────────────────────────────────────────────────

def _find_module_root(rel_path: str) -> str | None:
    """从相对路径（相对于 source/repos/）推断模块根目录"""
    parts = rel_path.split("/")
    for i, p in enumerate(parts):
        if p == "src" and i + 2 < len(parts) and parts[i + 1] == "main" and parts[i + 2] == "java":
            return "/".join(parts[:i])
    # 如果没有标准 Maven 结构，取前两级
    if len(parts) > 2:
        return "/".join(parts[:2])
    return None


def map_changes_to_domains(changes: dict, dirs: dict) -> set[str]:
    """将变更文件映射到受影响的域

    代码变更：文件路径 → 模块根目录 → domains.json modules → 域
    文档变更：doc_domain_mapping.json 反向查询 → 域
    """
    affected = set()

    # 加载 domains.json 的 module→domain 映射
    domains_data = cfg._load_domains_json()
    all_domains = domains_data.get("domains", {})

    # 构建 module→domain 反向映射
    module_to_domains: dict[str, list[str]] = {}
    for domain_name, info in all_domains.items():
        for mod in info.get("modules", []):
            module_to_domains.setdefault(mod, []).append(domain_name)

    # 代码变更 → 域
    for rel_path in (changes["repos"]["added"] + changes["repos"]["modified"] + changes["repos"]["deleted"]):
        mod_root = _find_module_root(rel_path)
        if mod_root:
            # 精确匹配
            if mod_root in module_to_domains:
                affected.update(module_to_domains[mod_root])
            else:
                # 前缀匹配：模块路径可能是 module_to_domains 中某个路径的前缀或子路径
                for mod_key, domains in module_to_domains.items():
                    if mod_root.startswith(mod_key + "/") or mod_key.startswith(mod_root + "/") or mod_key == mod_root:
                        affected.update(domains)

    # 文档变更 → 域（通过反向映射）
    doc_mapping = load_doc_domain_mapping(dirs)
    for rel_path in (changes["docs"]["added"] + changes["docs"]["modified"] + changes["docs"]["deleted"]):
        domains = doc_mapping.get(rel_path, [])
        affected.update(domains)

    # 文档新增但映射不存在时，无法确定域，标记为全量
    unmapped_docs = [
        p for p in changes["docs"]["added"]
        if p not in doc_mapping
    ]
    if unmapped_docs:
        # 新增文档没有映射记录，需要对这些文档重跑 extract
        # 但我们不知道它们会被分配到哪个域，所以暂时不加到 affected
        # extract 步骤的 progress.json 中不会有这些文件的记录，会自动处理
        pass

    return affected


# ── doc_domain_mapping ────────────────────────────────────────────────────────

def load_doc_domain_mapping(dirs: dict) -> dict:
    """加载文档→域的反向映射"""
    mf = dirs["cache"] / DOC_MAPPING_FILE
    if mf.exists():
        try:
            return json.loads(mf.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_doc_domain_mapping(dirs: dict, mapping: dict):
    """保存文档→域的反向映射"""
    cache_dir = dirs["cache"]
    cache_dir.mkdir(parents=True, exist_ok=True)
    mf = cache_dir / DOC_MAPPING_FILE
    mf.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")


def build_doc_domain_mapping_from_progress(dirs: dict) -> dict:
    """从 extract 的 progress.json 构建 doc→domain 反向映射

    progress.json 格式: {filename: "域名/doc_type/output_file.md"}
    映射格式: {filename: ["域名"]}（列表因为理论上同一文档可能被分配到多个域）
    """
    state_dir = dirs["knowledge_base"] / "_state"
    pf = state_dir / "progress.json"
    if not pf.exists():
        return {}

    try:
        progress = json.loads(pf.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}

    mapping = {}
    for filename, value in progress.items():
        if not isinstance(value, str) or value in ("done", "error") or ":" in value:
            continue
        # value 格式: "域名/doc_type/output_file.md"
        parts = value.split("/")
        if len(parts) >= 2:
            domain = parts[0]
            mapping.setdefault(filename, [])
            if domain not in mapping[filename]:
                mapping[filename].append(domain)

    return mapping


# ── 选择性清理 ────────────────────────────────────────────────────────────────

def clean_domain_outputs(domains: set[str], dirs: dict) -> dict:
    """清理指定域的生成产物，使流水线重新生成这些域

    清理内容：
    1. domains/{域名}/README.md
    2. domains/{域名}/PROCESSES.md
    3. domains/{域名}/{doc_type}/ 下由 extract 生成的文件（progress.json 中的记录）
    4. knowledgeBase/ 下对应的搬迁文件
    5. progress.json / enrich_progress.json / code_module_progress.json 中的相关记录

    Returns:
        {"files_deleted": int, "progress_entries_cleared": int, "domains": list}
    """
    domains_dir = dirs["domains"]
    kb_dir = dirs["knowledge_base"]
    state_dir = kb_dir / "_state"

    files_deleted = 0
    progress_cleared = 0

    # 1. 删除域级输出文件
    for domain in domains:
        domain_dir = domains_dir / domain
        if not domain_dir.exists():
            continue

        # README.md 和 PROCESSES.md
        for fname in ("README.md", "PROCESSES.md"):
            f = domain_dir / fname
            if f.exists():
                f.unlink()
                files_deleted += 1

        # 代码模块说明/
        code_mod_dir = domain_dir / "代码模块说明"
        if code_mod_dir.exists():
            shutil.rmtree(code_mod_dir)
            files_deleted += 1

    # 2. 清理 knowledgeBase/ 下该域的搬迁文件
    # migrate 将 domains/{域名}/{doc_type}/*.md → knowledgeBase/{doc_type}/*.md
    # 文件名格式: {page_id}_{title}.md，需要从 progress.json 得知哪些属于该域
    # 这里用一个更直接的方法：扫描 progress.json 找该域的文件

    # 3. 清理 progress 记录
    progress_files = {
        "progress.json": "extract",
        "enrich_progress.json": "enrich",
        "code_module_progress.json": "code_module",
    }

    for pf_name, step_name in progress_files.items():
        pf = state_dir / pf_name
        if not pf.exists():
            continue
        try:
            data = json.loads(pf.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        keys_to_remove = []
        for key, value in data.items():
            # extract progress: key=filename, value=output_path like "合同管理/需求文档/xxx.md"
            if step_name == "extract" and isinstance(value, str):
                for domain in domains:
                    if value.startswith(domain + "/"):
                        keys_to_remove.append(key)
                        # 也删除 domains/ 下的输出文件
                        output_file = domains_dir / value
                        if output_file.exists():
                            output_file.unlink()
                            files_deleted += 1
                        # 删除 knowledgeBase/ 下的搬迁文件
                        # 格式: domains/{域名}/{doc_type}/{file}.md → knowledgeBase/{doc_type}/{file}.md
                        parts = value.split("/")
                        if len(parts) >= 3:
                            kb_file = kb_dir / "/".join(parts[1:])  # 去掉域名前缀
                            if kb_file.exists():
                                kb_file.unlink()
                                files_deleted += 1
                        break

            # enrich progress: key=relative path like "合同管理/需求文档/xxx.md"
            elif step_name == "enrich":
                for domain in domains:
                    if key.startswith(domain + "/"):
                        keys_to_remove.append(key)
                        break

            # code_module progress: key=domain_name/module_name
            elif step_name == "code_module":
                for domain in domains:
                    if key.startswith(domain + "/") or key == domain:
                        keys_to_remove.append(key)
                        break

        if keys_to_remove:
            for k in keys_to_remove:
                del data[k]
            pf.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            progress_cleared += len(keys_to_remove)

    return {
        "files_deleted": files_deleted,
        "progress_entries_cleared": progress_cleared,
        "domains": sorted(domains),
    }


# ── 顶层 API ─────────────────────────────────────────────────────────────────

def diff() -> dict:
    """检测变更并返回受影响的域

    Returns:
        {
            "changes": {...},  # detect_changes 的结果
            "affected_domains": [...],
            "has_changes": bool,
        }
    """
    dirs = _get_dirs()
    changes = detect_changes(dirs)
    if not changes["has_changes"]:
        return {
            "changes": changes,
            "affected_domains": [],
            "has_changes": False,
        }

    affected = map_changes_to_domains(changes, dirs)
    return {
        "changes": changes,
        "affected_domains": sorted(affected),
        "has_changes": True,
    }


def clean(domains: list[str]) -> dict:
    """清理指定域的输出"""
    dirs = _get_dirs()
    return clean_domain_outputs(set(domains), dirs)


def update_hash():
    """更新 hash 缓存和 doc→domain 映射为当前状态"""
    dirs = _get_dirs()

    # 更新 hash 缓存
    hashes = scan_source_hashes(dirs)
    save_hashes(dirs, hashes)

    # 更新 doc→domain 映射（从 extract 的 progress.json 构建）
    doc_mapping = build_doc_domain_mapping_from_progress(dirs)
    save_doc_domain_mapping(dirs, doc_mapping)

    total = len(hashes.get("repos", {})) + len(hashes.get("docs", {}))
    return {"total_files": total, "doc_mappings": len(doc_mapping)}


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "diff":
        result = diff()
        if not result["has_changes"]:
            print("源数据无变化。")
        else:
            changes = result["changes"]
            for cat in ("repos", "docs"):
                c = changes[cat]
                if any(c.values()):
                    print(f"\n{cat}:")
                    if c["added"]:
                        print(f"  新增: {len(c['added'])} 个文件")
                    if c["modified"]:
                        print(f"  修改: {len(c['modified'])} 个文件")
                    if c["deleted"]:
                        print(f"  删除: {len(c['deleted'])} 个文件")
            print(f"\n受影响的域: {', '.join(result['affected_domains']) or '(无法确定，建议全量)'}")

    elif cmd == "clean":
        domains = sys.argv[2:]
        if not domains:
            print("用法: python -m tools.incremental clean <域1> <域2> ...")
            sys.exit(1)
        result = clean(domains)
        print(f"清理完成: 删除 {result['files_deleted']} 个文件, "
              f"清除 {result['progress_entries_cleared']} 条进度记录")
        print(f"域: {', '.join(result['domains'])}")

    elif cmd == "update-hash":
        result = update_hash()
        print(f"Hash 缓存已更新: {result['total_files']} 个文件")

    else:
        print(f"未知命令: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
