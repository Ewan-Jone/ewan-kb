# Ewan-kb

从 Java 后端代码 + 业务文档自动构建结构化业务知识库。

> **注意**：Ewan-kb 目前必须配合 [Claude Code](https://docs.anthropic.com/en/docs/claude-code) 使用。其 skill 定义（构建流程编排、交互式配置、语义提取等）和提示词均专为 Claude Code 设计，暂不支持其他 AI 编码工具。

## 对比 graphify 

[graphify](https://github.com/safishamsi/graphify) 是通用知识图谱构建工具，支持代码（tree-sitter AST，17 种语言）和文档（LLM 语义提取），输出为 `graph.json` + 社区报告 + wiki。

Ewan-kb 底层同样构建知识图谱（调用 graphify 做 AST 提取 + LLM 语义提取），但**不止于图**——在图谱之上增加了业务域组织、文档提炼、流程生成等层次，形成四层结构。查询时也不局限于图谱遍历，支持图谱查询、文档检索、双路对比等多种方式。

| 维度 | graphify | Ewan-kb |
|------|----------|---------|
| 定位 | 通用知识图谱 | 业务域知识库（含图谱） |
| 组织方式 | 按代码结构 / 社区聚类 | 按业务域（自动发现 + AI 翻译） |
| 输出形态 | 图谱（graph.json） | 四层结构（source → domains → knowledgeBase → graph） |
| 文档产物 | 无，图谱即终态 | 生成人类可读的域概览 + 流程文档 |
| 查询方式 | 图谱遍历（BFS/DFS） | 图谱遍历 + 文档检索 + 双路对比 |
| 增量粒度 | 文件级 hash | 域级影响映射（变更文件 → 模块 → 域） |
| 代码支持 | 17 种语言 | Java（域发现基于包路径） |
| 适用场景 | 任何代码仓库 | Java 微服务后端 + 业务文档的企业项目 |

## 四层架构

```
source/          →  domains/           →  knowledgeBase/     →  graph/
(原始数据)         (域组织 + AI 产物)     (最终知识库)           (可查询图谱)
```

| 层 | 职责 | 产物 | Git 提交 |
|----|------|------|----------|
| `source/` | 存放原始代码和文档 | Java 代码、.md 文档 | 是 |
| `domains/` | 按业务域组织，存放 extract 输出 + AI 生成的概览和流程 | README.md、PROCESSES.md、代码模块说明/、各类型文档/ | 是 |
| `knowledgeBase/` | 最终知识库，按文档类型平铺 | .md 文档（从 domains/ 迁移） | 是 |
| `graph/` | 知识图谱（AST + 语义） | graph.json、communities、统计 | 是 |

## 使用方式

知识库有两类用户角色：

- **构建者**：负责搭建和维护知识库的人（通常是熟悉系统代码和业务的研发），使用 `/ewankb` 执行构建、更新、推送等操作
- **消费者**：需要查询业务知识的人（研发、产品、测试、新人等），使用 `/ewankb-query` 直接提问，无需了解构建过程

这样划分是因为构建过程需要代码和文档的写入权限、LLM API 配置、以及对业务域映射的理解；而消费者只需要一个已构建好的知识库（通过 git clone 获取）即可开始查询。

### 构建者（/ewankb）

**前置条件**：Claude Code + ewankb skill 已安装。

**首次构建**：

```
/ewankb <知识库路径>
```

执行完整流程：preflight → discover → 模块映射 → knowledgebase → build-graph。

**增量构建**：

```
/ewankb
```

自动检测 source/ 变更，只重跑受影响的域。

**常用子命令**：

| 命令 | 说明 |
|------|------|
| `/ewankb` | 完整构建（含增量检测） |
| `/ewankb --build-kb` | 仅构建 domains + knowledgeBase |
| `/ewankb --build-kb --skip-discover` | 跳过域发现，从代码分析开始 |
| `/ewankb --build-graph` | 仅构建图谱（AST + 语义提取） |
| `/ewankb discover` | 重跑域发现 + 模块映射 |
| `/ewankb pull` | 拉取远程知识库 + 同步源码 + 同步文档 |
| `/ewankb push` | 提交并推送到远程仓库 |
| `/ewankb diff` | 检测 source/ 变更，展示受影响的域 |

### 消费者（/ewankb-query）

无需构建，直接查询已构建好的知识库。

| 命令 | 说明 |
|------|------|
| `/ewankb-query <问题>` | 图谱查询（默认，BFS 遍历关联节点） |
| `/ewankb-query kb <问题>` | 文档检索（BM25 检索知识库文档） |
| `/ewankb-query deep <问题>` | 双路对比查询（图谱 + 文档并行，交叉验证） |

## 核心流程

### 域发现（discover）

1. **代码扫描**：扫描 `source/repos/` 下的 Java 包路径，提取业务 segment（跳过停用词表中的技术层词汇）
2. **AI 精炼**：将代码 segment + 文档标题样本发给 LLM，翻译为中文域名并做合并/拆分/层级组织
3. **模块映射**：AI 辅助将代码目录映射到对应的业务域

产出：`domains/_meta/domains.json`

### 知识库构建（knowledgebase）

7 步流水线，按顺序执行：

| 步骤 | 说明 |
|------|------|
| analyze_code | 扫描代码结构，生成 code_analysis.json |
| extract | 读取文档全文，AI 分类到对应域的文档类型子目录 |
| gen_code_module_docs | 为每个域的代码模块生成说明文档 |
| enrich | 为已分类文档追加关联代码信息（类名、接口路径） |
| gen_overview | 为每个域生成 README.md（业务定位、代码模块、表结构、文档索引） |
| gen_processes | 为每个域生成 PROCESSES.md（L1/L2/L3 三级流程） |
| migrate | 将 domains/ 下的文档迁移到 knowledgeBase/ 按类型平铺 |

### 图谱构建（build-graph）

1. **AST 提取**（graphify）：从 Java 代码提取类、方法、调用关系等节点和边
2. **语义提取**（LLM，通过 skill 触发）：从 domains/ 的 README 和 PROCESSES 中提取业务概念、流程步骤、代码关联
3. **合并**：AST 节点 + 语义节点去重合并
4. **社区检测**：Leiden 算法发现结构聚类
5. **输出**：graph.json + 统计 + 建议

### 增量更新

1. **Hash 缓存**：首次构建后记录所有 source/ 文件的 SHA-256
2. **变更检测**：对比当前文件 hash 与缓存，找出新增/修改/删除的文件
3. **域影响映射**：变更文件 → 模块根目录 → domains.json 的 modules 映射 → 受影响的域
4. **选择性清理**：清除受影响域的生成产物（README、PROCESSES、进度记录等）
5. **重跑流水线**：流水线自动只处理被清理的域

## 关键配置项

### project_config.json

| 字段 | 说明 |
|------|------|
| `project_name` | 项目中文名（如"国际物流业务知识库"） |
| `system_name` | 系统名称，用于 AI prompt（如"国际物流系统"） |
| `api_key` | LLM API Key |
| `base_url` | LLM API Base URL（留空使用 Anthropic 官方） |
| `model` | 模型名称（默认 claude-haiku-4-5-20251001） |
| `doc_type_rules` | 文档类型识别规则（类型名 + 关键词列表） |
| `code_structure` | 代码仓库目录约定（java_package_prefix 等） |
| `skip_domains` | 跳过不生成概览的域列表 |
| `skip_doc_types_for_enrich` | enrich 阶段跳过的文档类型 |
| `system_fields` | DB schema 提取时过滤的通用系统字段 |
| `extraction_prompts` | 各文档类型的自定义提炼 prompt |

### segment_stopwords.json（域发现词表）

位于 `tools/discover/segment_stopwords.json`，控制从 Java 包路径中提取业务 segment 的行为：

| 词表 | 作用 | 示例 |
|------|------|------|
| `segment_stopwords` | 技术层 + 框架 + 项目名，无业务含义，匹配时直接跳过 | api, controller, service, impl, common, logistics |
| `package_wrappers` | 技术分层目录名，跳过它但继续往后找下一个词 | rest, feign, remote, job, batch |
| `generic_noise` | 通用名词，单独出现无业务区分度，不作为域标识 | info, detail, list, data, record, manage |

提取逻辑：逐个检查包路径片段，跳过在停用词表中的词，第一个不在任何表中的词即为 segment。

`segment_stopwords.json` 由 ewan-kb 维护，包含通用的技术词汇。构建者如需添加项目特有的停用词（如内部项目代号、公司包名），可编辑同目录下的 `segment_stopwords_extends.json`（格式相同，不提交 git）。

### source/repos/repos.json（可选）

配置需要从 git 自动拉取的代码仓库。`/ewankb pull` 时自动克隆或更新。

```json
{
  "repos": [
    {"name": "my-service", "url": "git@...", "branch": "master"}
  ]
}
```

也支持不配置 repos.json，直接手动将代码目录放到 `source/repos/` 下。

### source/docs/docs.json（可选）

Confluence 文档自动拉取配置。内置爬虫会递归抓取指定根页面下的所有子页面并转为 .md 格式。

```json
{
  "base_url": "https://your-confluence.example.com",
  "roots": [
    {"page_id": "12345", "description": "产品文档"}
  ]
}
```

> **文档来源不限于 Confluence**。只要是 `.md` 格式放到 `source/docs/` 即可参与构建。Confluence 只是提供了现成的爬取+转换工具，其他来源（语雀、飞书、本地文档等）需用户自行转为 `.md` 放入。

## 目录结构

```
my-knowledge-base/
├── project_config.json          # 项目配置（构建者使用，不提交 git）
├── source/                      # 原始数据（只读）
│   ├── repos/                   # 代码仓库
│   │   ├── repos.json           # git 拉取配置（可选）
│   │   └── my-service/          # 代码目录
│   ├── docs/                    # 业务文档（.md）
│   │   ├── docs.json            # CF 拉取配置（可选）
│   │   └── *.md
│   └── .cache/                  # 增量构建缓存
│       ├── hashes.json
│       └── doc_domain_mapping.json
├── domains/                     # 域组织层
│   ├── _meta/
│   │   ├── domains.json         # 域定义（自动生成）
│   │   └── module_mapping_context.md
│   └── {域名}/
│       ├── README.md            # 域概览（AI 生成）
│       ├── PROCESSES.md         # 流程文档（AI 生成）
│       ├── 代码模块说明/         # 代码模块文档
│       ├── 需求文档/            # extract 分类的文档
│       ├── 业务规则/
│       └── ...
├── knowledgeBase/               # 最终知识库
│   ├── _state/                  # 流水线状态
│   │   ├── progress.json
│   │   ├── enrich_progress.json
│   │   └── code_module_progress.json
│   ├── 需求文档/
│   ├── 业务规则/
│   └── ...
└── graph/                       # 知识图谱
    ├── graph.json
    ├── communities.json
    └── domain_suggestions.json
```

## 安装

```bash
# 从源码安装
cd Ewan-kb
pip install -e .

# 验证
ewankb --help
```

依赖：Python 3.10+、graphify、anthropic SDK、rank-bm25、jieba。

### CLI 命令

```
ewankb init <name>              初始化新知识库
ewankb discover                 域发现
ewankb knowledgebase            构建 domains/ + knowledgeBase/
ewankb build-graph              构建图谱
ewankb build                    完整构建（knowledgebase + graph）
ewankb query <text>             图谱查询
ewankb query-kb <text>          文档检索
ewankb graph-stats              图谱统计
ewankb diff                     检测变更
ewankb preflight [--fix]        环境检查
```

## 已知限制

- 代码域发现目前仅支持 Java（基于包路径提取 segment）
- LLM 语义提取质量依赖 prompt 和模型能力
- 图谱的语义节点提取（文档→图谱）仅通过 Claude Code skill 触发，CLI 单独执行 `build-graph` 只有 AST 节点

## License

MIT
