# 阶段 3-2：前端对话流 UI

> 完成时间：2026-03-28

## 一、完成内容概述

实现了 ChatGPT 风格的前端对话流 UI，包含侧栏会话管理、Markdown 渲染、逐 token 流式文本、SSE 消费层、Zustand 状态管理。

---

## 二、新增依赖

| 包 | 用途 |
|---|---|
| `react-markdown` | 将 Assistant 回复中的 Markdown 渲染为 React 组件 |
| `remark-gfm` | 支持 GFM 扩展（表格、删除线、任务列表等） |
| `recharts` | 为 Phase 3-3 业务面板图表预装 |

## 三、修改/新增文件清单

### 基础层

| 文件 | 变更 |
|------|------|
| `vite.config.ts` | 代理目标从 `localhost:8000` → `localhost:8080` |
| `src/types/index.ts` | `ToolCallEvent.timestamp` 替代原 `startTime/endTime` |
| `src/index.css` | 新增 `.markdown-body` 样式（标题、列表、表格、引用块等） |

### 状态管理 — `src/stores/chatStore.ts`（全部重写）

**架构变更：**
- `messagesMap: Record<string, ChatMessage[]>` — 消息按会话 ID 分组存储，切换会话零延迟
- 会话管理：`createSession` / `switchSession` / `deleteSession`
- 消息管理：`addMessage` / `appendToLastAssistant`
- 工具与面板数据存储在**消息级别**：`addToolCallToLast` / `updateToolCallInLast` / `addPanelDataToLast`
- UI 状态：`sidebarOpen` / `toggleSidebar`
- **Mock 数据**：预置 2 个演示会话（武侯区疏散计算、高新区物资查询），含完整的 toolCalls 和 panelData

### SSE 消费层 — `src/services/sse.ts`

**改进：**
- 回调拆分：`onToolCall` → `onToolStart` + `onToolEnd`，分别处理开始/完成事件
- 修复 `onDone` 双重调用 bug（`doneReceived` 标志防重复）
- 为每个 `ToolCallEvent` 正确映射 `timestamp` 字段
- fetch 异常 try/catch 全覆盖

### UI 组件

| 组件 | 文件 | 说明 |
|------|------|------|
| **App** | `src/App.tsx` | 顶层布局：Sidebar + Header + ChatWindow |
| **Sidebar** | `src/components/Sidebar.tsx` | 左侧会话列表，"新建对话"按钮，按日期分组（今天/昨天/近7天），删除会话 |
| **ChatWindow** | `src/components/chat/ChatWindow.tsx` | 主聊天区：消息列表 + 空状态欢迎页 + 4 个快捷提问卡片 + ChatInput |
| **ChatInput** | `src/components/chat/ChatInput.tsx` | 底部输入区：自动增高 Textarea + 发送按钮，Enter 发送 / Shift+Enter 换行 |
| **MessageItem** | `src/components/chat/MessageItem.tsx` | 单条消息：Avatar + 内容（用户纯文本 / 助手 Markdown），流式时显示光标，空内容时显示跳动点思考动画 |
| **MarkdownContent** | `src/components/chat/MarkdownContent.tsx` | react-markdown + remark-gfm，自定义 table/th/td/code 渲染组件 |
| **StreamingText** | `src/components/chat/StreamingText.tsx` | MarkdownContent + 闪烁光标块 |

### 设计风格

- 参照 ChatGPT 布局：左侧侧栏 + 居中消息流（max-w-3xl）+ 底部输入框
- Avatar：用户使用 `User` 图标（蓝灰），AI 使用 `Flame` 图标（琥珀色 — 燃气主题）
- 消息不使用气泡，左对齐展示，与 ChatGPT 一致
- 空状态：燃气图标 + 功能介绍 + 4 个快捷提问卡片

---

## 四、Mock 数据说明

页面首次加载时，侧栏显示 2 个预置会话（含完整对话消息），无需后端即可查看 UI 效果。

**如何替换为真实数据：**
- 在 `chatStore.ts` 中删除 `MOCK_SESSIONS` 和 `MOCK_MESSAGES` 常量
- 将 `sessions` 初始值改为 `[]`、`messagesMap` 初始值改为 `{}`
- 或在 Phase 4 联调时，从后端 API `/api/history/sessions` 加载历史会话

---

## 五、验证

### 5.1 构建验证

```bash
cd gas-copilot/frontend
npm run build
# ✅ tsc 类型检查通过
# ✅ vite build 成功，产物 dist/ 约 363 KB (gzipped 113 KB)
```

### 5.2 开发服务器

```bash
npm run dev
# 浏览器打开 http://localhost:5173
# 可看到完整的 ChatGPT 风格界面 + mock 数据
```

### 5.3 与后端联调测试

1. 启动后端：`cd backend && uvicorn app.main:app --port 8080`
2. 启动前端：`cd frontend && npm run dev`
3. 打开 `http://localhost:5173`
4. 新建对话 → 输入问题 → 观察 SSE 流式响应

---

## 六、启动方式

```bash
# 终端 1：启动后端
cd gas-copilot/backend
.venv\Scripts\Activate.ps1
uvicorn app.main:app --host 0.0.0.0 --port 8080

# 终端 2：启动前端
cd gas-copilot/frontend
npm run dev
# 访问 http://localhost:5173
```
