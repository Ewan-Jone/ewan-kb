"""`ewankb update` — Incremental update: detect source changes, rebuild affected domains only."""

import os
from argparse import Namespace

from ._helpers import resolve_kb_dir


def run(args):
    kb_dir = resolve_kb_dir()
    os.chdir(kb_dir)

    from ewankb.tools.incremental import diff, clean

    # Step 1: Detect changes
    print("检测源数据变更...")
    result = diff()

    if not result["has_changes"]:
        print("源数据无变化，无需更新。")
        return

    # Step 2: Show changes
    changes = result["changes"]
    for cat in ("repos", "docs"):
        c = changes[cat]
        if any(c.values()):
            print(f"\n{cat}:")
            if c["added"]:
                print(f"  新增: {len(c['added'])} 个文件")
                for f in c["added"][:5]:
                    print(f"    + {f}")
                if len(c["added"]) > 5:
                    print(f"    ... 共 {len(c['added'])} 个")
            if c["modified"]:
                print(f"  修改: {len(c['modified'])} 个文件")
                for f in c["modified"][:5]:
                    print(f"    ~ {f}")
                if len(c["modified"]) > 5:
                    print(f"    ... 共 {len(c['modified'])} 个")
            if c["deleted"]:
                print(f"  删除: {len(c['deleted'])} 个文件")
                for f in c["deleted"][:5]:
                    print(f"    - {f}")
                if len(c["deleted"]) > 5:
                    print(f"    ... 共 {len(c['deleted'])} 个")

    affected = result["affected_domains"]
    if not affected:
        print(
            "\n无法确定受影响的域（可能是新增模块/文档无映射记录），"
            "建议运行 ewankb rebuild && ewankb build 进行全量构建。"
        )
        return

    print(f"\n受影响的域 ({len(affected)}): {', '.join(affected)}")

    # Step 3: Clean affected domains (delete artifacts + clear progress entries)
    print(f"\n清理受影响域的产物...")
    clean_result = clean(affected)
    print(
        f"  删除 {clean_result['files_deleted']} 个文件, "
        f"清除 {clean_result['progress_entries_cleared']} 条进度记录"
    )

    # Step 4: Re-run knowledgebase pipeline
    # Pipeline steps use progress.json to skip already-processed items,
    # so only cleaned domains will be re-processed by the heavy LLM steps.
    from .knowledgebase_cmd import run as run_knowledgebase

    run_knowledgebase(Namespace(skip_discover=False))

    # Step 5: Rebuild graph
    print("\n重建图谱...")
    from .build_graph_cmd import run as run_build_graph

    run_build_graph(Namespace())

    print("\n=== 增量更新完成 ===")
