# Tools 说明

> Ewan-kb 的构建工具集。

## 架构概览

```
source/           ──discover──→  domains/         ──extract+enrich──→  knowledgeBase/  ──graphify──→  graph/
(code + raw docs)                (domain defs)                         (AI-refined)                    (queryable)
```

## 构建流水线 (ewankb knowledgebase)

7 步流水线，所有中间产物在 `domains/` 下工作，最后搬迁到 `knowledgeBase/`：

| 步骤 | 脚本 | 输入 | 输出 |
|------|------|------|------|
| 1. 域发现 | `discover_domains.py` | `source/repos/` Java 代码 | `domains/_meta/domains.json` |
| 2. 代码分析 | `analyze_code.py` | `source/repos/` + `domains.json` | `code_analysis.json` |
| 3a. 文档提炼 | `extract_to_kb.py` | `source/docs/` Confluence MD | `domains/{域名}/{doc_type}/` |
| 3b. 代码模块说明 | `gen_code_module_docs.py` | `code_analysis.json` | `domains/{域名}/代码模块说明/` |
| 4. 深度提炼 | `enrich_kb.py` | `domains/{域名}/{doc_type}/` + `source/repos/` | 原地追加关联代码/文档/备注 |
| 5. 域概览 | `gen_domain_overview.py` | `domains/{域名}/` 全部文档 | `domains/{域名}/README.md` |
| 6. 流程文档 | `gen_processes.py` | `domains/{域名}/` 全部文档 | `domains/{域名}/PROCESSES.md` |
| 7. 搬迁 | `migrate_to_kb.py` | `domains/{域名}/{doc_type}/` | `knowledgeBase/{doc_type}/` + 更新 README 路径 |

## 工具目录

| 目录 | 用途 |
|------|------|
| `build_graph/` | 封装 graphify 库，从 source + domains 构建 graph.json |
| `graph_runtime/` | 图查询运行时 (BFS/DFS 遍历) + 知识库直接查询 |
| `extract_kb/` | 文档提炼脚本套件（域发现、代码分析、文档提炼、enrich、概览、流程、搬迁） |
| `fetch_repos/` | 代码仓库拉取 (可选) |
| `fetch_db_schema/` | 数据库表结构拉取 (可选) |
| `scrape_cf/` | Confluence 文档爬取 (可选) |
| `text_utils.py` | 公共文本工具（parse_frontmatter、extract_keywords） |

## 配置体系

| 文件 | 作用 |
|------|------|
| `~/.config/ewankb/ewankb.toml` | 全局默认配置 |
| `project_config.json` | 项目配置（域定义、分类规则） |
| `config_loader.py` | 配置加载器 |
