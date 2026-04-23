# Ewan-kb

从 Java 后端代码和业务文档中构建按业务域组织的知识库，并生成可查询的知识图谱。

它适合需要沉淀业务知识、梳理流程、支持新成员理解系统的团队。构建完成后，你会得到两类产物：

- 面向人的业务知识库文档
- 面向查询的结构化图谱

> **使用前须知**：Ewan-kb 的完整使用体验目前以 [Claude Code](https://docs.anthropic.com/en/docs/claude-code) 为主，尤其是 slash command、交互式构建流程和语义提取提示词。底层 `ewankb` CLI 可单独使用，但 Claude Code 仍是当前的推荐入口。

## 适用场景

**适合：**

- Java 微服务后端 + 业务文档较多的企业项目
- 需要按业务域整理知识，而不只是做代码图谱的团队
- 希望同时支持文档检索、图谱查询和流程理解的场景

**暂不适合：**

- 非 Java 后端为主的项目
- 只需要通用代码图谱、不需要业务知识库分层的场景
- 不使用 Claude Code 的工作流

## 你属于哪类用户？

### 构建者

负责搭建和维护知识库，通常是熟悉系统代码和业务的研发。你需要准备源码、业务文档、项目配置和 LLM 凭证，并使用 `/ewankb` 或底层 `ewankb` CLI 执行构建、更新和同步。

### 使用者

负责查询和消费知识库内容，通常是研发、产品、测试或新成员。你不需要了解构建细节，只需要一个已构建好的知识库副本和自己的 `llm_config.json`，并使用 `/ewankb-query` 提问。

## 快速开始

### 构建者

构建者负责搭建和维护知识库，通常是熟悉系统代码和业务的研发。

```bash
# 1. 安装
pip install ewankb
ewankb install          # 安装 Claude Code skills

# 2. 首次构建（交互式引导，自动配置 llm_config.json）
/ewankb <知识库路径>

# 3. 增量构建（自动检测变更，只重跑受影响的域）
/ewankb
```

### 使用者

使用者只需克隆已构建好的知识库，创建 `llm_config.json` 并填入 LLM API 凭证后即可查询。

```bash
# 1. 安装
pip install ewankb
ewankb install          # 安装 Claude Code skills

# 2. 克隆知识库
git clone <知识库地址> my-kb
cd my-kb

# 3. 创建 llm_config.json
cat > llm_config.json << 'EOF'
{
  "api_key": "your-api-key-here",
  "base_url": "",
  "model": "claude-haiku-4-5-20251001",
  "api_protocol": "anthropic"
}
EOF

# 4. 开始查询
/ewankb-query <问题>
```

> 如使用 Claude Code，首次查询时 skill 也会自动检测并引导创建。手动创建可跳过这一步。模板文件见 `examples/llm_config.example.json`。

### 安装说明

默认安装方式：

```bash
pip install ewankb
ewankb install
```

运行环境要求：Python 3.10+。安装包会自动拉取 `graphifyy`、`anthropic`、`rank-bm25`、`jieba` 等依赖。

### 源码安装（开发者）

如果你要参与开发、调试本地改动或直接从仓库运行最新代码，再使用源码安装：

```bash
git clone https://github.com/Ewan-Jone/ewan-kb.git
cd ewan-kb
pip install -e .
ewankb install
```

## 常用命令

### Claude Code 入口

| 命令 | 用途 |
|------|------|
| `/ewankb` | 完整构建知识库 |
| `/ewankb --build-kb` | 仅构建 `domains/` 和 `knowledgeBase/` |
| `/ewankb --build-kb --skip-discover` | 跳过域发现，直接重跑知识库流水线 |
| `/ewankb --build-graph` | 仅构建图谱 |
| `/ewankb discover` | 单独执行域发现 |
| `/ewankb pull` | 拉取远程知识库并同步源码/文档 |
| `/ewankb push` | 提交并推送知识库 |
| `/ewankb diff` | 检测变更并展示受影响域 |
| `/ewankb-query <问题>` | 图谱查询（默认） |
| `/ewankb-query kb <问题>` | 文档检索 |
| `/ewankb-query deep <问题>` | 图谱 + 文档双路对比 |

### CLI 构建命令

| 命令 | 说明 |
|------|------|
| `ewankb init <name>` | 初始化新知识库目录 |
| `ewankb preflight --fix --dir .` | 检查环境并补齐缺失目录/配置 |
| `ewankb discover` | 域发现 |
| `ewankb knowledgebase` | 构建 `domains/` + `knowledgeBase/` |
| `ewankb knowledgebase --skip-discover` | 跳过域发现直接执行 7 步流水线 |
| `ewankb build` | 完整构建（知识库 + 图谱） |
| `ewankb build --kb` | 仅构建知识库 |
| `ewankb build --graph` | 仅构建图谱 |
| `ewankb diff` | 检测 `source/` 变更 |
| `ewankb rebuild` | 清空生成产物，做一次干净重建 |

### CLI 查询命令

| 命令 | 说明 |
|------|------|
| `ewankb query <text>` | 图谱查询 |
| `ewankb query-graph <text>` | 图谱查询别名 |
| `ewankb query-kb <text>` | 文档检索 |
| `ewankb graph-stats` | 图谱统计 |
| `ewankb communities` | 查看社区聚类 |
| `ewankb surprising` | 查看跨域关联 |

### 配置与维护命令

| 命令 | 说明 |
|------|------|
| `ewankb config --show` | 查看当前配置 |
| `ewankb config --edit` | 编辑 `project_config.json` |
| `ewankb config --edit-llm` | 编辑 `llm_config.json` |
| `ewankb install` | 安装 Claude Code skills |

## 构建完成后会看到什么

一个完整知识库通常包含四层产物：

```text
source/          →  domains/           →  knowledgeBase/     →  graph/
(原始数据)         (域组织 + AI 产物)     (最终知识库)           (可查询图谱)
```

> 知识库本身是一个 git 仓库。以上四层产物都会提交到知识库仓库，消费者 clone 后即可查询。`source/` 在 ewan-kb 工具仓库中会被 gitignore，但在知识库仓库中正常提交。

目录示例：

```text
my-knowledge-base/
├── project_config.json          # 项目元数据（提交 git）
├── llm_config.json              # LLM 凭证（不提交 git，每人自行创建）
├── source/                      # 原始数据
│   ├── repos/                   # 代码仓库
│   │   ├── repos.json           # git 拉取配置（可选）
│   │   └── my-service/          # 代码目录
│   ├── docs/                    # 业务文档（.md）
│   │   ├── docs.json            # Confluence 拉取配置（可选）
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

四层职责：

| 层 | 职责 | 产物 | Git 提交 |
|----|------|------|----------|
| `source/` | 存放原始代码和文档 | Java 代码、`.md` 文档 | 是 |
| `domains/` | 按业务域组织，存放中间产物和 AI 生成概览 | README、PROCESSES、分类文档 | 是 |
| `knowledgeBase/` | 最终知识库，按文档类型平铺 | 迁移后的 `.md` 文档 | 是 |
| `graph/` | 知识图谱（AST + 语义） | `graph.json`、统计、建议 | 是 |

## 核心流程

### 1. 域发现（discover）

1. 扫描 `source/repos/` 下的 Java 包路径
2. 提取业务 segment，跳过技术层词汇
3. 由 LLM 翻译并整理为中文业务域
4. 将代码目录映射到域

主要产出：`domains/_meta/domains.json`

### 2. 知识库构建（knowledgebase）

`ewankb knowledgebase` 会执行 7 步流水线：

| 步骤 | 说明 |
|------|------|
| `analyze_code` | 扫描代码结构，生成 `code_analysis.json` |
| `extract` | 读取文档全文，分类到对应域和文档类型 |
| `gen_code_module_docs` | 为每个域生成代码模块说明文档 |
| `enrich` | 为文档追加关联代码信息（类名、接口路径等） |
| `gen_overview` | 为每个域生成 `README.md` |
| `gen_processes` | 为每个域生成 `PROCESSES.md` |
| `migrate` | 将 `domains/` 下的文档迁移到 `knowledgeBase/` |

### 3. 图谱构建（build-graph）

1. 使用 graphify 提取 AST 节点和调用关系
2. 从 `domains/` 的 README 和流程文档中提取语义节点
3. 合并 AST 节点和语义节点
4. 做社区检测并输出统计结果

输出：`graph/graph.json`、`communities.json`、`domain_suggestions.json`

### 4. 增量更新

1. 首次构建后记录 `source/` 文件哈希
2. 对比新增、修改、删除文件
3. 将变更文件映射到业务域
4. 清理受影响域的生成产物
5. 只重跑受影响域对应的流水线

## 关键配置

### `project_config.json`（项目元数据，提交 git）

| 字段 | 说明 |
|------|------|
| `project_name` | 项目中文名，如“国际物流业务知识库” |
| `system_name` | 系统名称，用于 LLM prompt |
| `doc_type_rules` | 文档类型识别规则 |
| `code_structure` | 代码仓库目录约定，如 `java_package_prefix` |
| `skip_domains` | 跳过不生成概览的域列表 |
| `skip_doc_types_for_enrich` | enrich 阶段跳过的文档类型 |
| `system_fields` | DB schema 提取时过滤的通用系统字段 |
| `extraction_prompts` | 各文档类型的自定义提炼 prompt |
| `segment_stopwords` | 域发现停用词表，项目级完全覆盖默认值 |

模板可参考：

- `config/project_config.template.json`
- `tools/project_config.template.json`

### `llm_config.json`（LLM 凭证，不提交 git）

| 字段 | 说明 |
|------|------|
| `api_key` | LLM API Key |
| `base_url` | LLM API Base URL，留空则使用 Anthropic 官方 |
| `model` | 模型名称，默认 `claude-haiku-4-5-20251001` |
| `api_protocol` | API 协议类型：`anthropic` 或 `openai` |

每位使用者都需要创建自己的 `llm_config.json` 并填入 API 凭证。模板文件见 `examples/llm_config.example.json`。

### 可选输入源：代码仓库和文档

`source/repos/repos.json` 用于配置需要自动拉取的代码仓库：

```json
{
  "repos": [
    {"name": "my-service", "url": "git@...", "branch": "master"}
  ]
}
```

也可以不配，直接把代码放到 `source/repos/`。

`source/docs/docs.json` 用于配置 Confluence 抓取：

```json
{
  "base_url": "https://your-confluence.example.com",
  "roots": [
    {"page_id": "12345", "description": "产品文档"}
  ]
}
```

文档来源不限于 Confluence。只要是 `.md` 格式放到 `source/docs/`，都可以参与构建。

### 高级调优：`segment_stopwords`

`project_config.json` 中的 `segment_stopwords` 字段控制从 Java 包路径中提取业务 segment 的方式。内置默认值来源于 `tools/discover/segment_stopwords.json`，但项目级配置会完全覆盖默认值。

| 词表 | 作用 | 示例 |
|------|------|------|
| `segment_stopwords` | 技术层、框架、项目名，匹配时直接跳过 | `api`, `controller`, `service` |
| `package_wrappers` | 技术分层目录名，跳过后继续往后找 | `rest`, `feign`, `job` |
| `generic_noise` | 无业务区分度的泛化词，不作为域标识 | `info`, `detail`, `record` |

提取逻辑是：逐个检查包路径片段，跳过停用词，遇到第一个有效词就作为业务 segment。

`ewankb init` 会将内置默认词表写入 `project_config.json`。旧版 `project_config.json` 如果缺少这个字段，首次运行 discover 时会自动补写。

## 与 graphify 的关系

[graphify](https://github.com/safishamsi/graphify) 是通用知识图谱构建工具，支持代码 AST 和文档语义提取，输出图谱和社区结果。

Ewan-kb 底层同样会调用 graphify 做 AST 提取，但它不止停在“图”这一层，而是在图谱之上增加了业务域组织、知识库文档生成和流程提炼能力。

| 维度 | graphify | Ewan-kb |
|------|----------|---------|
| 定位 | 通用知识图谱 | 业务域知识库（含图谱） |
| 组织方式 | 按代码结构 / 社区聚类 | 按业务域（自动发现 + AI 翻译） |
| 输出形态 | 图谱（`graph.json`） | 四层结构（`source -> domains -> knowledgeBase -> graph`） |
| 文档产物 | 无，图谱即终态 | 生成人类可读的域概览和流程文档 |
| 查询方式 | 图谱遍历 | 图谱查询 + 文档检索 + 双路对比 |
| 增量粒度 | 文件级 hash | 域级影响映射 |
| 代码支持 | 17 种语言 | Java（域发现基于包路径） |
| 适用场景 | 任意代码仓库 | Java 微服务后端 + 业务文档项目 |

如果你的目标只是快速得到一个通用代码图谱，graphify 就够了；如果你想得到“按业务域组织的知识库 + 图谱 + 查询入口”，Ewan-kb 更合适。

## 已知限制

- 代码域发现目前仅支持 Java，且依赖包路径约定
- LLM 语义提取质量依赖 prompt 和模型能力
- 文档语义入图目前主要通过 Claude Code skill 触发
- 消费者 clone 知识库后仍需自行配置 `llm_config.json`
- README 中提到的 Claude Code slash command 依赖先执行 `ewankb install`

## License

MIT
