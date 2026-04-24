---
name: ewankb-query
description: 查询 ewankb 知识库。默认图谱查询，也可指定 kb 或 deep 双路对比模式。
trigger: /ewankb-query
---

# /ewankb-query

## 用法

```
/ewankb-query <问题>                        # 图谱查询（默认）
/ewankb-query graph <问题>                  # 图谱查询
/ewankb-query kb <问题>                     # 文档检索
/ewankb-query deep <问题>                   # 双路对比查询
```

## 执行步骤

### 1. 定位知识库 + 自动拉取

```bash
ewankb preflight --dir .
```

解析 JSON：`kb_dir` 是知识库路径。

**preflight 失败处理**（自动引导配置）：
- `blockers` 仅含 `no_llm_config`（其他 blocker 都不存在）→ 直接用 Write 工具创建 `{kb_dir}/llm_config.json`，内容如下：
  ```json
  {
    "api_key": "",
    "base_url": "",
    "model": "claude-haiku-4-5-20251001",
    "api_protocol": "anthropic"
  }
  ```
  然后提示用户编辑并填入 API Key，停止
- `blockers` 含 `no_llm_config` 且同时有其他 blocker → 如实告知所有 blocker（包含 llm_config 缺失和其他），停止
- `blockers` 含 `no_api_key` → `llm_config.json` 存在但 API Key 为空，提示用户填入，停止
- 其他 blocker → 如实告知用户并停止

**自动拉取**（消费者无需手动 pull）：
- 如果 `kb_dir` 是 git 仓库，检查是否有 remote 配置：
  ```bash
  cd "{kb_dir}"
  git remote -v
  ```
- 如果有 remote，静默拉取最新：
  ```bash
  git pull --rebase origin main 2>&1 || true
  ```
- 如果 `kb_dir` 不存在但用户提供了 git 仓库地址，自动 clone：
  ```bash
  git clone <仓库地址> "{kb_dir}"
  ```

如果 `graph.exists: false` 且需要 graph 查询，提示先运行 `/ewankb --build-graph`。

### 2. 判断查询模式

根据用户输入确定模式：
- `/ewankb-query <问题>`（无子命令）→ **图谱模式**（步骤 3A）
- `/ewankb-query graph <问题>` → **图谱模式**（步骤 3A）
- `/ewankb-query kb <问题>` → **kb 模式**（步骤 3B）
- `/ewankb-query deep <问题>` → **双路对比模式**（步骤 3C）

### 3A. Graph 模式（仅图谱）

```bash
ewankb query "用户问题" --json
```

如果 `ewankb` 命令不可用，请先运行 `pip install ewankb`。

**解析 JSON 结果并解读**：

1. **matched_start_nodes 为空**：
   → 告知用户图中未找到匹配节点，建议：
   - 尝试更短的关键词（如"付款额度" → "付款"）
   - 尝试用英文术语（如"overdraft"、"payment"）
   - 检查 query_analysis.extracted_keywords 是否合理
   - 建议用 `/ewankb-query kb "同一问题"` 切换到文档检索

2. **matched_start_nodes 非空**：
   → 基于 nodes 和 edges 用自然语言合成回答：
   - 从 matched_start_nodes 出发，描述直接关联的概念
   - 引用 source_file、source_location、relation 作为证据
   - 如果图的深度不足以覆盖问题范围，如实说明
   - 不要编造图中没有的关系
   - 参考 graphify 的做法：基于图的边关系做有限推理

**示例解读**：
```
根据图谱分析：
- 找到 2 个与"预付款"相关的节点
- 预付款执行付款 → calls → 付款计划
  来源：domains/收付款管理/README.md

这表明预付款流程和付款计划存在调用关系。但图中没有包含具体的额度计算逻辑，
可能需要查看 `/ewankb-query kb` 文档检索来获取更详细的计算规则。
```

回答末尾附建议："想看原文？试 `/ewankb-query kb \"同一问题\"`"

### 3B. KB 模式（仅文档）

```bash
ewankb query-kb "用户问题"
```

如果高分文档内容被截断，用 Read 工具读取完整内容后再回答。

回答末尾附建议："想看关联？试 `/ewankb-query graph \"同一问题\"`"

### 3C. 双路对比模式（deep）

用 Agent 工具**并行**启动两个 subagent（同一条消息）：

**Subagent A（graph）**：
> 在 {kb_dir} 执行 `ewankb query "{问题}"`，分析结果（涉及哪些节点、边、域）。

**Subagent B（kb）**：
> 在 {kb_dir} 执行 `ewankb query-kb "{问题}"`，对高分文档用 Read 工具读取完整内容，分析结果。

**对比 + 歧义处理**：
- 两路结果一致 → 合并汇总回答
- 存在歧义 → 向 subagent 追问具体歧义点，追问结果继续对比，还有歧义就再追问，直到一致（最多 5 轮）

最终回答格式：
```
## 回答
[综合回答]
## 信息来源
- 图谱：[关键发现]
- 文档：[关键发现]
## 差异说明（如有）
```

### 4. 回答约束

**严格模式约束**：用户选择了哪种查询模式，就只用该模式的结果回答。禁止因为认为结果不理想而自动切换或追加其他模式的查询。如果某种模式返回结果较少或为空，如实告知用户结果有限，并建议用户自行尝试其他模式，而不是替用户切换。

- 只用知识库中的信息回答，不编造
- 引用具体文件路径、类名、文档标题
- **结论优先**：先给出结论，再展开推断过程和细节
- **面向非技术人员**：关于代码的描述不要占大篇幅，除非提问者专门问代码细节
- **保持原问题**：回答标题和检索关键词必须使用用户的原始提问，禁止在检索前将业务语言改写为技术术语（如把"出库直发单"改写为"CZF"）。改写会缩小搜索范围，导致漏掉上游源头逻辑。如果检索结果中发现了对应的技术编码，在回答正文中补充说明即可，但不能用它替换原问题。
- **溯源到底**：当问题是"X 是怎么解析/产生/来的"这类溯源型提问时，找到一层解析逻辑后不能停，必须继续追问"这个输入值又是谁设置的"，直到追溯到系统边界（上游推送的原始字段）。只描述中间某一层映射机制不算完整回答。
