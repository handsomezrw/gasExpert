# 阶段 1 实施总结

> 对应 PLAN.md 中已完成（[x]）的两项任务

---

## 一、完成的工作

### 任务 1：项目脚手架搭建

**前端 (Vite + React 19 + TypeScript + shadcn/ui)**

| 项目 | 完成内容 |
|------|---------|
| 初始化 | `npm create vite@latest` 创建项目，手动转换为 React + TS 模板 |
| Tailwind CSS v4 | 安装 `tailwindcss` + `@tailwindcss/vite` 插件 |
| shadcn/ui | `npx shadcn@latest init`（base-nova 风格，含 CSS 变量 + 暗色模式） |
| 路径别名 | `@/*` → `./src/*`（tsconfig.json + vite.config.ts） |
| 开发代理 | `/api` → `localhost:8000` |
| 组件骨架 | `chat/` (ChatWindow, MessageBubble, StreamingText, CoTCollapsible)、`panels/` (MaterialPanel, EvacuationMap) |
| 状态管理 | Zustand stores (chatStore, panelStore) |
| 通信层 | `services/api.ts` (REST) + `services/sse.ts` (SSE 流式消费) |
| 类型定义 | `types/index.ts`（ChatMessage, ToolCallEvent, PanelData, SSEEvent 等） |

**后端 (FastAPI)**

| 项目 | 完成内容 |
|------|---------|
| 项目结构 | `api/routes`、`agent`、`tools`、`rag`、`memory` 五大模块 |
| API 端点 | `/api/health`、`/api/chat/stream` (SSE)、`/api/history/sessions` |
| 配置管理 | Pydantic Settings + `.env.example` |
| 依赖文件 | `requirements.txt`（核心）+ `requirements-rag.txt`（Phase 2 ML 依赖） |
| 容器化准备 | `Dockerfile`（前后端各一）+ `docker-compose.yml` + `nginx.conf` |

### 任务 2：LangGraph Agent 核心引擎

| 文件 | 实现内容 |
|------|---------|
| `agent/state.py` | `AgentState` TypedDict：messages (带 add_messages reducer)、current_plan、planner_output、tool_results、retrieved_docs、final_report、iteration_count |
| `agent/llm.py` | 缓存的 `ChatOpenAI` 工厂函数 + `extract_json()` 从 LLM 输出中鲁棒提取 JSON |
| `agent/prompts.py` | 三套 Prompt 模板：PLANNER（含动态工具描述注入）、REFLECTOR（含已收集信息 + 迭代轮次）、RESPONDER（含上下文注入） |
| `agent/nodes.py` | 5 个节点全部接入真实 LLM 调用 + 2 个条件边路由函数（详见下方） |
| `agent/graph.py` | `build_graph(checkpointer)` → 编译出 `CompiledStateGraph` |
| `tools/__init__.py` | 工具注册表：`ALL_TOOLS` / `TOOL_MAP` / `get_tool_descriptions()` |
| `memory/checkpointer.py` | 双方案：`MemorySaver`（开发）+ `AsyncSqliteSaver`（生产持久化） |
| `api/routes/chat.py` | SSE 端点对接 Graph `astream()`，按节点输出分发 tool_start/tool_end/panel_data/token/done 事件 |
| `api/deps.py` | `get_agent_graph()` 依赖注入，从 `app.state` 读取编译后的 graph |
| `main.py` | Lifespan 中初始化 checkpointer → 编译 graph → 存入 `app.state` |

**Agent 执行流程：**

```
用户消息 → Planner (LLM JSON决策)
             ├─ use_tools → Tool Executor (分发执行) → Reflector (LLM判断充分性)
             ├─ need_rag  → RAG Retriever (Phase 2) → Reflector
             └─ direct_answer → Responder (LLM生成回答) → END
                                          ↑
                            Reflector ─── sufficient ───→ Responder
                                    └──── need_more ────→ Planner (重新规划)
```

**关键设计决策：**

- 最大迭代 3 轮（`MAX_ITERATIONS = 3`）防止 Planner↔Reflector 无限循环
- Planner 每轮注入已收集的 tool_results + retrieved_docs 避免重复调用
- 工具执行失败时记录 error 而非中断流程，保证 graceful degradation
- LLM JSON 输出使用正则提取（兼容 markdown 代码块包裹），解析失败回退 `direct_answer`

---

## 二、遇到的问题与解决方案

### 问题 1：Vite v8 模板不匹配

**现象**：`npm create vite@latest frontend -- --template react-ts` 实际生成了 vanilla TypeScript 项目（`main.ts` + `counter.ts`），而非 React + TS。

**原因**：Vite v8 的 `react-ts` 模板行为变更。

**解决方案**：手动将 vanilla TS 模板转换为 React 项目——删除旧模板文件，安装 `react`、`react-dom`、`@vitejs/plugin-react`、`@types/react`、`@types/react-dom`，手动创建 `main.tsx`、`App.tsx`、`vite.config.ts`，配置 `tsconfig.json` 启用 `jsx: "react-jsx"`。

### 问题 2：中文弯引号导致 Python 语法错误

**现象**：`gas_expert.py` 第 14 行 `SyntaxError: invalid syntax`。

**原因**：f-string 中使用了中文弯引号 `\u201c \u201d`（`""`），Python 解释器无法正确解析。

**解决方案**：将 f-string 外层引号从双引号改为单引号，内部中文弯引号改为英文双引号：
```python
# 修复前（报错）
return f"[专家模型占位回答] 关于\u201c{query}\u201d的专业建议：..."

# 修复后
return f'[专家模型占位回答] 关于"{query}"的专业建议：...'
```

### 问题 3：greenlet 编译失败

**现象**：`pip install` 时 `greenlet` 构建失败，报 `Microsoft Visual C++ 14.0 or greater is required`。

**原因**：初始虚拟环境使用了 Python 3.9.0，`greenlet` 最新版（4.x）没有为 Python 3.9 提供预编译 wheel，回退到源码编译需要 MSVC。

**解决方案**：系统已安装 Python 3.12.7，用 `py -3.12 -m venv .venv` 重建虚拟环境。Python 3.12 有完整的预编译 wheel 支持，所有依赖一次安装成功。

### 问题 4：pip SSL / 代理连接失败

**现象**：`pip install` 报 `SSLError` 或 `ProxyError('Cannot connect to proxy.')`。

**原因**：系统配置了代理 `127.0.0.1:7890`（Clash 等代理软件），pip 通过 Windows 系统代理设置自动使用，但 pip 进程未正确继承代理环境变量。

**解决方案**：显式设置环境变量后再执行安装：
```powershell
$env:HTTPS_PROXY="http://127.0.0.1:7890"
$env:HTTP_PROXY="http://127.0.0.1:7890"
.venv\Scripts\pip install -r requirements.txt
```

### 问题 5：uuid-utils DLL 加载失败

**现象**：`ImportError: DLL load failed while importing _uuid_utils`。

**原因**：`langchain-core` 依赖的 `uuid-utils` 包的编译扩展与 Python 3.9.0 不兼容。

**解决方案**：升级到 Python 3.12 虚拟环境后此问题自动消失（同问题 3 一并解决）。

---

## 三、验证方法

### 1. 前端编译验证

```bash
cd gas-copilot/frontend
npm install        # 安装依赖（如已安装可跳过）
npx tsc --noEmit   # TypeScript 类型检查，应输出零错误
npm run dev         # 启动开发服务器，浏览器访问 http://localhost:5173
```

预期结果：页面显示"燃气抢险智能副驾"标题 + 聊天输入框。

### 2. 后端语法检查

```bash
cd gas-copilot/backend
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux

python -c "
import ast, pathlib
for f in pathlib.Path('app').rglob('*.py'):
    ast.parse(f.read_text(encoding='utf-8'))
print('All files parse OK')
"
```

预期结果：`All files parse OK`。

### 3. 模块导入验证

```bash
cd gas-copilot/backend
.venv\Scripts\python -c "
from app.config import get_settings
from app.tools import ALL_TOOLS, TOOL_MAP
from app.agent.state import AgentState
from app.agent.llm import get_llm, extract_json
from app.agent.nodes import planner_node, tool_executor_node, rag_retriever_node, reflector_node, responder_node
from app.agent.graph import build_graph
from app.memory.checkpointer import get_memory_checkpointer

g = build_graph(get_memory_checkpointer())
print(f'Tools: {len(ALL_TOOLS)}')
print(f'Graph: {type(g).__name__}')
print('All imports OK')
"
```

预期结果：
```
Tools: 5
Graph: CompiledStateGraph
All imports OK
```

### 4. Agent 端到端流程验证（Mock LLM）

```bash
cd gas-copilot/backend
.venv\Scripts\python -c "
import asyncio, json, os
os.environ['OPENAI_API_KEY'] = 'sk-test'
from unittest.mock import AsyncMock, patch
from langchain_core.messages import AIMessage, HumanMessage
from app.agent.graph import build_graph
from app.memory.checkpointer import get_memory_checkpointer

call_count = 0
async def mock_invoke(msgs, **kw):
    global call_count; call_count += 1
    if call_count == 1:
        return AIMessage(content=json.dumps({'decision':'use_tools','reasoning':'test','tool_calls':[{'name':'calculate_evacuation_zone','args':{'pressure':0.4,'diameter':200,'leak_type':'crack'}}]}))
    elif call_count == 2:
        return AIMessage(content=json.dumps({'verdict':'sufficient','reason':'ok','missing':''}))
    return AIMessage(content='evacuation radius is 17.9m')

async def main():
    g = build_graph(get_memory_checkpointer())
    with patch('app.agent.nodes.get_llm') as m:
        llm = AsyncMock(); llm.ainvoke = mock_invoke; m.return_value = llm
        nodes = []
        async for ev in g.astream({'messages':[HumanMessage(content='test')],'current_plan':'','planner_output':{},'tool_results':[],'retrieved_docs':[],'final_report':None,'iteration_count':0}, config={'configurable':{'thread_id':'t1'}}):
            nodes.extend(ev.keys())
    print(f'Executed nodes: {nodes}')
    assert nodes == ['planner','tool_executor','reflector','responder'], f'Unexpected: {nodes}'
    print('E2E flow verified!')

asyncio.run(main())
"
```

预期结果：
```
Executed nodes: ['planner', 'tool_executor', 'reflector', 'responder']
E2E flow verified!
```

### 5. FastAPI 启动验证

```bash
cd gas-copilot/backend
cp .env.example .env   # 编辑 .env 填入 OPENAI_API_KEY
.venv\Scripts\uvicorn app.main:app --reload
```

然后访问：
- `http://localhost:8000/docs` — Swagger UI 文档页
- `http://localhost:8000/api/health` — 应返回 `{"status": "ok", "service": "gas-copilot"}`

---

## 四、当前项目结构

```
gas-copilot/
├── frontend/                        # React 19 + TS + Tailwind v4 + shadcn/ui
│   ├── src/
│   │   ├── components/chat/         # ChatWindow, MessageBubble, StreamingText, CoTCollapsible
│   │   ├── components/panels/       # MaterialPanel, EvacuationMap
│   │   ├── components/ui/           # shadcn button (更多组件按需添加)
│   │   ├── lib/utils.ts             # cn() 工具函数
│   │   ├── stores/                  # chatStore.ts, panelStore.ts (Zustand)
│   │   ├── services/                # api.ts (REST), sse.ts (SSE 流式)
│   │   ├── types/index.ts           # 全部 TS 类型
│   │   ├── App.tsx, main.tsx, index.css
│   │   └── vite-env.d.ts
│   ├── vite.config.ts, tsconfig.json, components.json
│   ├── Dockerfile, nginx.conf
│   └── package.json
├── backend/                         # FastAPI + LangGraph
│   ├── app/
│   │   ├── main.py                  # Lifespan 初始化 graph
│   │   ├── config.py                # Pydantic Settings
│   │   ├── api/routes/              # health.py, chat.py (SSE), history.py
│   │   ├── api/deps.py              # 依赖注入
│   │   ├── agent/                   # graph.py, nodes.py, state.py, prompts.py, llm.py
│   │   ├── tools/                   # __init__.py (注册表), weather, evacuation, inventory, gas_expert, report
│   │   ├── rag/                     # retriever.py, reranker.py, ingest.py (Phase 2 stub)
│   │   └── memory/                  # checkpointer.py, models.py
│   ├── data/docs/                   # 燃气规范 PDF 存放处
│   ├── .venv/                       # Python 3.12 虚拟环境
│   ├── requirements.txt             # 核心依赖
│   ├── requirements-rag.txt         # Phase 2 RAG 依赖
│   ├── Dockerfile, .env.example
├── docker-compose.yml
├── PLAN.md
├── SUMMARY.md
└── README.md
```
