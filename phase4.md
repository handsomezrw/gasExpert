# 阶段 4 实施总结：前后端联调

> 对应 PLAN.md 阶段 4（已完成 [x]）

---

## 一、联调前的准备状态

### 已完成的基础设施

| 阶段 | 模块 | 状态 |
|------|------|:----:|
| 1 | 项目脚手架 + LangGraph Agent 骨架 | ✓ |
| 2 | 5 个工具箱 + RAG 混合检索管道 | ✓ |
| 3 | FastAPI SSE 端点 + 前端对话流 UI + CoT/业务面板 | ✓ |

### 当前模型配置

| 配置项 | 值 | 说明 |
|--------|-----|------|
| `OPENAI_API_BASE` | `https://api.deepseek.com` | DeepSeek API |
| `OPENAI_MODEL` | `deepseek-reasoner` | DeepSeek R1 推理模型 |
| 本地微调模型 | 未接入 | `consult_gas_expert` 自动降级到主 LLM |
| `WEATHER_API_HOST` | 已配置 | 和风天气专属 Host |
| `WEATHER_API_KEY` | 已配置 | 和风天气 API KEY |

---

## 二、联调中发现并修复的问题

### 问题 1：物资面板字段不匹配

**现象**：后端 `query_material_inventory` 返回 `station.items`，前端 `InventoryPanel` 读取 `station.materials`，导致面板渲染为空。

**修复**：`InventoryPanel.tsx` 增加 `items` 字段兼容：

```typescript
const stations = rawStations.map((s) => ({
  ...s,
  materials: s.materials ?? s.items ?? [],
}));
```

### 问题 2：天气面板字段不匹配

**现象**：

| 后端字段 | 前端原始读取 | 是否匹配 |
|----------|-------------|:--------:|
| `wind_direction` | `data.wind_dir \|\| data.windDir` | ✗ |
| `visibility_km` | `data.visibility` | ✗ |

**修复**：`WeatherPanel.tsx` 添加后端字段名 fallback：

```typescript
const windDir = data.wind_direction ?? data.wind_dir ?? data.windDir ?? "";
const visibility = data.visibility_km ?? data.visibility;
```

### 问题 3：风速单位标注错误

**现象**：和风天气返回 `windSpeed` 单位为 km/h，前端标注为 "m/s"。

**修复**：`WeatherPanel.tsx` 改为 `km/h`。

---

## 三、联调测试步骤

> 以下为完整的联调验证流程，请按顺序操作。

### 步骤 1：启动后端

```powershell
cd d:\aiProject\gas-copilot\backend
.venv\Scripts\uvicorn app.main:app --port 8080 --reload
```

**预期**：终端输出类似：
```
INFO:     gas-copilot ready model=deepseek-reasoner
INFO:     Uvicorn running on http://127.0.0.1:8080
```

确认看到 `rag_init ready=True`（如果已入库文档）。

### 步骤 2：启动前端

新开一个终端：

```powershell
cd d:\aiProject\gas-copilot\frontend
npm run dev
```

**预期**：Vite 输出 `Local: http://localhost:5173/`。

### 步骤 3：验证后端健康检查

浏览器访问：`http://localhost:5173/api/health`

**预期**：
```json
{"status": "ok", "service": "gas-copilot"}
```

如果返回 404 或无法连接 → 检查后端是否在 8080 端口运行、Vite proxy 配置。

### 步骤 4：端到端对话测试

打开 `http://localhost:5173/`，**新建对话**，依次测试以下场景：

#### 测试 A：疏散范围计算（工具调用链路）

输入：
```
成都武侯区发生天然气泄漏，管径DN200，压力0.4MPa，请计算疏散范围
```

**验证点**：
- [ ] CoT 面板显示 Planner 决策：`use_tools` + `calculate_evacuation_zone`
- [ ] CoT 面板显示工具执行完成（绿色状态）
- [ ] CoT 面板显示 Reflector 判定：`sufficient`
- [ ] 消息正文有疏散半径、影响面积、风险等级的文字回答
- [ ] **疏散面板**出现（红/黄/绿色边框），显示半径、面积、安全措施
- [ ] 回答基于工具返回的真实计算结果

#### 测试 B：物资库存查询（工具 + 面板渲染）

输入：
```
查询武侯区附近的应急物资库存情况
```

**验证点**：
- [ ] Planner 决策调用 `query_material_inventory`
- [ ] **物资面板**出现，列出站点名、距离、物资表格
- [ ] 物资表格有"物资名称"、"库存"、"状态"三列
- [ ] 每项物资根据数量显示"充足/偏低/紧张"状态标签

#### 测试 C：天气查询（异步工具 + 和风 API）

输入：
```
查询成都武侯区当前天气，评估对燃气泄漏处置的影响
```

**验证点**：
- [ ] Planner 决策调用 `get_weather_info`
- [ ] **天气面板**出现，显示温度、湿度、风速、能见度
- [ ] `source` 为"和风天气实时数据"（非模拟数据）
- [ ] 显示应急建议（高温/大风/降雨等条件相关）

#### 测试 D：知识库检索（RAG 链路）

输入：
```
根据国家规范，燃气管道泄漏的临时处置方法有哪些？
```

**验证点**：
- [ ] Planner 决策为 `need_rag`
- [ ] CoT 面板显示 `knowledge_search` 检索中/完成
- [ ] 回答中引用了 GB 50028 等规范条款内容
- [ ] 回答标注了来源信息

#### 测试 E：综合报告生成（多工具 + 报告面板）

输入：
```
武侯区XX路发生DN200天然气管道裂缝泄漏，压力0.3MPa，请综合评估并生成处置报告
```

**验证点**：
- [ ] Planner 可能发起多轮工具调用（天气 + 疏散 + 物资 + 报告）
- [ ] CoT 面板逐步展开各工具执行过程
- [ ] **报告面板**出现（绿色边框），含 Markdown 格式报告
- [ ] 报告面板有"下载"按钮，可导出 .md 文件
- [ ] 报告内容包含事故概况、环境评估、疏散方案等章节

#### 测试 F：普通对话（直接回答链路）

输入：
```
你好，你能做什么？
```

**验证点**：
- [ ] Planner 决策为 `direct_answer`
- [ ] 无工具调用、无面板
- [ ] 正常流式输出文字回答

### 步骤 5：会话功能测试

- [ ] 侧栏可新建多个对话
- [ ] 切换对话显示对应历史消息
- [ ] 删除对话正常工作
- [ ] 新对话首条消息自动截断为标题

---

## 四、架构通信链路（联调确认）

```
浏览器 (localhost:5173)
  │  POST /api/chat/stream  {message, session_id}
  │
  ├──── Vite Dev Proxy ──→ http://localhost:8080/api/chat/stream
  │                            │
  │                            ▼
  │                       FastAPI SSE Endpoint
  │                            │
  │                    ┌───────┼───────┐
  │                    ▼       ▼       ▼
  │                Planner  Tools   RAG
  │                (DeepSeek R1)    (ChromaDB + BM25)
  │                    │       │       │
  │                    ▼       ▼       ▼
  │                Reflector → Responder → SSE events
  │
  ◄──── SSE: token / tool_start / tool_end / panel_data / done
  │
  ▼
  Zustand Store → React UI
  ├── StreamingText (token 事件)
  ├── CoTSteps (tool_start / tool_end 事件)
  └── PanelRenderer (panel_data 事件)
      ├── EvacuationPanel
      ├── InventoryPanel
      ├── WeatherPanel
      └── ReportPanel
```

---

## 五、已修改文件清单

| 文件 | 变更 |
|------|------|
| `frontend/src/components/panels/InventoryPanel.tsx` | 兼容后端 `items` 字段，fallback `s.materials ?? s.items` |
| `frontend/src/components/panels/WeatherPanel.tsx` | 兼容 `wind_direction`、`visibility_km`；修正风速单位为 km/h |

---

## 六、注意事项与建议

### 1. 模型选择建议

当前使用 `deepseek-reasoner`（R1 推理模型），特点：
- 思考深度高，输出质量好
- **速度较慢**（单次 LLM 调用 10-30 秒），整条链路可能 30-90 秒
- JSON 结构化输出可靠性略低于 V3

如果联调时感到**响应太慢**，可在 `.env` 中改为：

```env
OPENAI_MODEL=deepseek-chat
```

`deepseek-chat`（V3）速度快 5-10 倍，JSON 遵循度更好，适合联调和日常使用。正式上线可根据需要切回 reasoner。

### 2. 本地微调模型

`consult_gas_expert` 工具当前自动降级到主 LLM（DeepSeek），功能正常但缺少专业微调知识。部署 vLLM 后只需配置：

```env
LOCAL_MODEL_URL=http://your-vllm-host:8000/v1
LOCAL_MODEL_NAME=your-gas-expert-model
```

### 3. RAG 入库

确保 `data/docs/` 中的 PDF 已通过 `python -m app.rag.ingest` 入库，否则知识库检索路径会返回"请先运行 ingest"提示。

### 4. 和风天气

已从旧版公用域名（`devapi.qweather.com`）迁移到专属 API Host 鉴权方式（`X-QW-Api-Key` 请求头），需在 `.env` 同时配置 `WEATHER_API_HOST` 和 `WEATHER_API_KEY`。

### 5. 会话持久化

LangGraph Agent 状态通过 `AsyncSqliteSaver` 持久化在 `data/copilot_checkpoints.db`。重启后端后同一 `session_id` 的对话上下文可恢复。但前端 Zustand 状态是内存态，刷新页面后会话列表重置为 Mock 数据（历史会话 REST 接口 `GET /api/history/sessions` 当前为 TODO 状态，返回空列表）。

---

## 七、后续待办

- **阶段 5**：LangSmith 全链路追踪 + Docker 容器化
- **历史会话持久化**：将 `history.py` 路由与 SQLAlchemy `Session` / `Message` 模型对接，前端启动时加载历史会话
- **前端刷新保持**：移除 Mock 数据，改为从后端 `/api/history/sessions` 加载
