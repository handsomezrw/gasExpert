# 阶段 3-3：CoT 可视化面板 + 结构化业务面板

> 完成时间：2026-03-28

## 一、完成内容概述

实现了 Agent 思维链（CoT）时间线可视化组件和 4 个结构化业务面板（疏散范围、物资库存、天气信息、处置报告），并将它们接入消息流，在助手回复中内联展示。

---

## 二、新增/修改文件

### CoT 可视化

| 文件 | 说明 |
|------|------|
| `src/components/chat/CoTSteps.tsx` | 全新的思维链时间线组件，替代原 CoTCollapsible |

**CoTSteps 功能：**
- **折叠/展开**：默认折叠，显示摘要（如"已完成 3 个步骤"）
- **时间线**：左侧竖线连接各步骤，类似 Git log 视觉
- **状态指示**：每步显示状态图标（`Loader2` 旋转 = running, `CheckCircle2` 绿色 = done, `XCircle` 红色 = error）
- **图标映射**：`planner` → Brain, `reflector` → CheckCircle2, `knowledge_search` → Search, 其他工具 → Wrench
- **中文标签**：所有工具名映射为中文（如 `calculate_evacuation_zone` → "疏散范围计算"）
- **详情展开**：每步可再次点击展开参数和结果的 JSON
- **实时反馈**：流式过程中显示"正在处理..."和旋转图标

### 结构化业务面板

| 文件 | 面板类型 | 说明 |
|------|---------|------|
| `src/components/panels/PanelRenderer.tsx` | 路由 | 根据 `panel.type` 动态渲染对应面板 |
| `src/components/panels/EvacuationPanel.tsx` | `evacuation` | 疏散范围面板 — 红/橙/绿三级风险色彩主题 |
| `src/components/panels/InventoryPanel.tsx` | `inventory` | 物资库存面板 — 站点列表 + 物资表格 + 库存状态徽章 |
| `src/components/panels/WeatherPanel.tsx` | `weather` | 天气信息面板 — 温度/湿度/风速/能见度指标卡片 |
| `src/components/panels/ReportPanel.tsx` | `report` | 处置报告面板 — Markdown 渲染 + 一键下载 |

### 面板接入

| 文件 | 变更 |
|------|------|
| `src/components/chat/MessageItem.tsx` | 在助手消息中内联渲染 CoTSteps 和 PanelRenderer |

---

## 三、各面板设计详情

### 1. EvacuationPanel（疏散范围）

**色彩主题**：根据风险等级自动切换
| 风险等级 | 背景 | 边框 | 文字 |
|---------|------|------|------|
| 高危 | `bg-red-50` | `border-red-200` | `text-red-700` |
| 中危 | `bg-amber-50` | `border-amber-200` | `text-amber-700` |
| 低危 | `bg-green-50` | `border-green-200` | `text-green-700` |

**展示内容**：
- 三个指标卡片：疏散半径(m)、影响面积(m²)、风险等级
- 标签：压力等级、泄漏类型
- 安全措施有序列表

**数据字段映射**：
```typescript
data.radius_m        → 疏散半径
data.affected_area_m2 → 影响面积
data.risk_level      → 风险等级
data.pressure_class  → 压力等级
data.leak_type       → 泄漏类型
data.safety_instructions → 安全措施列表
```

### 2. InventoryPanel（物资库存）

**色彩**：蓝色主题（`bg-blue-50`）

**展示内容**：
- 标题 + 查询位置 + 匹配站点数
- 每个站点一张卡片：站点名 + 距离徽章
- 物资表格：名称、库存、状态（充足/偏低/紧张）

**状态徽章逻辑**：
| 库存量 | 显示 | 颜色 |
|--------|------|------|
| ≥ 10 | 充足 | 绿色 |
| 3-9 | 偏低 | 琥珀色 |
| < 3 | 紧张 | 红色 |

**数据字段映射**：
```typescript
data.stations[].station_name  → 站点名
data.stations[].distance_km   → 距离
data.stations[].materials[]   → 物资列表 {name, quantity, unit}
```

### 3. WeatherPanel（天气信息）

**色彩**：天蓝渐变（`from-sky-50 to-blue-50`）

**展示内容**：
- 4 个指标卡片：温度、湿度、风速(含风向)、能见度
- 天气状况文字
- 应急建议（琥珀色高亮）

**数据字段映射**：
```typescript
data.temperature / data.temp  → 温度
data.humidity                 → 湿度
data.wind_speed / data.windSpeed → 风速
data.wind_dir / data.windDir  → 风向
data.visibility               → 能见度
data.gas_emergency_advice     → 应急建议
```

### 4. ReportPanel（处置报告）

**色彩**：翠绿主题（`bg-emerald-50`）

**展示内容**：
- 标题 + 下载按钮（生成 .md 文件下载）
- 报告内容以 Markdown 渲染

**数据字段映射**：
```typescript
data.content / data.report / (string) → 报告 Markdown 文本
```

---

## 四、Mock 数据说明

chatStore 中的预置 mock 数据已包含 `toolCalls` 和 `panelData`，加载即可查看所有面板效果：

- **mock-1**（武侯区燃气泄漏）：包含 EvacuationPanel 疏散面板
- **mock-2**（高新区物资查询）：包含 InventoryPanel 库存面板

**如何替换真实数据：**

面板数据来自后端 SSE 的 `panel_data` 事件，格式为 `{type, data}`。后端 `chat.py` 中的 `_PANEL_MAP` 定义了哪些工具触发面板：

| 后端工具 | panel_data.type | 前端面板 |
|---------|----------------|---------|
| `calculate_evacuation_zone` | `evacuation` | EvacuationPanel |
| `query_material_inventory` | `inventory` | InventoryPanel |
| `get_weather_info` | `weather` | WeatherPanel |
| `generate_report` | `report` | ReportPanel |

当 SSE 推送 `panel_data` 事件时，前端 `sse.ts` 的 `onPanelData` 回调将数据存入当前助手消息的 `panelData` 数组，`PanelRenderer` 自动根据 `type` 渲染对应组件。**无需任何额外配置**。

---

## 五、验证

### 5.1 TypeScript 构建

```bash
cd gas-copilot/frontend
npm run build
# ✅ tsc 类型检查通过
# ✅ vite build 成功，产物 378 KB (gzipped 117 KB)
```

### 5.2 UI 验证（开发模式）

```bash
npm run dev
# 浏览器打开 http://localhost:5173
# 侧栏选择"武侯区燃气泄漏应急处置" → 可看到：
#   - CoT 时间线（折叠/展开，3 个步骤）
#   - EvacuationPanel 疏散面板（红色高危主题）
# 侧栏选择"高新区管道破裂疏散方案" → 可看到：
#   - InventoryPanel 库存面板（蓝色主题 + 物资表格）
```

### 5.3 与后端联调

启动后端发送真实请求，SSE 的 `tool_start`/`tool_end`/`panel_data` 事件将自动填充 CoT 步骤和面板数据。

---

## 六、组件架构

```
MessageItem
├── CoTSteps              ← 思维链时间线（toolCalls 数据）
│   └── StepItem × N      ← 每步：状态图标 + 标签 + 可展开详情
├── MarkdownContent       ← 助手回复 Markdown 渲染
│   or StreamingText      ← 流式时带光标
└── PanelRenderer         ← 业务面板路由（panelData 数据）
    ├── EvacuationPanel   ← 疏散范围（红/橙/绿）
    ├── InventoryPanel    ← 物资库存（蓝色 + 表格）
    ├── WeatherPanel      ← 天气信息（天蓝渐变）
    └── ReportPanel       ← 处置报告（翠绿 + 下载）
```
