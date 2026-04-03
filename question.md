# 模拟面试问题（由浅入深）

如果我是面试官，我会按以下顺序问你：

---

## 第一层：基础实现（验证代码是否真是你写的）

### Q1：SQLite Checkpointer 的持久化机制

> "你说用了 SQLite 做 Checkpointer。在 LangGraph 中，如果用户问了 10 轮，产生了 50 个 state 节点，SQLite 里存的是什么？你会定期清理旧的 thread 吗？如果不清理，数据库会膨胀到什么程度？"

**考察点：** 是否理解 LangGraph 的持久化机制（每个 step 存一份 state），是否有运维意识。

**我的回答：**

SQLite Checkpointer 存的是每一个 checkpoint，也就是每次 LangGraph 执行完一个节点后的完整 `AgentState` 快照。在我的项目里，`AgentState` 包含 `messages`、`tool_results`、`retrieved_docs`、`planner_output`、`iteration_count` 等字段。每走完一个节点（planner → tool_executor → reflector → responder），LangGraph 就向 SQLite 写入一条记录，key 是 `(thread_id, checkpoint_id)`。10 轮对话、每轮走 3-4 个节点，大概会产生 30-40 条 checkpoint 记录。

我目前的实现在 `checkpointer.py` 里用的是 `AsyncSqliteSaver.from_conn_string`，没有做定期清理。这确实是个运维隐患——如果系统长期运行，`messages` 字段会随对话轮次线性增长，`tool_results` 和 `retrieved_docs` 每轮也会追加数据，单个 thread 的 state 可能膨胀到几百 KB，乘以大量用户就会有问题。

改进方案我考虑过两个：一是定期清理超过 N 天未活跃的 thread（加一个后台定时任务按 `created_at` 删除）；二是在 state 设计上做限制，比如 `retrieved_docs` 只保留最近一轮的结果而不是无限追加，这样单个 checkpoint 的体积可控。

---

### Q2：检索链路的技术细节

> "在 混合检索 + RRF + BGE-Reranker 这条链路里，BM25 用的是 rank_bm25 还是 Elasticsearch 的 BM25？BGE-Reranker 你是跑在 CPU 还是 GPU 上？Token 长度超过 512 时你是怎么处理的？"

**考察点：** 细节落地，是否踩过坑（显存/速度/截断）。

**我的回答：**

BM25 用的是 `rank_bm25` 库的 `BM25Okapi`，中文分词用 `jieba`，在 `retriever.py` 的 `BM25Index` 类里实现。没有用 Elasticsearch，因为这是一个单机部署的场景，引入 ES 太重了。

BGE-Reranker 用的是 `sentence-transformers` 的 `CrossEncoder`，跑在 CPU 上。我在 `reranker.py` 里做了懒加载，首次调用时才 load 模型，避免启动时占用过多内存。CPU 推理延迟大概在 200-500ms 左右（取决于候选文档数量），对于抢险场景偶尔慢一点还可以接受，但如果有 GPU 当然优先用 GPU。

Token 截断的问题我确实遇到过。BGE-Reranker 的最大输入是 512 token，燃气规范的条款有时很长。处理方式是在 `ingest.py` 入库时按章节切片，单个 chunk 控制在 300 token 以内，这样 query + chunk 拼在一起基本不会超限。如果 chunk 本身超长，`CrossEncoder.predict` 会自动截断，不会报错，但召回质量会下降——这是一个已知的 tradeoff，目前用切片策略规避。

---

### Q3：SSE 流式协议设计

> "你前端实现了 panel_data 结构化事件。请描述一下后端如何通过 SSE 保证 token 和 panel_data 的顺序？如果工具调用返回的 JSON 很大（比如 200 个物资点），你是先完整缓存再发送，还是边生成边发送？"

**考察点：** 流式协议的设计，避免前端渲染错乱。

**我的回答：**

SSE 本身是有序的——HTTP/1.1 的 TCP 连接保证字节有序到达，同一个 SSE 连接里的事件按发送顺序到达客户端，不存在乱序问题。

在我的后端实现里（`chat.py`），事件的发送顺序是严格固定的：先发 `tool_start`（planner 决策），然后等工具执行完毕发 `tool_end`，紧接着发对应的 `panel_data`，最后才进入 responder 阶段发 `token` 流。这个顺序由 LangGraph 的 `astream_events` 保证——节点串行执行，事件在节点完成时才 yield，天然有序。

关于大 JSON（比如 200 个物资点的 inventory 结果），我的做法是先完整缓存再发送。工具函数 `query_material_inventory` 是同步执行完毕返回完整 dict 的，`tool_executor_node` 拿到完整 result 后，`chat.py` 里才 yield `tool_end` 和 `panel_data` 事件。这样前端拿到的 `panel_data` 永远是完整的 JSON，不会出现前端收到半个 JSON 导致解析失败的情况。代价是工具执行期间用户看不到进度，但对于这类计算型工具是合理的取舍。

---

## 第二层：业务深度（验证是否真懂燃气抢险）

### Q4：Agent 的并发控制与超时处理

> "燃气抢险有一个核心难点：时效性。你调用了天气 API（影响扩散）和疏散计算（耗时）。如果 Agent 在执行疏散计算 Tool 时卡住了 10 秒，用户在这期间问'现在风向是什么？'，你的 LangGraph 是如何处理的？是阻塞等待，还是支持并发 Tool 调用？"

**考察点：** Agent 的并发控制与超时处理。

**我的回答：**

这是我项目目前的一个真实局限。我的 LangGraph 图是线性的：planner → tool_executor → reflector → responder，同一个 thread（会话）在执行时是串行的。如果疏散计算工具卡住 10 秒，用户这期间再发“现在风向是什么”，这条新消息会等到当前 graph 执行完毕后才被处理，因为 SQLite checkpointer 不适合同一 thread 的并发写入。

不过有两点说明：一是工具内部我用了 `asyncio.gather` 并行跑向量检索和 BM25，以及在 `retriever.py` 里用 `run_in_executor` 把阻塞的 ChromaDB 和 BM25 搜索丢给线程池，所以单次请求内的 IO 是并发的；二是对于真正的并发用户，不同 `thread_id` 之间互不影响。

针对超时问题，`weather.py` 里设了 `httpx timeout=10s`，`gas_expert.py` 里用了 `settings.local_model_timeout`，工具层有超时保护。但 planner 和 reflector 调主 LLM 目前没有显式超时，这是一个可以继续改进的点——可以在工具执行层或 node 层统一加 `asyncio.wait_for`，超时就返回错误结果让 reflector 感知，而不是无限阻塞。

---

### Q5：微调模型的具体效果

> "你微调了大模型处理燃气方案。请举一个具体的例子：Base 模型（如 Qwen/Llama）输出错误的 A 答案，你微调后它输出了正确的 B 答案。这个错误是知识性的（不懂规范），还是推理性的（逻辑链条断裂）？微调数据你是怎么构造的？"

**考察点：** 是否真的做了微调，是否区分微调 vs RAG 的边界。

---

### Q6：多模态 RAG 的处理

> "假设用户问：'关掉阀门 A 和关掉阀门 B，哪种方案对下游居民影响更小？' 你的 Agent 需要从 RAG 里找到管网拓扑图（PDF 里的图片）。你是如何让 RAG 召回这张图的？如果你的 RAG 只存文本，这个问题就答不上来。"

**考察点：** 多模态 RAG 的思考，以及 Agent 对非文本数据的处理能力。

---

## 第三层：架构权衡与批判

### Q7：框架选择的反思

> "你选择了 LangGraph。如果让你现在用 LangChain 的 LCEL 或者 纯 Python + asyncio 重新实现这个 Agent，你会觉得哪个更简单？LangGraph 给你带来的最大好处是什么？有没有哪一部分你觉得 Graph 是多余的，用普通函数调用更好？"

**考察点：** 不盲从框架，有独立判断能力。

---

### Q8：知识冲突消解机制

> "你的项目里同时用到了：微调模型（处理燃气方案）、RAG（检索规范）、外部 Tool（天气/计算）。如果微调模型输出的结果与 RAG 检索到的规范条文冲突，你的 Agent 听谁的？你的 反思（Reflection） 节点能发现这种冲突吗？"

**考察点：** 知识冲突消解机制，这是 Agent 安全性的核心。

---

## 第四层：极限场景

### Q9：边缘计算与降级方案

> "抢险现场可能没有网络。你的架构假设了 LangSmith（云端）和外部 API（天气）。如果完全离线，你能让你的 Agent 运行在笔记本电脑甚至树莓派上吗？你会砍掉哪些组件，保留哪些？"

**考察点：** 边缘计算与降级方案。

---

### Q10：工程务实精神

> "最后一个问题：如果现在让你重构这个项目，只保留 20% 的代码解决 80% 的问题，你会删掉哪三个你认为'过度设计'的模块？"

**考察点：** 工程上的务实精神，拒绝炫技。
