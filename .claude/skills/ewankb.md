---
name: ewankb
description: 从 Java 后端代码 + Confluence 文档构建结构化业务知识库。
trigger: /ewankb
---

# /ewankb

四层架构知识库构建工具：`source/` → `domains/` → `knowledgeBase/` → `graph/`

## 命令路由

| 输入 | 动作 |
|------|------|
| `/ewankb` 或 `/ewankb <路径>` | 完整构建（preflight → discover → 模块映射 → build） |
| `/ewankb --build-kb` | 仅 domains + knowledgeBase（含 discover + 模块映射） |
| `/ewankb --build-kb --skip-discover` | 跳过 discover，从 analyze_code 开始执行剩余流水线 |
| `/ewankb --build-graph` | 跳到 [--build-graph 执行](#--build-graph-执行) |
| `/ewankb discover` | 仅重跑域发现 + 模块映射 |
| `/ewankb pull` | 跳到 [pull 执行](#pull-执行) |
| `/ewankb push` | 跳到 [push 执行](#push-执行) |
| `/ewankb diff` | 跳到 [diff 执行](#diff-执行) |

## 构建流程

### 第 1 步 — preflight 检查 + 自动修复

```bash
cd "目标路径"
ewankb preflight --fix --dir .
```

解析 JSON 输出：
- `ready: true` 且无 `config_created` → 继续第 2 步
- `blockers` 含 `no_java_files` → 告诉用户把 Java 代码放到 `source/repos/`，停止
- `blockers` 含 `no_api_key` → 通过对话询问用户 API key，然后用 Edit 工具写入 `project_config.json` 的 `api_key` 字段
- **`config_created: true`** → 这是首次初始化。**必须**调用 `AskUserQuestion` 展示 `config_values` 中的大模型配置（API Key 前缀、Base URL、Model），让用户选择"继续使用当前配置"或"修改配置"。如果用户选择修改，用 Edit 工具更新 `project_config.json` 对应字段后再继续

如果 `ewankb` 命令不存在，改用：
```bash
PYTHONPATH="$EWANKB_ROOT" python -m ewankb preflight --fix --dir .
```
其中 `EWANKB_ROOT` 通过 `python -c "import importlib,pathlib; s=importlib.util.find_spec('tools.config_loader'); print(pathlib.Path(s.origin).parent.parent) if s else None"` 获取。

### 第 2 步 — 域发现

```bash
ewankb discover
```

等待完成。此步会：
- 扫描 `source/repos/` 下的 Java 包路径，提取业务域 segments
- AI 翻译为中文域名，写入 `domains/_meta/domains.json`
- 生成 `domains/_meta/module_mapping_context.md`（模块映射上下文）

### 第 3 步 — 代码模块映射（AI 自主探索）

读取 `domains/_meta/module_mapping_context.md`，检查是否存在 modules 为空的域。

**如果存在待映射的域**，执行以下探索流程：

1. 阅读 `module_mapping_context.md` 中的目录树，初步判断每个域的代码可能在哪些目录下
2. 对不确定的目录，浏览其中的 Java 文件名和包声明（`package` 语句）来确认归属
3. 确定映射后，用 Edit 工具修改 `domains/_meta/domains.json`，填充对应域的 `modules` 字段

映射规则：
- `modules` 的值是目录路径列表（相对于 `source/repos/`）
- 微服务项目：通常是服务模块目录名（如 `contract-atomic-service`）
- 单体项目：通常是包路径中的业务子目录（如 `myapp/src/main/java/com/example/rest/contract`）
- 一个域可能对应多个目录，多个域也可能共享同一个大目录的不同子包
- 只修改 `modules` 字段，不动其他字段
- 找不到代码目录的域保留 `modules: []`

**如果所有域都已有 modules**，跳过此步。

### 第 4 步 — 执行剩余流水线

```bash
ewankb knowledgebase --skip-discover
```

此命令跳过域发现（第 2 步已完成），从代码分析开始执行：
analyze_code → extract → gen_code_module_docs → enrich → gen_overview → gen_processes → migrate

等待完成。

### 第 5 步 — 构建图谱

执行 [--build-graph 执行](#--build-graph-执行) 中的全部步骤（语义提取 + AST + 合并）。

### 第 6 步 — 汇报结果

告诉用户：
> 知识库构建完成。可用 `/ewankb push` 推送到远程仓库。
> 查询方式（使用 `/ewankb-query`）：
> - `/ewankb query "问题"` — 图谱查询
> - `/ewankb query-kb "问题"` — 文档直接查询
> - `/ewankb query-deep "问题"` — 双路对比查询

如果 `graph/domain_suggestions.json` 存在，读取 `data["suggestions"][:3]` 并展示前 3 条建议。

---

## --skip-discover 执行

当用户输入 `/ewankb --build-kb --skip-discover` 时：

1. 运行 preflight 检查（第 1 步）
2. 跳过第 2、3 步（discover 和模块映射）
3. 直接运行 `ewankb knowledgebase --skip-discover`（第 4 步）
4. 汇报结果（第 5 步）

---

## discover 单独执行

当用户输入 `/ewankb discover` 时，执行以下流程：

1. 运行 `ewankb discover`，等待完成
2. 读取 `domains/_meta/module_mapping_context.md`，按「第 3 步 — 代码模块映射」的规则完成 modules 填充
3. 告诉用户域发现和模块映射已完成，展示域列表

---

## pull 执行

拉取知识库和源码。

### 步骤 1 — 拉取 KB 仓库

```bash
cd "{kb_dir}"
git pull --rebase origin main
```

如果有冲突，告诉用户冲突文件列表，让用户决定如何处理。
如果尚未配置 remote，通过对话询问用户仓库地址，然后执行 `git remote add origin <地址>`。

### 步骤 2 — 同步源码仓库

读取 `source/repos/repos.json`（如果不存在，检查 `tools/fetch_repos/repos.json`），调用 fetch_repos 拉取/更新各代码仓库：

```bash
cd "{kb_dir}"
python tools/fetch_repos/fetch_repos.py
```

如果 `repos.json` 不存在，通过对话引导用户完成配置：
1. 询问用户有哪些代码仓库需要拉取（仓库名、git 地址、分支）
2. 根据用户回答，用 Write 工具生成 `source/repos/repos.json`（参考 `tools/fetch_repos/repos.template.json` 格式）
3. 生成后继续执行 fetch_repos

### 步骤 3 — 同步 Confluence 文档

读取 `source/docs/docs.json`，如果存在则拉取文档：

1. 通过对话询问用户 Confluence 账号和密码
2. 从 `docs.json` 读取 `base_url` 和所有 `roots[].page_id`，拼接为逗号分隔的 ID 串
3. 执行拉取（全量覆盖）：

```bash
cd "{kb_dir}"
CONFLUENCE_BASE_URL="{base_url}" CONFLUENCE_USERNAME="{用户名}" CONFLUENCE_PASSWORD="{密码}" python tools/scrape_cf/scrape_confluence.py --root "{page_ids}" --output source/docs/
```

如果 `docs.json` 不存在，跳过此步（不报错）。如果用户主动要求配置，通过对话引导：
1. 询问 Confluence 地址和要拉取的根页面 ID（及描述）
2. 用 Write 工具生成 `source/docs/docs.json`（参考 `tools/scrape_cf/docs.template.json` 格式）
3. 生成后继续执行拉取

---

## push 执行

构建完成后，commit 并推送到远程。

**前提**：`.gitignore` 中必须包含 `source/repos/**/.git`，确保子仓库的 git 元数据不被提交。如果不存在，自动追加。

### 步骤 1 — 检查 .gitignore

```bash
cd "{kb_dir}"
grep -qF 'source/repos/**/.git' .gitignore 2>/dev/null || echo 'source/repos/**/.git' >> .gitignore
```

### 步骤 2 — commit + 推送

```bash
cd "{kb_dir}"
git add -A
git diff --cached --quiet || git commit -m "update knowledge base"
git push origin main
```

如果 push 失败（远程有新提交），先 `git pull --rebase origin main` 再重试。
如果尚未配置 remote，通过对话询问用户仓库地址，然后执行 `git remote add origin <地址>`。

---

## diff 执行

当用户输入 `/ewankb diff` 时，检测 source 目录变化并展示受影响的域。

```bash
cd "{kb_dir}"
ewankb diff
```

解析 JSON 输出，展示：
- 代码/文档各有多少新增、修改、删除
- 受影响的域列表

如果 hash 缓存不存在（首次执行），告诉用户"尚无基线，请先执行一次完整构建。"

---

## 增量构建逻辑

当 `/ewankb` 完整构建时，如果 `source/.cache/hashes.json` 已存在（非首次构建），在第 4 步之前插入增量检测：

1. 运行 `ewankb diff`，获取受影响的域列表
2. 如果无变更 → 告诉用户"源数据无变化，跳过构建"，直接跳到第 5 步（图谱）
3. 如果有变更 → 执行以下 Python 清理受影响域的缓存：

```python
from tools.incremental import clean
result = clean(affected_domains)
```

4. 然后正常执行第 4 步 `ewankb knowledgebase --skip-discover`，流水线会自动只重跑被清理的域
5. 构建完成后 `update_hash` 自动被调用（已内置在流水线末尾）

如果 hash 缓存不存在（首次构建），跳过增量检测，走全量构建。

---

## --build-graph 执行

当用户输入 `/ewankb --build-graph` 时，执行 AST 提取 + 域文档语义提取 + 图谱构建。

### 步骤 1 — 收集 domains/ 下的文档文件

```bash
cd "{kb_dir}"
python -c "
import json
from pathlib import Path

doc_files = []
domains_dir = Path('domains')
if domains_dir.exists():
    for f in sorted(domains_dir.rglob('*.md')):
        doc_files.append(str(f))
    dj = domains_dir / '_meta' / 'domains.json'
    if dj.exists():
        doc_files.append(str(dj))
Path('graph/.doc_files.txt').write_text('\n'.join(doc_files), encoding='utf-8')
print(f'域文档文件数: {len(doc_files)}')
"
```

如果文档数为 0，直接跳到步骤 3（只做 AST 图谱）。

### 步骤 2 — 逐域语义提取

读取 `domains/_meta/domains.json` 获取域列表，然后逐域处理：

对每个域：
1. 用 Read 工具读取 `domains/{域名}/README.md`
2. 用 Read 工具读取 `domains/{域名}/PROCESSES.md`
3. 从文档内容中提取：
   - **域概念**（职责、关键实体、管理的表/接口/模块）→ node（每域至少 5-10 个节点）
   - **业务流程**（每个流程步骤作为独立节点，步骤之间用 precedes 边连接）→ node + edge
   - **文档中引用的代码类名** → edge（连接文档节点到 AST 代码节点）。重点：README 的「核心接口文件」和「核心服务文件」段落、以及 enrich 追加的「关联代码」章节中列出的每一个类名，都应创建一条 `belongs_to` 边
4. 累积到 nodes/edges 列表

**提取粒度要求**：
- 每个域至少提取 5 个概念节点（域职责、核心实体、关键接口、数据表、业务规则等）
- PROCESSES.md 中的每个流程的每个步骤都应是独立节点
- README 中列出的每个 Rest/Controller/Service 类都应创建一条 `belongs_to` 边（source=域概念节点, target=小写类名）

最后从 `domains.json` 提取域层级关系（父域/子域）和域与模块的映射关系。

**提取规则**：
- node id 格式：`{域名}_{概念名}`（用下划线连接，中文直接保留）
- node 必须有：`id`、`label`、`file_type`（固定 `"document"`）、`source_file`（相对路径）、`domain`
- edge relation 类型：`contains`、`references`、`depends_on`、`precedes`、`belongs_to`、`manages`
- 文档中明确引用的代码实体（类名、模块名、包路径）→ 创建 edge，target 直接使用**小写类名**（如 `anomalyrecordrest`、`contractchangerest`），这是 AST 节点的实际 ID 格式。`build_graph()` 也内置了模糊匹配，支持 `路径::类名` 格式的自动解析
- 置信度标签：
  - `EXTRACTED`（confidence_score=1.0）：文档中明确声明的关系
  - `INFERRED`（confidence_score=0.6-0.9）：合理推断
  - `AMBIGUOUS`（confidence_score=0.1-0.3）：不确定

将结果用 Write 工具写入 `graph/.semantic_extraction.json`，格式：
```json
{
  "nodes": [{"id": "...", "label": "...", "file_type": "document", "source_file": "...", "domain": "..."}],
  "edges": [{"source": "...", "target": "...", "relation": "...", "confidence": "EXTRACTED", "confidence_score": 1.0, "source_file": "..."}]
}
```

### 步骤 3 — 构建图谱

`build_graph()` 会自动检测 `graph/.semantic_extraction.json` 并与 AST 结果合并。

```bash
ewankb build-graph
```

### 步骤 4 — 清理 + 汇报

```bash
rm -f graph/.doc_files.txt graph/.semantic_extraction.json
```

告诉用户图谱构建完成，展示节点/边数量统计。
如果 `graph/domain_suggestions.json` 存在，读取 `data["suggestions"][:3]` 并展示前 3 条建议。
