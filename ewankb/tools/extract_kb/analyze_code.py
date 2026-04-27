#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
代码分析工具 - 提取各模块的表清单、核心接口、Service类名

从 source/repos/ 扫描 Java 仓库，输出 code_analysis.json。
不调用 AI，纯静态分析。

用法：
  python analyze_code.py                # 分析所有仓库
  python analyze_code.py --stats        # 只查看已有分析结果
"""
import sys, re, json, argparse
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
from collections import defaultdict

from .. import config_loader as cfg

REPOS = cfg.get_repos_dir()
OUT   = cfg.get_knowledge_base_dir() / "_state" / "code_analysis.json"


def extract_tables(sql_dir: Path) -> dict:
    """从 SQL 文件中提取 模块->表列表 映射"""
    mod_tables = defaultdict(set)
    if not sql_dir.exists():
        return {}
    for sql_file in sorted(sql_dir.rglob("*.sql")):
        content = sql_file.read_text(encoding="utf-8", errors="replace")
        tables = re.findall(
            r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"]?(\w+)[`\"]?\s*\(",
            content, re.IGNORECASE
        )
        if tables:
            mod = sql_file.relative_to(sql_dir).parts[0] if len(sql_file.relative_to(sql_dir).parts) > 1 else sql_file.stem
            mod_tables[mod].update(tables)
    return {k: sorted(v) for k, v in mod_tables.items()}


def extract_rest_endpoints(java_root: Path, module: str) -> list:
    """扫描 @RequestMapping / @PostMapping 等注解，提取接口路径"""
    endpoints = []
    sep = "/" + module + "/"
    java_files = [f for f in java_root.rglob("*.java")
                  if sep in str(f).replace("\\", "/")]
    for jf in java_files:
        try:
            content = jf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        class_maps = re.findall(r'@RequestMapping\(["\']([^"\']+)["\']', content)
        class_prefix = class_maps[0] if class_maps else ""
        method_maps = re.findall(
            r'@(Get|Post|Put|Delete|Request)Mapping\(["\']([^"\']+)["\']', content
        )
        for method, path in method_maps:
            full = (class_prefix + path).replace("//", "/")
            endpoints.append(f"[{method.upper()}] {full}")
    return list(dict.fromkeys(endpoints))[:30]


def extract_service_names(java_root: Path, module: str) -> list:
    """提取模块内的 Service 类名"""
    sep = "/" + module + "/"
    return sorted(set(
        f.stem for f in java_root.rglob("*.java")
        if sep in str(f).replace("\\", "/")
        and "Service" in f.stem
        and "Test" not in f.stem
        and "Feign" not in f.stem
    ))[:20]


def analyze_repo(repo_dir: Path, modules: list[str]) -> dict:
    java_root = repo_dir
    sql_dir = repo_dir / "sql"
    tables_by_mod = extract_tables(sql_dir)

    result = {}
    for mod in modules:
        endpoints = extract_rest_endpoints(java_root, mod)
        services = extract_service_names(java_root, mod)
        tables = tables_by_mod.get(mod, [])

        java_files = sum(
            1 for f in java_root.rglob("*.java")
            if ("/" + mod + "/") in str(f).replace("\\", "/")
        )

        result[mod] = {
            "java_files": java_files,
            "services": services,
            "tables": tables,
            "endpoints": endpoints,
        }
    return result


def analyze_all() -> dict:
    """扫描 source/repos/ 下所有仓库，使用 domains.json 中的 modules 信息。"""
    if not REPOS.exists():
        print("source/repos/ 不存在，跳过代码分析")
        return {}

    # 从 domains.json 收集所有模块名
    domains_data = cfg._load_domains_json()
    all_modules = set()
    for info in domains_data.get("domains", {}).values():
        all_modules.update(info.get("modules", []))

    if not all_modules:
        print("domains.json 中无模块信息，跳过代码分析")
        return {}

    result = {}
    for repo_dir in REPOS.iterdir():
        if not repo_dir.is_dir() or repo_dir.name.startswith("."):
            continue
        # 找该仓库下存在的模块
        repo_modules = []
        for mod in all_modules:
            # modules 路径可能以仓库名开头（如 "my-service/my-application/..."）
            # 在仓库目录内搜索时需要去掉仓库名前缀
            inner = mod[len(repo_dir.name) + 1:] if mod.startswith(repo_dir.name + "/") else mod
            mod_path = repo_dir / inner
            if mod_path.exists() and mod_path.is_dir():
                repo_modules.append(mod)
        if not repo_modules:
            continue
        print(f"分析 {repo_dir.name} ({len(repo_modules)} 模块)...")
        result[repo_dir.name] = analyze_repo(repo_dir, repo_modules)
    return result


def print_stats():
    if not OUT.exists():
        print("code_analysis.json 不存在，请先运行代码分析")
        return
    data = json.loads(OUT.read_text(encoding="utf-8"))
    for repo_name, mods in data.items():
        print(f"\n=== {repo_name} ===")
        for mod, info in mods.items():
            print(f"  {mod}: {info['java_files']}个Java, "
                  f"{len(info['services'])}个Service, "
                  f"{len(info['tables'])}张表, "
                  f"{len(info['endpoints'])}个接口")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="代码分析工具")
    parser.add_argument("--stats", action="store_true", help="查看已有分析结果")
    args = parser.parse_args()

    if args.stats:
        print_stats()
    else:
        result = analyze_all()
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n结果写入: {OUT}")
        for repo_name, mods in result.items():
            print(f"\n=== {repo_name} ===")
            for mod, info in mods.items():
                print(f"  {mod}: {info['java_files']}个Java, "
                      f"{len(info['services'])}个Service, "
                      f"{len(info['tables'])}张表, "
                      f"{len(info['endpoints'])}个接口")
