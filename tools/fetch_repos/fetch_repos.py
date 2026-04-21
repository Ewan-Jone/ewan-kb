#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
代码仓库拉取工具

用法：
  python fetch_repos.py              # 克隆/更新所有仓库
  python fetch_repos.py --update     # 只更新已存在的仓库（不克隆新的）
  python fetch_repos.py --only fe-ils logistics-gls  # 只处理指定仓库
  python fetch_repos.py --list       # 列出配置中的仓库，不执行操作

配置文件：repos.json（同目录下）
  - output_dir：仓库存放目录（相对于本脚本所在目录，默认 repos/）
  - repos：仓库列表，每项含 name / url / branch / description
"""

import json
import subprocess
import sys
import argparse
import urllib.parse
from pathlib import Path
from datetime import datetime

# ── 配置 ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR  = Path(__file__).resolve().parent
CONFIG_FILE = SCRIPT_DIR / "repos.json"


def load_git_credentials() -> tuple[str, str]:
    """从 .env 读取 GIT_USER / GIT_PASSWORD，返回 (user, password)。未配置则返回空串。"""
    env_candidates = [
        SCRIPT_DIR.parent.parent / ".env",   # 项目根目录
        SCRIPT_DIR / ".env",                  # 本目录
    ]
    user, password = "", ""
    for env_path in env_candidates:
        if not env_path.exists():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip()
            if k == "GIT_USER":
                user = v
            elif k == "GIT_PASSWORD":
                password = v
    return user, password


def inject_credentials(url: str, user: str, password: str) -> str:
    """将凭证注入 https URL（运行时使用，不持久化）。"""
    if not user or not url.startswith("https://"):
        return url
    encoded_user = urllib.parse.quote(user, safe="")
    encoded_pass = urllib.parse.quote(password, safe="") if password else ""
    # https://host/path -> https://user:pass@host/path
    return url.replace("https://", f"https://{encoded_user}:{encoded_pass}@", 1)

# ── 工具函数 ──────────────────────────────────────────────────────────────────

def log(msg: str, level: str = "INFO"):
    prefix = {"INFO": "[+]", "WARN": "[!]", "ERR ": "[x]", "SKIP": "[-]"}.get(level, "[.]")
    print(f"{prefix} {msg}", flush=True)


def run(cmd: list[str], cwd: Path = None) -> tuple[int, str, str]:
    """执行命令，返回 (returncode, stdout, stderr)。"""
    result = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        print(f"[x] 配置文件不存在：{CONFIG_FILE}")
        sys.exit(1)
    with open(CONFIG_FILE, encoding="utf-8") as f:
        return json.load(f)


def get_output_dir(config: dict) -> Path:
    rel = config.get("output_dir", "repos")
    out = SCRIPT_DIR / rel
    out.mkdir(parents=True, exist_ok=True)
    return out


def get_current_branch(repo_path: Path) -> str:
    code, out, _ = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_path)
    return out if code == 0 else "unknown"


def get_last_commit(repo_path: Path) -> str:
    code, out, _ = run(
        ["git", "log", "-1", "--format=%h %s (%cr)"], cwd=repo_path
    )
    return out if code == 0 else ""


# ── 核心操作 ──────────────────────────────────────────────────────────────────

def clone_repo(url: str, dest: Path, branch: str) -> bool:
    """克隆仓库，返回是否成功。"""
    log(f"克隆 {dest.name}  ({url})")
    cmd = ["git", "clone", "--branch", branch, "--single-branch", url, str(dest)]
    code, _, err = run(cmd)
    if code != 0:
        # 可能 branch 名称不对，尝试不指定分支直接克隆
        log(f"  指定分支 {branch} 失败，尝试默认分支…", "WARN")
        cmd = ["git", "clone", url, str(dest)]
        code, _, err = run(cmd)
    if code == 0:
        branch_now = get_current_branch(dest)
        commit = get_last_commit(dest)
        log(f"  克隆成功  分支:{branch_now}  最新提交: {commit}")
        return True
    else:
        log(f"  克隆失败: {err[:200]}", "ERR ")
        return False


def update_repo(repo_path: Path, branch: str) -> bool:
    """拉取最新代码，返回是否成功。"""
    log(f"更新 {repo_path.name}")
    branch_now = get_current_branch(repo_path)

    # 切换到目标分支（如果当前不是）
    if branch_now != branch:
        code, _, err = run(["git", "checkout", branch], cwd=repo_path)
        if code != 0:
            log(f"  切换分支 {branch} 失败，保持 {branch_now}: {err[:100]}", "WARN")

    code, out, err = run(["git", "pull", "--ff-only"], cwd=repo_path)
    if code == 0:
        if "Already up to date" in out or "已经是最新" in out:
            log(f"  已是最新，无需更新", "SKIP")
        else:
            commit = get_last_commit(repo_path)
            log(f"  更新成功  最新提交: {commit}")
        return True
    else:
        log(f"  更新失败: {err[:200]}", "ERR ")
        return False


# ── 主流程 ────────────────────────────────────────────────────────────────────

def process(repos: list[dict], output_dir: Path, update_only: bool) -> dict:
    results = {"ok": [], "skip": [], "fail": []}
    git_user, git_pass = load_git_credentials()
    if git_user:
        log(f"已加载 Git 凭证（用户: {git_user}）")

    for repo in repos:
        name   = repo["name"]
        url    = inject_credentials(repo["url"], git_user, git_pass)
        branch = repo.get("branch", "master")
        dest   = output_dir / name

        if dest.exists():
            ok = update_repo(dest, branch)
            (results["ok"] if ok else results["fail"]).append(name)
        elif update_only:
            log(f"跳过 {name}（不存在，--update 模式不克隆）", "SKIP")
            results["skip"].append(name)
        else:
            ok = clone_repo(url, dest, branch)
            (results["ok"] if ok else results["fail"]).append(name)

    return results


def print_summary(results: dict, output_dir: Path):
    print()
    print("─" * 50)
    print(f"完成  成功:{len(results['ok'])}  跳过:{len(results['skip'])}  失败:{len(results['fail'])}")
    if results["ok"]:
        print(f"  成功: {', '.join(results['ok'])}")
    if results["fail"]:
        print(f"  失败: {', '.join(results['fail'])}")
    print(f"输出目录: {output_dir}")
    print("─" * 50)


# ── 入口 ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="代码仓库拉取工具")
    parser.add_argument("--update",  action="store_true", help="只更新已存在的仓库")
    parser.add_argument("--only",    nargs="+", metavar="NAME", help="只处理指定名称的仓库")
    parser.add_argument("--list",    action="store_true", help="列出配置中的仓库")
    args = parser.parse_args()

    config     = load_config()
    output_dir = get_output_dir(config)
    all_repos  = config.get("repos", [])

    if args.list:
        print(f"配置文件: {CONFIG_FILE}")
        print(f"输出目录: {output_dir}")
        print(f"共 {len(all_repos)} 个仓库：")
        for r in all_repos:
            exists = "✓" if (output_dir / r["name"]).exists() else " "
            print(f"  [{exists}] {r['name']:20s}  {r.get('description','')}  ({r['url']})")
        return

    # 过滤
    if args.only:
        name_set = set(args.only)
        repos = [r for r in all_repos if r["name"] in name_set]
        missing = name_set - {r["name"] for r in repos}
        if missing:
            log(f"配置中不存在以下仓库名：{', '.join(missing)}", "WARN")
    else:
        repos = all_repos

    if not repos:
        log("没有可处理的仓库", "WARN")
        return

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 开始处理 {len(repos)} 个仓库")
    print()

    results = process(repos, output_dir, update_only=args.update)
    print_summary(results, output_dir)


if __name__ == "__main__":
    main()
