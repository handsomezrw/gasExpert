# 燃气抢险智能副驾 (Gas Emergency Copilot) · gasExpert

> 燃气管道泄漏事故的应急处置方案生成  
> 基于 LangGraph + DeepSeek + RAG 的燃气抢险辅助决策系统

---

## 功能概览

| 能力 | 说明 |
|------|------|
| 疏散范围计算 | 根据管道压力/管径/泄漏类型，按 GB 50028 标准自动计算疏散半径 |
| 物资库存查询 | 查询事发地周边抢险站库存，按距离排序 |
| 实时天气查询 | 和风天气 API 接入，附带燃气抢险气象建议 |
| 知识库检索 | 混合检索（向量 + BM25 + RRF 融合），支持燃气规范 PDF 入库 |
| 专家咨询 | 可对接本地微调模型，降级走主 LLM |
| 处置报告生成 | LLM 生成结构化 Markdown 报告，支持下载 |
| CoT 思维链面板 | 实时展示 Agent 规划 → 工具调用 → 反思过程 |

## 技术栈

| 层 | 技术 |
|----|------|
| 前端 | React 19 · TypeScript · Tailwind CSS 4 · Zustand · Vite 8 |
| 后端 | FastAPI · LangGraph · LangChain · SSE 流式 |
| 模型 | DeepSeek（可切换 OpenAI 兼容接口）· bge-large-zh-v1.5（Embedding） |
| 检索 | ChromaDB 向量库 · BM25 关键词检索 · RRF 融合 · BGE-Reranker（可选） |
| 存储 | SQLite（会话持久化 + LangGraph Checkpoint） |
| 可观测性 | structlog 结构化日志 · LangSmith 全链路追踪（可选） |

---

## 快速开始

### 前置条件

- Python 3.11+
- Node.js 18+
- DeepSeek / OpenAI 兼容 API Key
- （可选）和风天气 API Host + Key

### 1. 克隆 & 配置

```bash
git clone <repo-url> && cd gas-copilot

# 后端环境
cd backend
cp .env.example .env        # 编辑 .env，填入 API 密钥
python -m venv .venv
.venv/Scripts/activate       # Windows
pip install -r requirements-rag.txt
```

### 2. 文档入库（可选，启用 RAG）

将燃气规范 PDF 放入 `backend/data/docs/`，然后：

```bash
cd backend
python -m app.rag.ingest
```

### 3. 启动后端

```bash
cd backend
uvicorn app.main:app --port 8080 --reload
```

### 4. 启动前端

```bash
cd frontend
npm install
npm run dev
```

打开 `http://localhost:5173` 即可使用。

---

## Docker 一键启动

```bash
# 1. 配置后端环境变量
cp backend/.env.example backend/.env
# 编辑 backend/.env 填入 API Key

# 2. 构建并启动
docker-compose up --build -d

# 前端: http://localhost:3000
# 后端: http://localhost:8080/api/health
```

---

## 可观测性

### structlog 结构化日志

- 开发模式（终端 TTY）：彩色控制台输出
- 生产模式（Docker / `LOG_FORMAT=json`）：JSON Lines 格式
- 每个 HTTP 请求自动记录 method、path、status、elapsed_ms

### LangSmith 追踪（可选）

在 `.env` 中配置：

```env
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=lsv2_pt_xxx
LANGCHAIN_PROJECT=gas-copilot
```

启用后，每次 Agent 调用链路（Planner → Tools → Reflector → Responder）将自动上报到 [LangSmith](https://smith.langchain.com)，可查看：
- 每个节点的输入/输出
- LLM 调用耗时与 token 用量
- 工具执行结果
- RAG 检索命中文档

---

## 项目结构

```
gas-copilot/
├── frontend/                    # React + Vite 前端
│   ├── src/
│   │   ├── components/
│   │   │   ├── chat/            # 对话组件（ChatWindow, MessageItem, CoTSteps...）
│   │   │   └── panels/          # 业务面板（Evacuation, Inventory, Weather, Report）
│   │   ├── services/sse.ts      # SSE 流式通信
│   │   └── stores/chatStore.ts  # Zustand 状态管理
│   ├── Dockerfile
│   └── nginx.conf
├── backend/                     # FastAPI 后端
│   ├── app/
│   │   ├── agent/               # LangGraph 状态图 + 节点
│   │   ├── api/routes/          # REST/SSE 端点
│   │   ├── rag/                 # 混合检索管道
│   │   ├── tools/               # 5 个结构化工具
│   │   ├── memory/              # 会话持久化
│   │   ├── logging_config.py    # structlog 配置
│   │   └── main.py              # FastAPI 入口
│   ├── data/
│   │   └── docs/                # 放置燃气规范 PDF
│   ├── Dockerfile
│   └── .env.example
├── docker-compose.yml
└── README.md
```

---

## 配置项速查

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `OPENAI_API_KEY` | LLM API Key | — |
| `OPENAI_API_BASE` | API 基地址 | `https://api.openai.com/v1` |
| `OPENAI_MODEL` | 模型名称 | `gpt-4o` |
| `WEATHER_API_HOST` | 和风天气 API Host | — |
| `WEATHER_API_KEY` | 和风天气 Key | — |
| `LANGCHAIN_TRACING_V2` | 启用 LangSmith 追踪 | `false` |
| `LANGCHAIN_API_KEY` | LangSmith API Key | — |
| `RAG_ENABLE_RERANKER` | 启用 BGE 重排序 | `false` |
| `LOG_FORMAT` | 强制 JSON 日志 | 自动检测 |
