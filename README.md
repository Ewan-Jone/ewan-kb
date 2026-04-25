# Ewan-kb

从 Java 后端代码和业务文档中构建按业务域组织的知识库，并生成可查询的知识图谱。

适合需要沉淀业务知识、梳理流程、支持新成员理解系统的团队。构建完成后产出两类产物：

- 面向人的业务知识库文档
- 面向查询的结构化图谱

> 完整使用体验目前以 [Claude Code](https://docs.anthropic.com/en/docs/claude-code) 为主。底层 `ewankb` CLI 可单独使用，但 Claude Code 仍是推荐入口。

## 适用场景

**适合：**

- Java 微服务后端 + 业务文档较多的企业项目
- 需要按业务域整理知识，而不只是做代码图谱的团队
- 希望同时支持文档检索、图谱查询和流程理解的场景

**暂不适合：**

- 非 Java 后端为主的项目
- 只需要通用代码图谱、不需要业务知识库分层的场景
- 不使用 Claude Code 的工作流

## 快速开始

### 构建者

负责搭建和维护知识库，通常是熟悉系统代码和业务的研发。

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

只需克隆已构建好的知识库，创建 `llm_config.json` 填入 API 凭证后即可查询。

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

### 源码安装

```bash
git clone https://github.com/Ewan-Jone/ewan-kb.git
cd ewan-kb
pip install -e .
ewankb install
```

运行环境：Python 3.10+。自动拉取 `graphifyy`、`anthropic`、`rank-bm25`、`jieba` 等依赖。

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

### CLI 命令

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
| `ewankb query <text>` | 图谱查询 |
| `ewankb query-kb <text>` | 文档检索 |
| `ewankb graph-stats` | 图谱统计 |
| `ewankb communities` | 查看社区聚类 |
| `ewankb config --show` | 查看当前配置 |
| `ewankb install` | 安装 Claude Code skills |

## 构建产物

完整知识库包含四层产物：

```text
source/          →  domains/           →  knowledgeBase/     →  graph/
(原始数据)         (域组织 + AI 产物)     (最终知识库)           (可查询图谱)
```

目录示例：

```text
my-knowledge-base/
├── project_config.json          # 项目元数据
├── llm_config.json              # LLM 凭证（不提交 git）
├── source/                      # 原始数据
│   ├── repos/                   # 代码仓库
│   ├── docs/                    # 业务文档（.md）
│   └── .cache/                  # 增量构建缓存
├── domains/                     # 域组织层
│   ├── _meta/domains.json       # 域定义
│   └── {域名}/
│       ├── README.md            # 域概览（AI 生成）
│       ├── PROCESSES.md         # 流程文档（AI 生成）
│       ├── 代码模块说明/
│       ├── 需求文档/
│       └── ...
├── knowledgeBase/               # 最终知识库
│   ├── _state/                  # 流水线状态 + BM25 索引
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
| `knowledgeBase/` | 最终知识库，按文档类型平铺 | 迁移后的 `.md` 文档、BM25 索引 | 是 |
| `graph/` | 知识图谱（AST + 语义） | `graph.json`、统计、建议 | 是 |

## 核心流程

### 域发现（discover）

扫描 `source/repos/` 下的 Java 包路径，提取业务 segment，跳过技术层词汇，由 LLM 翻译为中文业务域。

产出：`domains/_meta/domains.json`

### 知识库构建（knowledgebase）

7 步流水线：

| 步骤 | 说明 |
|------|------|
| `analyze_code` | 扫描代码结构，生成 `code_analysis.json` |
| `extract` | 读取文档全文，分类到对应域和文档类型 |
| `gen_code_module_docs` | 为每个域生成代码模块说明文档 |
| `enrich` | 为文档追加关联代码信息（类名、接口路径等） |
| `gen_overview` | 为每个域生成 `README.md` |
| `gen_processes` | 为每个域生成 `PROCESSES.md` |
| `migrate` | 将 `domains/` 下的文档迁移到 `knowledgeBase/` |

完成后自动构建 BM25 索引，供 `query_kb` 使用。

### 图谱构建（build-graph）

1. 使用 graphify 提取 AST 节点和调用关系
2. 从 `domains/` 的 README 和流程文档中提取语义节点
3. 合并 AST 节点和语义节点
4. 做社区检测并输出统计结果

产出：`graph/graph.json`、`communities.json`、`domain_suggestions.json`

### 增量更新

首次构建后记录 `source/` 文件哈希，对比新增、修改、删除文件，映射到业务域，清理受影响域的生成产物，只重跑受影响域对应的流水线。

### 查询

- **图谱查询**：基于关键词匹配起始节点 + BFS/DFS 遍历，支持 `verbose=True` 返回结构化 JSON
- **文档检索**：基于 BM25 关键词排名，支持按域过滤
- **双路对比**：图谱查询 + 文档检索结果合并

`KBContext` 类封装了查询逻辑，支持多 KB 环境（通过 EWANKB_DIR 环境变量切换）。

## 配置

### `project_config.json`（项目元数据，提交 git）

| 字段 | 说明 |
|------|------|
| `project_name` | 项目中文名 |
| `system_name` | 系统名称，用于 LLM prompt |
| `doc_type_rules` | 文档类型识别规则 |
| `code_structure` | 代码仓库目录约定 |
| `skip_domains` | 跳过不生成概览的域列表 |
| `segment_stopwords` | 域发现停用词表 |

### `llm_config.json`（LLM 凭证，不提交 git）

| 字段 | 说明 |
|------|------|
| `api_key` | LLM API Key |
| `base_url` | LLM API Base URL，留空则使用 Anthropic 官方 |
| `model` | 模型名称，默认 `claude-haiku-4-5-20251001` |
| `api_protocol` | API 协议类型：`anthropic` 或 `openai` |

每位使用者需创建自己的 `llm_config.json`。模板见 `examples/llm_config.example.json`。

### 域发现停用词

`segment_stopwords` 控制从 Java 包路径提取业务 segment 的方式。内置默认值来源于 `tools/discover/segment_stopwords.json`，项目级配置会完全覆盖默认值。

| 词表 | 作用 |
|------|------|
| `segment_stopwords` | 技术层、框架、项目名，匹配时直接跳过 |
| `package_wrappers` | 技术分层目录名，跳过后继续往后找 |
| `generic_noise` | 无业务区分度的泛化词，不作为域标识 |

## 与 graphify 的关系

[graphify](https://github.com/safishamsi/graphify) 是通用知识图谱构建工具。Ewan-kb 底层调用 graphify 做 AST 提取，但不止停在图谱层，增加了业务域组织、知识库文档生成和流程提炼能力。

| 维度 | graphify | Ewan-kb |
|------|----------|---------|
| 定位 | 通用知识图谱 | 业务域知识库（含图谱） |
| 组织方式 | 按代码结构 / 社区聚类 | 按业务域（自动发现 + AI 翻译） |
| 输出形态 | 图谱（`graph.json`） | 四层结构 |
| 文档产物 | 无 | 域概览、流程文档、BM25 索引 |
| 查询方式 | 图谱遍历 | 图谱查询 + 文档检索 + 双路对比 |

## 已知限制

- 代码域发现仅支持 Java，依赖包路径约定
- LLM 语义提取质量依赖 prompt 和模型能力
- 文档语义入图主要通过 Claude Code skill 触发
- 消费者 clone 知识库后需自行配置 `llm_config.json`

## License

MIT