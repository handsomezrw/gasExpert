# 阶段 2-2 实施总结：RAG 混合检索管道

> 对应 PLAN.md 阶段 2 第二项任务（已完成 [x]）

---

## 一、完成的工作

### 任务目标

实现完整的 RAG（检索增强生成）混合检索管道，使 Agent 在面对规范条款、操作规程等知识性问题时，能够从本地文档库中检索相关内容并辅助生成回答。

### 检索管道架构

```
用户问题 ──┬──→ ChromaDB 向量检索 (bge-large-zh-v1.5, top-20)  ──┐
           │                                                       ├─→ RRF 融合 ─→ [可选] Reranker ─→ top-5 结果
           └──→ BM25 关键词检索 (jieba 分词, top-20)            ──┘
```

### 各模块实现详情

#### 1. 文档入库脚本 (`rag/ingest.py`)

| 项目 | 内容 |
|------|------|
| 文件格式 | 支持 PDF（PyMuPDF 解析）、TXT、Markdown |
| 切片策略 | 中文规范条款感知 — 优先按 `X.X.X` 条款编号和 `第X章/节` 分割，保留章节元数据；超长条款按句子边界二次切割（带重叠） |
| 小分块合并 | 相邻小于 80 字符的分块自动合并，避免碎片化 |
| 向量索引 | ChromaDB PersistentClient + `bge-large-zh-v1.5` Embedding Function，cosine 距离 |
| BM25 索引 | 全部分块导出为 `data/rag_chunks.json`，启动时加载并用 jieba 分词构建 BM25Okapi |
| CLI 入口 | `python -m app.rag.ingest [--docs-dir PATH] [--create-sample]` |
| 内置样本 | 提供约 1900 字的燃气规程节选（5 章 30+ 条款），可直接用于测试 |

**切片元数据结构**：
```json
{
  "id": "chunk_a1b2c3d4e5f6",
  "text": "4.2.2 管道泄漏的临时处置方法：...",
  "source": "CJJ51_规程.pdf",
  "page": 23,
  "heading": "4.2.2 管道泄漏的临时处置方法："
}
```

#### 2. 混合检索器 (`rag/retriever.py`)

| 项目 | 内容 |
|------|------|
| 模式 | 模块级单例 — `init_retriever()` 初始化，`get_retriever()` 获取 |
| 向量检索 | ChromaDB `collection.query()`，默认 top-20 |
| 关键词检索 | `rank_bm25.BM25Okapi` + jieba 中文分词，默认 top-20 |
| 并行执行 | `asyncio.gather()` + `run_in_executor()` 将两路检索并行化 |
| RRF 融合 | Reciprocal Rank Fusion（k=60），合并两路排序结果 |
| Reranker | 可选（`rag_enable_reranker=True` 时启用），使用 `sentence-transformers.CrossEncoder` 加载 `bge-reranker-v2-m3` 模型 |
| 输出格式化 | `format_docs_for_state()` 将结果格式化为带来源标注的字符串，注入 AgentState |

**RRF 融合算法**：
```
RRF_score(doc) = Σ 1/(k + rank_in_list_i)

对每个文档，累加它在向量检索结果和 BM25 结果中的倒数排名分，
同时出现在两路结果中的文档得分更高，排名更靠前。
```

#### 3. 重排序器 (`rag/reranker.py`)

| 项目 | 内容 |
|------|------|
| 模型 | `BAAI/bge-reranker-v2-m3`（通过 sentence-transformers CrossEncoder 加载） |
| 加载策略 | 懒加载 — 首次调用 `rerank()` 时才加载模型 |
| 降级策略 | 模型不可用时自动降级为 passthrough（直接按 RRF 顺序返回） |
| 配置开关 | `rag_enable_reranker` 默认 `False`，避免首次启动下载 1.1GB 模型 |

#### 4. Agent 节点集成

| 文件 | 变更 |
|------|------|
| `agent/nodes.py` | `rag_retriever_node` 从占位 stub 升级为调用真实 `HybridRetriever.retrieve()`，检索结果带来源标注格式化后写入 `AgentState.retrieved_docs` |
| `main.py` | `lifespan` 中调用 `init_retriever()`，非阻塞初始化，索引缺失时优雅降级 |

#### 5. 配置与依赖

| 文件 | 变更 |
|------|------|
| `config.py` | 新增 7 项 RAG 配置：`rag_collection_name`、`rag_chunks_path`、`rag_chunk_size`（500）、`rag_chunk_overlap`（100）、`rag_vector_top_k`（20）、`rag_bm25_top_k`（20）、`rag_final_top_k`（5）、`rag_enable_reranker`（False）、`rag_use_hyde`（False） |
| `requirements-rag.txt` | `chromadb>=0.5.0`、`rank-bm25>=0.2.2`、`sentence-transformers>=3.0.0`、`pymupdf>=1.24.0`、`jieba>=0.42.1` |

---

## 二、遇到的问题与解决方案

### 问题 1：HuggingFace 模型下载缓慢/卡住

**现象**：首次运行 ingest 时需下载 `bge-large-zh-v1.5` Embedding 模型（~1.3GB），直连 HuggingFace 速度极慢或超时。

**解决方案**：设置 HuggingFace 镜像加速：
```powershell
$env:HF_ENDPOINT="https://hf-mirror.com"
```
建议将此变量写入系统环境变量或 `.env` 中以持久化。

### 问题 2：FlagEmbedding 与 transformers 版本不兼容

**现象**：`from FlagEmbedding import FlagReranker` 报错 `ImportError: cannot import name 'is_torch_fx_available'`，原因是 FlagEmbedding 内部引用了 transformers 已移除的 API。

**解决方案**：放弃 FlagEmbedding，改用 `sentence-transformers` 的 `CrossEncoder` 类加载同一个 `bge-reranker-v2-m3` 模型，API 更稳定且已作为 RAG 依赖安装。同时将 FlagEmbedding 从 `requirements-rag.txt` 中移除。

### 问题 3：ChromaDB 后台线程阻止进程退出

**现象**：使用 `chromadb.PersistentClient` 后，Python 进程在主逻辑执行完毕后不退出（需手动终止或调用 `sys.exit(0)`）。

**影响**：仅影响 CLI 脚本和测试脚本，不影响 FastAPI Web 服务（lifespan 管理生命周期）。

**解决方案**：测试脚本末尾显式调用 `sys.exit(0)`。实际 Web 服务不受影响。

---

## 三、验证方法

### 1. 语法检查

```powershell
cd gas-copilot\backend
.venv\Scripts\python -c "import ast, pathlib; [ast.parse(f.read_text(encoding='utf-8')) for f in pathlib.Path('app').rglob('*.py')]; print('All files parse OK')"
```

**预期结果**：`All files parse OK`

### 2. 文档入库验证

```powershell
cd gas-copilot\backend
$env:HF_ENDPOINT="https://hf-mirror.com"
.venv\Scripts\python -m app.rag.ingest --create-sample
```

**预期结果**：
```
[ingest] Sample document created: data\docs\sample_regulation.txt
[ingest] Found 1 document(s) in data\docs
  - Processing: sample_regulation.txt
    Pages: 1, Chars: 1890, Chunks: 16
[ingest] Total chunks: 16
[ingest] Building ChromaDB collection...
[ingest] Saving BM25 chunks JSON...
[ingest] Done! Indices saved to:
  - ChromaDB: ./data/chroma
  - BM25 JSON: ./data/rag_chunks.json
```

验证索引文件：
```powershell
dir data\rag_chunks.json    # 应存在，约 8KB
dir data\chroma             # 应存在 chroma.sqlite3 文件
```

### 3. 检索器初始化验证

```powershell
$env:HF_ENDPOINT="https://hf-mirror.com"
.venv\Scripts\python -c "
import sys; import os; os.environ.setdefault('OPENAI_API_KEY','sk-test')
from app.rag.retriever import init_retriever
print('ready:', init_retriever())
sys.exit(0)
"
```

**预期结果**：
```
chroma_loaded    count=16 name=gas_regulations
bm25_index_built docs=16
hybrid_retriever_ready
ready: True
```

### 4. 混合检索端到端验证

```powershell
$env:HF_ENDPOINT="https://hf-mirror.com"
.venv\Scripts\python -c "
import asyncio, sys, os
os.environ.setdefault('OPENAI_API_KEY','sk-test')
from app.rag.retriever import init_retriever, get_retriever
init_retriever()
r = get_retriever()

async def test():
    results = await r.retrieve('管道泄漏的处置方法', top_k=3)
    print(f'Results: {len(results)}')
    for i, doc in enumerate(results):
        print(f'  [{i+1}] {doc[\"heading\"] or doc[\"text\"][:50]}')
    assert len(results) > 0
    print('Search OK')
    sys.exit(0)

asyncio.run(test())
"
```

**预期结果**：返回 3 条与"管道泄漏处置"相关的规范条款，如 4.2.2、4.2.3、4.1.3。

### 5. Agent RAG 路径端到端验证

```powershell
$env:HF_ENDPOINT="https://hf-mirror.com"
.venv\Scripts\python -c "
import asyncio, json, sys, os
os.environ.setdefault('OPENAI_API_KEY','sk-test')
from app.rag.retriever import init_retriever
init_retriever()

from unittest.mock import AsyncMock, patch
from langchain_core.messages import AIMessage, HumanMessage
from app.agent.graph import build_graph
from app.memory.checkpointer import get_memory_checkpointer

call_count = 0
async def mock_invoke(msgs, **kw):
    global call_count; call_count += 1
    if call_count == 1:
        return AIMessage(content=json.dumps({'decision':'need_rag','reasoning':'need docs','tool_calls':[]}))
    elif call_count == 2:
        return AIMessage(content=json.dumps({'verdict':'sufficient','reason':'got docs','missing':''}))
    return AIMessage(content='Based on regulation 4.2.2...')

async def main():
    g = build_graph(get_memory_checkpointer())
    with patch('app.agent.nodes.get_llm') as m:
        llm = AsyncMock(); llm.ainvoke = mock_invoke; m.return_value = llm
        nodes = []
        async for ev in g.astream({'messages':[HumanMessage(content='PE管泄漏处置')],'current_plan':'','planner_output':{},'tool_results':[],'retrieved_docs':[],'final_report':None,'iteration_count':0}, config={'configurable':{'thread_id':'rag-e2e'}}):
            nodes.extend(ev.keys())
    print(f'Nodes: {nodes}')
    assert nodes == ['planner','rag_retriever','reflector','responder']
    print('E2E RAG path verified!')
    sys.exit(0)

asyncio.run(main())
"
```

**预期结果**：
```
Nodes: ['planner', 'rag_retriever', 'reflector', 'responder']
E2E RAG path verified!
```

---

## 四、数据存放指南

### 你需要准备什么数据

RAG 系统的知识来源是**燃气行业的规范文档和技术资料**。建议入库以下文档：

| 文档类型 | 示例 | 优先级 |
|---------|------|:------:|
| **国家/行业标准** | GB 50028《城镇燃气设计规范》 | 高 |
| | CJJ 51《城镇燃气设施运行、维护和抢修安全技术规程》 | 高 |
| | GB/T 13611《城镇燃气分类和基本特性》 | 高 |
| | GB 50494《城镇燃气技术规范》 | 中 |
| | CJJ/T 153《城镇燃气管道非开挖修复更新工程技术规程》 | 中 |
| **企业内部文件** | 抢险应急预案 | 高 |
| | 操作规程 SOP | 高 |
| | 设备操作手册 | 中 |
| | 历史事故案例 | 中 |
| **培训材料** | 抢险人员培训教材 | 低 |
| | 安全知识题库 | 低 |

### 数据放在哪里

```
gas-copilot/
└── backend/
    └── data/
        ├── docs/                    ← 【在这里放文档】
        │   ├── GB50028_城镇燃气设计规范.pdf
        │   ├── CJJ51_运维抢修安全技术规程.pdf
        │   ├── 公司应急预案.pdf
        │   ├── 抢修操作手册.txt
        │   └── sample_regulation.txt   (内置测试样本，可删除)
        │
        ├── chroma/                  ← 向量索引（自动生成，勿手动修改）
        │   └── chroma.sqlite3
        ├── rag_chunks.json          ← BM25 分块数据（自动生成）
        └── inventory.json           ← 物资库存数据
```

### 入库流程

```powershell
# 1. 将 PDF/TXT 文件放入 data/docs/ 目录

# 2. 设置 HuggingFace 镜像（中国大陆加速）
$env:HF_ENDPOINT="https://hf-mirror.com"

# 3. 运行入库脚本
cd gas-copilot\backend
.venv\Scripts\python -m app.rag.ingest

# 4. 查看入库结果
# 终端会显示每个文件的页数、字符数、分块数
# 最后显示总分块数和索引存储路径
```

### 注意事项

1. **每次入库会重建索引** — 运行 `ingest` 会清除旧的 ChromaDB collection 并重建，确保数据一致性。如果新增了文档，需要重新运行 ingest（所有文档都需要在 `data/docs/` 中）。

2. **PDF 质量很重要** — 扫描版 PDF（图片型）无法直接提取文字，需要先做 OCR。建议使用文字型 PDF（可以选中复制文字的那种）。

3. **文件编码** — TXT/MD 文件应使用 UTF-8 编码。

4. **文档量建议** — 当前架构适合中小规模文档库（几十个文件、数千个分块）。如果文档量超过 10万分块，建议升级为客户端-服务器模式的向量数据库。

5. **Reranker 可选启用** — 在 `.env` 中设置 `RAG_ENABLE_RERANKER=true` 可启用交叉编码重排序，首次启用需下载 `bge-reranker-v2-m3` 模型（~1.1GB），会显著提升检索精度但增加约 0.5-1 秒延迟。

6. **Embedding 模型缓存** — `bge-large-zh-v1.5` 模型首次下载后缓存在 `C:\Users\<你的用户名>\.cache\huggingface\hub\`，后续启动秒级加载。

---

## 五、当前 RAG 模块结构

```
backend/app/rag/
├── ingest.py          # 文档入库 CLI（PDF解析 + 条款切片 + 索引构建）
├── retriever.py       # 混合检索器（向量 + BM25 并行 → RRF融合 → 可选Reranker）
└── reranker.py        # 交叉编码重排序器（懒加载 + 自动降级）

backend/data/
├── docs/              # 【用户放文档的目录】
├── chroma/            # ChromaDB 向量索引（自动生成）
└── rag_chunks.json    # BM25 分块数据（自动生成）
```

### Agent 调用流程

```
Planner (LLM 判断 → need_rag)
  └─→ rag_retriever_node
        ├─ 检索器已初始化 → HybridRetriever.retrieve(query)
        │   ├─ ChromaDB 向量检索 (并行)
        │   └─ BM25 关键词检索 (并行)
        │   └─ RRF 融合 → [可选 Reranker] → top-5 结果
        │   └─ 格式化为 "[来源: xxx.pdf | 第23页 | 4.2.2 ...]" 写入 state
        │
        └─ 检索器未初始化 → 返回提示 "请先运行 ingest 入库文档"
      └─→ Reflector → Responder
```

---

## 六、后续待办

- **入库真实文档**：将实际的燃气规范 PDF 放入 `data/docs/` 并运行 `python -m app.rag.ingest`
- **Reranker 模型下载**：网络条件好时设置 `RAG_ENABLE_RERANKER=true` 并重启服务，模型会自动下载
- **HyDE 查询扩展**：`rag_use_hyde` 配置项已预留，后续可实现基于 LLM 生成假设文档来提升向量检索质量
- **阶段 3 前端 UI**：对话流 UI + CoT 可视化面板 + 业务面板
