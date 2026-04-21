#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
文档搬迁脚本 — 从 domains/ 搬到 knowledgeBase/

将 domains/{域名}/{doc_type}/*.md 复制到 knowledgeBase/{doc_type}/，
然后更新 domains/{域名}/README.md 中的文档索引链接为搬迁后的路径。

搬迁规则：
  - 源：domains/{域名}/{doc_type}/{file}.md
  - 目标：knowledgeBase/{doc_type}/{file}.md
  - README 链接：从 "{doc_type}/{file}.md" 更新为 "../../knowledgeBase/{doc_type}/{file}.md"
  - "代码模块说明" 目录不搬迁（保留在 domains/ 下）

用法：
  python migrate_to_kb.py               # 执行搬迁
  python migrate_to_kb.py --dry-run     # 只预览，不实际搬迁
  python migrate_to_kb.py --domain 合同管理  # 只搬迁某个域
"""
import sys, shutil, argparse
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools import config_loader as cfg

DOMAINS_DIR = cfg.get_domains_dir()
KB_DIR      = cfg.get_knowledge_base_dir()
SKIP_DOMAINS = cfg.get_skip_domains()

# 这些目录不搬迁，保留在 domains/ 下
KEEP_IN_DOMAINS = {"代码模块说明", "_meta"}


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def migrate_domain(domain: str, dry_run: bool = False) -> tuple[int, int]:
    """搬迁一个域的文档，返回 (搬迁文件数, 更新链接数)"""
    domain_dir = DOMAINS_DIR / domain
    if not domain_dir.exists():
        return 0, 0

    migrated = 0
    # 收集所有需要搬迁的文件及其路径映射 (旧相对路径 -> 新相对路径)
    path_map = {}  # old_rel (from README) -> new_rel (from README)

    for dtype_dir in sorted(domain_dir.iterdir()):
        if not dtype_dir.is_dir() or dtype_dir.name.startswith("_"):
            continue
        if dtype_dir.name in KEEP_IN_DOMAINS:
            continue
        # 子域目录含 README.md，doc_type 目录不含，跳过子域
        if (dtype_dir / "README.md").exists():
            continue

        doc_type = dtype_dir.name
        target_dir = KB_DIR / doc_type

        for f in sorted(dtype_dir.glob("*.md")):
            if f.name in ("README.md", "PROCESSES.md"):
                continue

            target_file = target_dir / f.name
            # README 中旧的相对路径
            old_rel = f"{doc_type}/{f.name}"
            # 从 domains/{域名}/README.md 到 knowledgeBase/{doc_type}/{file}.md 的相对路径
            depth = domain.count("/") + 1  # 域路径深度
            prefix = "../" * (depth + 1) + "knowledgeBase/"
            new_rel = f"{prefix}{doc_type}/{f.name}"
            path_map[old_rel] = new_rel

            if not dry_run:
                target_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(f), str(target_file))
            migrated += 1

    # 更新 README.md 中的链接
    links_updated = 0
    readme = domain_dir / "README.md"
    if readme.exists() and path_map:
        text = readme.read_text(encoding="utf-8", errors="replace")
        new_text = text
        for old_rel, new_rel in path_map.items():
            # 替换 markdown 链接中的路径: ]({old_rel}) -> ]({new_rel})
            old_pattern = f"]({old_rel})"
            new_pattern = f"]({new_rel})"
            if old_pattern in new_text:
                new_text = new_text.replace(old_pattern, new_pattern)
                links_updated += 1
        if new_text != text and not dry_run:
            readme.write_text(new_text, encoding="utf-8")

    return migrated, links_updated


def main():
    parser = argparse.ArgumentParser(description="搬迁文档到 knowledgeBase")
    parser.add_argument("--domain", help="只搬迁指定域")
    parser.add_argument("--dry-run", action="store_true", help="只预览不执行")
    args = parser.parse_args()

    if not DOMAINS_DIR.exists():
        log("domains/ 目录不存在，跳过搬迁")
        return

    total_migrated = 0
    total_links = 0

    all_domains = cfg.get_domains()
    for domain in all_domains:
        if domain in SKIP_DOMAINS or domain == "待分类":
            continue
        if args.domain and domain != args.domain:
            continue

        migrated, links = migrate_domain(domain, args.dry_run)
        if migrated > 0:
            action = "预览" if args.dry_run else "搬迁"
            log(f"  {domain}: {action} {migrated} 个文件, 更新 {links} 个链接")
        total_migrated += migrated
        total_links += links

    action = "预览" if args.dry_run else "搬迁"
    log(f"=== {action}完成 === 文件:{total_migrated} 链接更新:{total_links}")


if __name__ == "__main__":
    main()
