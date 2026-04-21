#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
代码模块说明生成脚本

为每个域的代码模块生成结构化说明文档，写入 domains/{域名}/代码模块说明/。
依赖 code_analysis.json（由 analyze_code.py 生成）和 domains.json 中的模块映射。

用法：
  python gen_code_module_docs.py                # 全量生成（跳过已完成）
  python gen_code_module_docs.py --force        # 强制重新生成
  python gen_code_module_docs.py --domain 合同管理  # 只处理某域
"""
import os, sys, re, json, time, argparse
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
from datetime import datetime
import anthropic

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools import config_loader as cfg

BASE_DIR    = cfg.get_kb_dir()
DOMAINS_DIR = cfg.get_domains_dir()
REPOS       = cfg.get_repos_dir()
CODE_ANALYSIS = cfg.get_knowledge_base_dir() / "_state" / "code_analysis.json"
PROGRESS    = cfg.get_knowledge_base_dir() / "_state" / "code_module_progress.json"
TODAY       = datetime.now().strftime("%Y-%m-%d")

gcfg        = cfg.get_global_config()
pcfg        = cfg.get_project_config()
_AUTH_TOKEN = pcfg.get("api_key") or gcfg.api_key
_BASE_URL   = pcfg.get("base_url") or gcfg.base_url
MODEL       = pcfg.get("model") or gcfg.default_model
MAX_TOKENS  = 3000
_SYSTEM_NAME = pcfg.get("system_name", "业务系统")

SKIP_DOMAINS = cfg.get_skip_domains()


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def load_json(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def save_json(p: Path, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


CODE_PROMPT = f"""\
你是{_SYSTEM_NAME}的知识库整理助手。请根据以下代码模块信息，生成一份结构化的代码模块说明文档。

系统：{_SYSTEM_NAME}
域：{{domain}}
模块目录：{{module}}

数据库表（{{table_count}}张）：
{{tables}}

核心Service类（共{{service_count}}个）：
{{services}}

关键接口路径：
{{endpoints}}

输出要求（标准Markdown，开头含YAML frontmatter，不要用代码块包裹frontmatter）：
---
domain: {{domain}}
type: 代码模块说明
title: {{module}}模块代码说明
source: 代码仓库
status: active
updated: {{today}}
---

## 模块职责
（一句话说明该模块负责什么业务）

## 数据库表清单
（所有表名及其简要说明，按业务分组）

## 核心服务类
（列出主要Service，说明其职责，每个一行）

## 关键业务规则
（从Service名称和表结构推断该模块的核心业务约束，3-8条）

## 与其他模块的关联
（该模块依赖哪些模块，被哪些模块调用）
"""


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


def main():
    parser = argparse.ArgumentParser(description="生成代码模块说明文档")
    parser.add_argument("--domain", help="只处理指定域")
    parser.add_argument("--force", action="store_true", help="强制重新生成")
    args = parser.parse_args()

    code_data = load_json(CODE_ANALYSIS)
    if not code_data:
        log("code_analysis.json 不存在或为空，跳过代码模块说明生成")
        return

    progress = load_json(PROGRESS)
    client = (anthropic.Anthropic(api_key=_AUTH_TOKEN, base_url=_BASE_URL)
              if _BASE_URL else anthropic.Anthropic())

    # 从 domains.json 获取每个域的 modules 映射
    domains_data = cfg._load_domains_json()
    all_domains = domains_data.get("domains", {})

    total = 0
    done = 0
    errs = 0

    for domain_name, domain_info in all_domains.items():
        if domain_name in SKIP_DOMAINS or domain_name == "待分类":
            continue
        if args.domain and domain_name != args.domain:
            continue

        modules = domain_info.get("modules", [])
        if not modules:
            continue

        for module_name in modules:
            total += 1
            key = f"code:{domain_name}:{module_name}"
            if not args.force and progress.get(key) == "done":
                done += 1
                continue

            # 从 code_analysis.json 中查找模块数据
            mod_data = {}
            for repo_name, repo_mods in code_data.items():
                if module_name in repo_mods:
                    mod_data = repo_mods[module_name]
                    break

            tables = mod_data.get("tables", [])
            services = mod_data.get("services", [])
            endpoints = mod_data.get("endpoints", [])

            log(f"  生成 {domain_name}/{module_name}")

            prompt = CODE_PROMPT.format(
                domain=domain_name,
                module=module_name,
                table_count=len(tables),
                tables="\n".join(f"- {t}" for t in tables[:30]) or "（无）",
                service_count=len(services),
                services="\n".join(f"- {s}" for s in services[:15]) or "（无）",
                endpoints="\n".join(f"- {e}" for e in endpoints[:15]) or "（无）",
                today=TODAY,
            )

            try:
                output = call_claude(client, prompt)
                output = re.sub(r"^```yaml\s*\n", "", output.strip())
                output = re.sub(r"\n```\s*$", "", output)

                out_dir = DOMAINS_DIR / domain_name / "代码模块说明"
                out_dir.mkdir(parents=True, exist_ok=True)
                safe_name = re.sub(r'[\\/:*?"<>|]', "_", module_name)
                out_path = out_dir / f"{safe_name}.md"
                out_path.write_text(output, encoding="utf-8")
                log(f"    -> {domain_name}/代码模块说明/{out_path.name}")

                progress[key] = "done"
                done += 1
            except Exception as e:
                log(f"    [失败] {e}")
                progress[key] = f"error:{e}"
                errs += 1

            save_json(PROGRESS, progress)

    log(f"=== 代码模块说明生成完成 === 总计:{total} 完成:{done} 失败:{errs}")


if __name__ == "__main__":
    main()
