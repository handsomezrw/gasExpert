# 阶段 3-1：FastAPI SSE 流式端点

> 完成时间：2026-03-27

## 一、完成内容概述

本阶段实现了 `/api/chat/stream` SSE 流式端点的生产级升级，输出 **token / tool_start / tool_end / panel_data / done** 五种标准事件类型，支持真正的逐 token 实时流式输出。

---

## 二、修改文件清单

### 1. `app/agent/llm.py` — LLM 流式适配

**改动要点：**

- 启用 `streaming=True`，使 ChatOpenAI 实例支持逐 token 推送
- 自动适配 `deepseek-reasoner` 的温度限制：该模型不支持自定义 `temperature` 参数，代码中做了条件判断，仅对非 reasoner 模型设置 `temperature=0`

```python
@lru_cache
def get_llm() -> ChatOpenAI:
    settings = get_settings()
    kwargs: dict = {
        "model": settings.openai_model,
        "api_key": settings.openai_api_key,
        "base_url": settings.openai_api_base,
        "streaming": True,
    }
    if "reasoner" not in settings.openai_model:
        kwargs["temperature"] = 0
    return ChatOpenAI(**kwargs)
```

### 2. `app/api/routes/chat.py` — SSE 流式端点完整重写

**架构设计 — 双策略 + 自动降级：**

| 策略 | 方法 | 特点 |
|------|------|------|
| 主策略 | `graph.astream_events(version="v2")` | 真正的逐 token 流式输出，实时推送 Responder 每个字符 |
| 备用策略 | `graph.astream()` | 节点级输出，Responder 文本整块发送（自动降级，无需配置） |

**5 种 SSE 事件类型：**

| 事件 | 触发时机 | 数据结构 |
|------|---------|----------|
| `tool_start` | Planner 决策完成 / 工具开始执行 / Reflector 判定 | `{id, name, args, status, result, timestamp}` |
| `tool_end` | 工具执行完毕 / RAG 检索完毕 | `{id, name, args, status, result, timestamp}` |
| `panel_data` | 工具返回结构化数据（疏散/库存/天气/报告） | `{type, data}` |
| `token` | Responder LLM 逐 token 输出 | `{content}` |
| `done` | 流结束 | `{session_id, timestamp}` |

**关键改进：**

1. **真正的 token 流**：通过 `astream_events(version="v2")` 拦截 `on_chat_model_stream` 事件，Responder 的每个 token 在生成时立即推送到客户端，而非等待整个回复完成
2. **实时时间戳**：所有事件携带毫秒级 epoch 时间戳（前端可直接 `new Date(timestamp)`）
3. **tool_start / tool_end 配对**：Planner 决策后自动预告即将执行的工具列表（status=running），工具完成后发送 tool_end（status=done/error）
4. **panel_data 修复**：适配新版 inventory 工具返回的完整 dict 结构，新增 `generate_report` → `report` 面板类型映射
5. **session_id 自动生成**：`ChatRequest.session_id` 改为可选字段，未提供时自动生成 UUID
6. **事件去重**：通过输出结构校验和计数器机制，避免 astream_events 内部嵌套链产生重复事件

**事件流示例（工具调用场景）：**

```
Client POST /api/chat/stream
  ↓
  tool_start {planner, decision: "use_tools"}     ← Planner 决策
  tool_start {calculate_evacuation_zone, running}  ← 预告工具执行
  tool_end   {calculate_evacuation_zone, done}     ← 工具完成
  panel_data {type: "evacuation", data: {...}}     ← 结构化面板数据
  tool_start {reflector, verdict: "sufficient"}    ← Reflector 判定
  token      {content: "根据"}                     ← 逐 token 流式
  token      {content: "计算"}
  token      {content: "结果"}
  ...（数百个 token 事件）
  done       {session_id, timestamp}               ← 流结束
```

**面板类型映射：**

| 工具函数名 | panel_data.type | 前端面板 |
|-----------|----------------|---------|
| `calculate_evacuation_zone` | `evacuation` | 疏散范围面板 |
| `query_material_inventory` | `inventory` | 物资库存面板 |
| `get_weather_info` | `weather` | 天气信息面板 |
| `generate_report` | `report` | 报告面板 |

---

## 三、遇到的问题及解决

### 问题 1：`--reload` 文件监听导致服务器重启

**现象**：测试脚本写入 `backend/` 目录后，uvicorn 的 WatchFiles 检测到文件变更，触发服务器热重载，中断正在进行的 SSE 流，客户端收到 `RemoteProtocolError: peer closed connection`。

**解决**：测试时不使用 `--reload` 参数启动 uvicorn，避免文件监听干扰。生产部署也不应使用 `--reload`。

### 问题 2：DeepSeek Reasoner 模型的 temperature 限制

**现象**：`deepseek-reasoner` 模型不支持自定义 `temperature` 参数（仅接受默认值），强制设置可能导致 API 报错。

**解决**：在 `get_llm()` 中添加条件判断，仅对非 reasoner 模型设置 `temperature=0`。

### 问题 3：astream_events 嵌套链事件去重

**现象**：`graph.astream_events()` 会为每个内部链（RunnableSequence 等）产生独立事件，同一个节点可能触发多个 `on_chain_end`，导致重复的 SSE 事件。

**解决**：通过检查事件输出结构（如 `planner_output`、`tool_results` 等特征键）过滤出真正的节点级输出；对 tool_results 使用计数器 `emitted_tool_count` 跟踪已发送的结果，仅发送新增部分。

---

## 四、验证流程

### 4.1 语法与导入检查

```bash
cd gas-copilot/backend
python -c "import py_compile; py_compile.compile('app/api/routes/chat.py', doraise=True); print('OK')"
python -c "from app.api.routes.chat import router; print('import OK')"
```

### 4.2 服务启动验证

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8080
# 确认日志输出: gas-copilot ready, Application startup complete
```

### 4.3 简单对话测试（direct_answer 路径）

发送 `"你好，简单介绍一下你自己"` → 验证事件流：

```
结果: tool_start:1, token:231, done:1
```

- Planner 决策 `direct_answer`，跳过工具执行
- 231 个 token 事件 → 真正的逐 token 流式输出
- done 事件正常关闭

### 4.4 工具调用测试（use_tools 路径）

发送 `"成都武侯区发生天然气泄漏，管径DN200，压力0.4MPa，请计算疏散范围"` → 验证事件流：

```
结果: tool_start:3, tool_end:1, panel_data:1, token:410, done:1
```

- Planner 决策 `use_tools`，调用 `calculate_evacuation_zone`
- tool_start × 3：planner 决策 + 工具预告 + reflector 判定
- tool_end × 1：疏散计算完成
- panel_data × 1：evacuation 面板数据
- token × 410：逐 token 流式最终回复
- Reflector 判定 `sufficient`，直接进入 Responder

---

## 五、API 配置说明

当前 `.env` 配置已可正常工作，**无需额外修改**：

```env
OPENAI_API_KEY=sk-xxxx
OPENAI_API_BASE=https://api.deepseek.com
OPENAI_MODEL=deepseek-reasoner
```

**可选优化建议**：如需更快响应速度，可将 `OPENAI_MODEL` 改为 `deepseek-chat`。Reasoner 模型会先进行内部推理再给出答案，对话场景下 `deepseek-chat` 响应更快、成本更低。需要更强推理能力时保持 `deepseek-reasoner`。

---

## 六、前端对接指南

前端通过 `POST /api/chat/stream` 建立 SSE 连接，请求体：

```json
{
  "message": "用户输入内容",
  "session_id": "可选，不传则自动生成 UUID"
}
```

前端 SSE 消费伪代码：

```typescript
const source = new EventSource('/api/chat/stream', { method: 'POST', body: ... });
// 或使用 fetch + ReadableStream 解析 SSE

// 处理事件
onEvent('tool_start', (data) => { /* 显示 CoT 面板：节点开始 */ });
onEvent('tool_end',   (data) => { /* 更新 CoT 面板：节点完成 */ });
onEvent('panel_data', (data) => { /* 渲染业务面板：疏散/库存/天气/报告 */ });
onEvent('token',      (data) => { /* 追加到消息气泡 */ });
onEvent('done',       (data) => { /* 标记流结束，启用输入框 */ });
onEvent('error',      (data) => { /* 显示错误提示 */ });
```
