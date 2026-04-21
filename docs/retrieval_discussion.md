# Ewan-kb 检索增强方案讨论

## 背景

Ewan-kb 当前支持两种查询方式：
- **query-kb**（文件直搜）：精确匹配，无需索引，但无法语义理解，漏召回
- **query-graph**（图检索）：关系推理、跨域关联，但依赖图结构完整度

希望增加 **BM25**（关键词召回）和**向量检索**（语义召回）两种能力。

## 5 个方面的分析

### 1. 索引什么内容

分层索引，每个 chunk 带 metadata（domain、doc_type、source_file）：
- **domains/ 下的 README.md、PROCESSES.md** — 高质量摘要，权重最高
- **knowledgeBase/{doc_type}/*.md** — 提炼文档，主力检索内容
- **source/repos/ 的代码注释 + 方法签名** — 可选，量大但噪音也大

Chunking 策略：按 markdown heading 切分（自然语义边界），每 chunk 500-1000 token，保留 frontmatter 作为 metadata。

### 2. BM25 方案选择

| 方案 | 特点 |
|------|------|
| **bm25s** | 纯 Python，稀疏矩阵实现，快，内存索引，几行代码搞定 |
| **SQLite FTS5** | 零依赖（Python 自带 sqlite3），持久化，支持 BM25 排序 |
| **tantivy-py** | Rust 内核，最快，支持中文分词插件，持久化索引 |

### 3. 向量检索方案选择

| 方案 | 特点 |
|------|------|
| **ChromaDB** | 嵌入式、Python 原生、自带 embedding 调用，最简单 |
| **LanceDB** | 嵌入式、列式存储、原生支持混合检索（BM25+向量）|
| **FAISS** | Facebook 出品、纯向量、需自己管 embedding 和 metadata |

Embedding 模型：
- **本地**：`BAAI/bge-small-zh-v1.5`（中文优化，~90MB，CPU 可跑）
- **API**：调 OpenAI/Anthropic embedding 接口（简单但有成本）

### 4. 集成到流水线

在流水线末尾加 `build_index` 步骤：
1. 扫描 domains/ + knowledgeBase/ 下所有 .md
2. 按 heading 切 chunk，保留 metadata
3. jieba 分词 → 写入 BM25 索引
4. embedding → 写入向量索引
5. 输出索引文件到 graph/ 目录

增量更新：对比文件 hash，只重新索引变更文件。

### 5. 查询时融合

```
query-hybrid "问题":
  1. BM25 检索 → top 20
  2. 向量检索 → top 20
  3. RRF (Reciprocal Rank Fusion) 合并排序
  4. 取 top 5 送 LLM 生成答案
```

## 决策记录

- **LanceDB 已排除**
- 其他方案待继续讨论

## 安装依赖参考

| 包 | 大小 | 用途 |
|---|---|---|
| bm25s | 轻量 | 纯 Python BM25 |
| tantivy | Rust wheel | 高性能全文检索 |
| chromadb | 较重（带 sqlite、onnxruntime） | 嵌入式向量库 |
| faiss-cpu | ~30MB | 纯向量检索 |
| sentence-transformers + torch | ~2GB | 本地 embedding |
