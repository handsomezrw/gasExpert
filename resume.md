# 简历 · 项目经历

## 燃气抢险智能副驾（Gas Copilot）| 个人全栈 Demo

**项目简介**：面向燃气应急处置场景，将模糊的自然语言诉求转为可执行的检索、计算与报告生成流程，用 **Agent + RAG + 业务工具** 提升信息整合效率，验证「需求 → 架构 → 落地 → 可观测」的闭环。

**技术架构**

- **前端**：React + TypeScript + Vite，shadcn/ui；Zustand 管理多会话对话与业务面板状态；通过 **SSE（fetch ReadableStream）** 消费流式 token、工具事件与结构化 `panel_data`，驱动 **CoT 可折叠展示**与疏散/物资等 **动态业务面板**。
- **网关与 API**：FastAPI；对话走 **SSE 流式端点**，普通能力走 REST；HTTP 中间件记录延迟与路径，便于排障。
- **Agent 核心**：**LangGraph** `StateGraph`（Planner → 工具执行 / RAG 检索 → Reflector 反思 → Responder），用 **条件边** 替代单独意图分类服务；**SQLite + LangGraph checkpointer** 按 `thread_id` 持久化会话状态，支持多轮与断点延续。
- **工具与环境**：规范化 `@tool` 封装（天气、疏散范围计算、应急物资查询、抢险报告生成等）；预留 **微调/专家模型** 通过独立 Tool 接入（与通用模型编排解耦）。
- **知识层**：**混合检索**（ChromaDB 向量 + BM25/关键词）+ **RRF 融合 + BGE-Reranker** 重排序；文档按规范结构切片与入库，面向表格/条款类文档优化召回。
- **可观测与交付**：**LangSmith** 做 Agent 全链路追踪；**structlog** 结构化日志（开发控制台 / 生产 JSON Lines）；**Docker + docker-compose** 一键拉起前后端与数据卷，Nginx 反代并关闭缓冲以适配 SSE。

**个人职责与产出**

- 完成从 **业务场景抽象**（调度问询、规范检索、数值计算、报告）到 **AI 原生架构**（状态机、记忆、工具编排、RAG 管道）的设计与实现。
- 落地 **Context Engineering**：系统 Prompt、节点级 Prompt、结构化输出约束（Pydantic / 节点输出）与 RAG 上下文注入策略。
- 实现 **端到端工程闭环**：流式协议设计、前后端类型与事件契约、容器化与 README，保证可演示、可部署。

---

## 简历压缩版（4～6 条 bullet，可贴 PDF）

- 独立设计并实现燃气应急处置场景下的 **LangGraph Agent**（规划 / 工具 / RAG / 反思 / 回答），**SQLite checkpointer** 持久化多轮会话。
- 搭建 **混合检索 + RRF 融合 + BGE-Reranker** 的 RAG 管道（ChromaDB + BM25），优化规范类文档召回。
- **FastAPI SSE** 流式对话 + 结构化事件（token / 工具 / `panel_data`）；**React + TS + Zustand** 实现 CoT 与业务动态面板。
- 工具层封装天气、疏散计算、物资查询、报告生成等；专家能力以 **Tool** 形式对接微调/本地推理，与编排层解耦。
- 接入 **LangSmith** 与 **structlog**；**Docker Compose** 一键部署，Nginx 适配 SSE 代理。

---

## 与目标岗位（job.md）的对应关系

| JD 方向           | 项目中对应点                                       |
|-------------------|----------------------------------------------------|
| 需求理解与归因    | 抢险场景问答类型 → 规划 / 工具 / RAG 分支          |
| Agent 架构与记忆  | LangGraph + checkpointer；反思节点闭环             |
| 知识与环境        | RAG 混合检索 + Rerank；工具对接业务逻辑与 API      |
| 核心能力与 API    | SSE 服务、工具封装、LangSmith 追踪                 |
| 系统迭代          | 分阶段实施（见 PLAN.md）、文档与 compose 沉淀      |
| 性能与稳定        | 异步流式、错误事件、日志与健康探针                 |

---

## 模拟面试题与参考答法

**1. 为什么用 LangGraph 而不是「先 Router 再链式调用」？**  
规划与执行是有状态、可循环的（工具失败或信息不足要再规划）。`StateGraph` + 条件边让下一步走工具 / RAG / 直接回答由当前状态与模型输出决定，避免维护独立意图分类服务，且与检查点、多轮消息累积一致。

**2. RAG 为什么做向量 + BM25 再加 Reranker？**  
纯向量对专有名词、条款编号、表格容易漏召或序不对；BM25 补关键词匹配。两路用 RRF 合并后再用 Cross-Encoder 精排，提升 Top-K 质量并控制进模型的 token。

**3. SSE 相对 WebSocket 你怎么选？**  
对话主要是服务端单向推流，HTTP/2 下 SSE 足够；实现与运维简单，与 FastAPI 流式 Response 契合。双向实时协作才优先考虑 WebSocket。

**4. LangGraph checkpointer 和前端聊天记录有什么区别？**  
Checkpointer 存 Agent 图状态与消息序列，服务多轮推理与同 `thread_id` 延续；前端还要展示工具时间线、panel 数据等，可本地持久化或将来用服务端会话表；职责不同。

**5. 如何缓解幻觉与 Prompt 注入？**  
RAG 答案锚定检索片段；工具参数 Pydantic 校验；系统提示约束不可执行用户越权指令；敏感操作走工具；用日志与 LangSmith 做 bad case 复盘。

**6. 微调模型在系统里放哪一层？**  
作为 Tool（如 `consult_gas_expert`）由 Planner 调度，通用模型负责编排与对用户解释；可独立替换为 vLLM/Ollama，不影响主图结构。

**7. QPS 变高时先优化哪里？**  
区分瓶颈：LLM 延迟、Embedding/Rerank、向量库与 SQLite；可批处理、缓存、换托管向量库等；保留降级（缩短上下文、跳过 Rerank）。

**8. 如何用 AI 编程工具提效？**  
用 Cursor 等做脚手架与重复代码生成，但架构边界、事件协议、安全与评测由自己把控；Prompt 与 LangSmith trace 结合做迭代闭环。（按个人实际用法调整表述。）

---

## 面试准备提示

- 准备 **1 张架构图**（见 `PLAN.md` 中 mermaid）和 **1 条完整用户路径**（例如：问疏散 → 调计算工具 → `panel_data` 出面板）。
- 专家/微调接口若仍为占位，如实说明「接口已预留、当前接通用 API」，诚信优于夸大。
