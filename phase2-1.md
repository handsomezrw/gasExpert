# 阶段 2-1 实施总结：工具箱实现

> 对应 PLAN.md 阶段 2 第一项任务（已完成 [x]）

---

## 一、完成的工作

### 任务目标

将阶段 1 中 5 个占位/TODO 状态的工具全部升级为生产级实现，使 Agent 的工具调用链路具备真实业务能力。

### 各工具实现详情

#### 1. get_weather_info（天气查询）

| 项目 | 内容 |
|------|------|
| 文件 | `backend/app/tools/weather.py` |
| API 集成 | 和风天气 (QWeather) — GeoAPI 地名解析 + 实时天气查询，异步 httpx 调用 |
| 降级策略 | 未配置 `WEATHER_API_KEY` 时自动回退到随机模拟数据，并在 `source` 字段标注"模拟数据" |
| 新增能力 | **燃气抢险气象建议**：根据风速（≥6级扩大疏散范围）、降雨（PE管熔接需遮雨）、低温（管材脆性）、高温（燃气挥发加速）等条件自动生成针对性建议 |
| 返回字段 | location, weather, temperature, feels_like, humidity, wind_direction, wind_speed, wind_scale, pressure_hpa, visibility_km, source, gas_emergency_advice |

#### 2. calculate_evacuation_zone（疏散范围计算）

| 项目 | 内容 |
|------|------|
| 文件 | `backend/app/tools/evacuation.py` |
| 计算模型 | 基础公式 `√(pressure × diameter) × leak_multiplier`，在阶段 1 基础上新增风速修正因子（20-39km/h ×1.2, ≥39km/h ×1.5）和室内场景修正（×1.3） |
| 新增参数 | `wind_speed`（当前风速）、`is_indoor`（是否室内泄漏） |
| 新增输出 | pressure_class（压力等级分类，低压/中压B/中压A/次高压/高压）、risk_color（前端可用的颜色编码）、wind_correction/indoor_correction（修正系数说明）、safety_instructions（分级安全指令列表）、immediate_actions（即时行动清单） |
| 规范参考 | GB 50028《城镇燃气设计规范》、CJJ 51《城镇燃气设施运行、维护和抢修安全技术规程》 |

#### 3. query_material_inventory（抢险物资查询）

| 项目 | 内容 |
|------|------|
| 文件 | `backend/app/tools/inventory.py` + `backend/data/inventory.json` |
| 数据源 | 新建 JSON 数据文件，包含成都市 7 个燃气抢险站（武侯区、高新区、锦江区、金牛区、成华区、双流区、天府新区），每站 8-14 种物资明细 |
| 距离计算 | haversine 公式计算球面距离，通过区级坐标映射表（12 个区）将地名字符串解析为经纬度 |
| 查询逻辑 | 解析位置 → 坐标匹配 → 计算各站距离 → 按半径过滤 → 按距离排序 → 返回结果 |
| 返回字段 | query_location, search_radius_km, matched_stations, coordinate_resolved, stations[]{station_name, district, address, contact, available_24h, distance_km, items[]} |

#### 4. consult_gas_expert（燃气专家咨询）

| 项目 | 内容 |
|------|------|
| 文件 | `backend/app/tools/gas_expert.py` |
| 主路径 | 通过 httpx 调用 vLLM OpenAI 兼容接口（`LOCAL_MODEL_URL/chat/completions`），支持可配置的超时时间 |
| 降级路径 | 本地模型不可用时（ConnectError 或其他异常），自动降级为主 LLM（当前为 DeepSeek）+ 燃气专家系统提示词 |
| 专家提示词 | 涵盖 GB 50028、CJJ 51、GB/T 13611、GB 50494、CJJ/T 153 五部核心规范，要求标注条款编号、区分强制性/推荐性条款 |
| 设计考量 | 用户后续在服务器部署 vLLM 后，只需配置 `LOCAL_MODEL_URL` 和 `LOCAL_MODEL_NAME` 即可无缝切换，无需改代码 |

#### 5. generate_report（抢险报告生成）

| 项目 | 内容 |
|------|------|
| 文件 | `backend/app/tools/report.py` |
| 实现方式 | 调用主 LLM 根据结构化提示词模板生成 Markdown 格式报告 |
| 报告结构 | 六个章节：事故概况 → 现场环境评估 → 疏散方案 → 抢修资源调配 → 处置步骤 → 安全注意事项 |
| 输入参数 | `incident_type`（事故类型）、`location`（地点）、`situation_summary`（综合摘要） |
| 错误兜底 | LLM 调用失败时生成简要版报告框架（含已知信息），标注需人工补充 |
| 时间戳 | 报告自动写入生成时间 |

### 基础设施变更

| 文件 | 变更内容 |
|------|---------|
| `backend/app/config.py` | 新增 `weather_api_key`、`weather_api_base`、`local_model_timeout` 三个配置项 |
| `backend/app/agent/nodes.py` | `tool_executor_node` 中 `tool_fn.invoke(args)` → `await tool_fn.ainvoke(args)`，统一支持同步和异步工具 |
| `backend/.env.example` | 同步新增 `WEATHER_API_KEY`、`WEATHER_API_BASE`、`LOCAL_MODEL_TIMEOUT` |
| `PLAN.md` | 阶段 2 工具箱实现标记为 `[x]` |

---

## 二、遇到的问题与解决方案

本次实施过程较为顺畅，未遇到阻断性问题。以下记录两个需要注意的点：

### 问题 1：异步工具与同步 tool_executor 的兼容

**现象**：`weather.py`、`gas_expert.py`、`report.py` 三个工具因需要 HTTP/LLM 调用而改为 `async def`，但阶段 1 的 `tool_executor_node` 使用的是同步的 `tool_fn.invoke(args)`。

**解决方案**：将 `tool_fn.invoke(args)` 改为 `await tool_fn.ainvoke(args)`。LangChain 的 `ainvoke` 对同步工具会在线程池中运行，对异步工具直接 await，因此一行改动即可兼容两类工具。

### 问题 2：Windows PowerShell 终端中文乱码

**现象**：测试脚本输出的中文在 PowerShell 终端中显示为乱码（GBK 编码问题），且 Unicode emoji 字符（✅）导致 `UnicodeEncodeError`。

**影响**：仅影响终端显示，不影响实际功能。

**解决方案**：移除了测试脚本中的 emoji 字符。中文乱码为 Windows 终端固有的编码问题，在实际 Web 服务（UTF-8 环境）中不存在此问题。

---

## 三、验证方法与结果

### 1. 语法检查

```bash
cd gas-copilot/backend
.venv\Scripts\python -c "
import ast, pathlib
for f in pathlib.Path('app').rglob('*.py'):
    ast.parse(f.read_text(encoding='utf-8'))
print('All files parse OK')
"
```

**结果**：`All files parse OK` ✓

### 2. 模块导入与工具注册验证

```bash
.venv\Scripts\python -c "
from app.tools import ALL_TOOLS
for t in ALL_TOOLS:
    print(f'{t.name}: {type(t).__name__} (async={t.coroutine is not None})')
print(f'Total: {len(ALL_TOOLS)} tools')
"
```

**结果**：

```
get_weather_info: StructuredTool (async=True)
calculate_evacuation_zone: StructuredTool (async=False)
query_material_inventory: StructuredTool (async=False)
consult_gas_expert: StructuredTool (async=True)
generate_report: StructuredTool (async=True)
Total: 5 tools
```

5 个工具全部注册成功，3 个异步 + 2 个同步 ✓

### 3. 各工具独立调用测试

通过临时测试脚本逐一验证：

| 工具 | 测试方式 | 结果 |
|------|---------|------|
| calculate_evacuation_zone | 直接调用，参数 pressure=0.4, diameter=200, leak_type=crack, wind_speed=25 | 返回 radius=21.5m, risk_level=低危, wind_correction=×1.2, 4 条安全指令 ✓ |
| query_material_inventory | 直接调用，参数 location=成都市武侯区, radius_km=8 | 匹配 4 个站点，坐标解析成功，按距离排序（3.0km, 5.3km, 6.2km...）✓ |
| get_weather_info | ainvoke 异步调用（mock 模式，无 API Key） | 返回模拟气象数据 + 气象建议 ✓ |
| consult_gas_expert | ainvoke 异步调用，mock 本地模型不可用 → 降级 | 成功走降级路径，返回专家回答 ✓ |
| generate_report | ainvoke 异步调用，mock LLM 返回报告 | 生成结构化报告（31 chars mock），包含标题和章节 ✓ |

### 4. Agent 端到端流程验证（Mock LLM）

```bash
.venv\Scripts\python -c "
import asyncio, json, os
os.environ['OPENAI_API_KEY'] = 'sk-test'
# ... (Mock LLM 模拟 Planner→use_tools→Reflector→sufficient 路径)
"
```

**结果**：

```
Executed nodes: ['planner', 'tool_executor', 'reflector', 'responder']
E2E flow verified!
```

确认升级后的异步工具在完整 Agent 执行链路中正常工作 ✓

---

## 四、当前工具箱架构

```
tools/
├── __init__.py              # 工具注册表（ALL_TOOLS / TOOL_MAP / get_tool_descriptions）
├── weather.py               # [async] 和风天气 API + mock 回退 + 燃气气象建议
├── evacuation.py            # [sync]  疏散范围计算（含风速/室内修正 + 安全指令）
├── inventory.py             # [sync]  JSON 数据 + haversine 距离 + 区级坐标解析
├── gas_expert.py            # [async] vLLM 本地模型 → 主 LLM 降级回退
└── report.py                # [async] LLM 驱动结构化报告生成（6 章节模板）

data/
└── inventory.json           # 成都市 7 站点 × 8-14 种物资 + 12 区坐标映射
```

### 工具调用流程

```
Planner (LLM 决策)
  └─ use_tools → Tool Executor
                    ├─ get_weather_info        ──→ QWeather API / mock
                    ├─ calculate_evacuation_zone ──→ 本地计算
                    ├─ query_material_inventory  ──→ JSON 数据查询
                    ├─ consult_gas_expert        ──→ vLLM / 主 LLM 降级
                    └─ generate_report           ──→ 主 LLM 结构化生成
                 → Reflector (判断信息充分性)
                    ├─ sufficient → Responder → 最终回答
                    └─ need_more → Planner (重新规划)
```

---

## 五、后续待办

- **vLLM 部署后**：配置 `LOCAL_MODEL_URL` 和 `LOCAL_MODEL_NAME`，gas_expert 工具将自动切换到本地微调模型
- **和风天气 API Key**：注册 QWeather 开发者账号（免费额度 1000次/天），配置 `WEATHER_API_KEY` 启用真实气象数据
- **物资数据**：当前为 JSON 静态数据，阶段 4 联调时可对接真实库存数据库
- **阶段 2 剩余任务**：RAG 混合检索管道（文档切片入库 + ChromaDB + BM25 + Reranker）
