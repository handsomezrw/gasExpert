"""LangGraph node implementations with real LLM calls."""
from __future__ import annotations

import json

import structlog
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.agent.llm import extract_json, get_llm
from app.agent.prompts import (
    PLANNER_SYSTEM_TEMPLATE,
    REFLECTOR_SYSTEM,
    RESPONDER_SYSTEM,
)
from app.agent.state import AgentState
from app.skills import SkillRegistry
from app.tools import TOOL_MAP, get_tool_descriptions

logger = structlog.get_logger()

MAX_ITERATIONS = 5


# ── Case Recall (Phase 6.4 L2 案例记忆) ─────────────────────────────

async def case_recall_node(state: AgentState) -> dict:
    """Recall top-3 similar historical cases and inject into planner context.

    Only runs on the first iteration (iteration_count == 0) and when the
    user message appears to describe an incident (contains leak keywords).
    """
    iteration = state.get("iteration_count", 0)
    if iteration > 0:
        return {}

    user_msgs = [m for m in state["messages"] if isinstance(m, HumanMessage)]
    if not user_msgs:
        return {}
    query_text = user_msgs[-1].content or ""

    # Quick heuristic: only run case recall for incident-like messages
    leak_keywords = ["泄漏", "漏气", "破裂", "锈蚀", "第三方破坏", "开挖", "爆管",
                     "扩散", "疏散", "关阀", "抢修"]
    if not any(kw in query_text for kw in leak_keywords):
        return {}

    from app.memory.case_store import get_case_store

    store = get_case_store()
    if not store.ready:
        return {}

    # Build context from message text (simple keyword extraction)
    context: dict[str, str] = {}
    for kw_map, field in [
        (["锈蚀", "腐蚀"], "failure_mode"),
        (["第三方破坏", "开挖"], "failure_mode"),
        (["接口漏气", "三通"], "failure_mode"),
        (["钢管"], "material"),
        (["PE管", "PE"], "material"),
        (["中压"], "pressure_class"),
        (["低压"], "pressure_class"),
        (["管道外腐蚀", "外腐蚀"], "direct_cause"),
        (["焊口开裂", "焊接"], "direct_cause"),
        (["机械施工", "第三方施工"], "direct_cause"),
        (["管道老旧"], "indirect_cause"),
        (["重车碾压"], "indirect_cause"),
        (["地面沉降", "地质沉降"], "indirect_cause"),
    ]:
        for kw in kw_map:
            if kw in query_text:
                context[field] = kw
                break

    try:
        # Pass raw query_text for semantic search + context for structured match
        similar = store.query(context, query_text=query_text, top_k=3)
    except Exception as exc:
        logger.warning("case_recall_failed", error=str(exc))
        return {}

    # Filter out low-relevance matches (noise reduction)
    MIN_SCORE = 3.0  # at least 2 meaningful fields matched
    similar = [c for c in similar if c["score"] >= MIN_SCORE]

    if not similar:
        logger.info("case_recall_no_quality_hits", min_score=MIN_SCORE)
        return {}

    logger.info(
        "case_recall_hits n=%d ids=%s",
        len(similar),
        [c["incident_id"] for c in similar],
    )

    # Format as a system-level message injected into the state
    lines = [
        "## 相似历史事故（案例库召回 top-3）",
        "以下是与当前事故相似的历史处置案例，请参考其处置方式和经验：",
        "",
    ]
    for i, c in enumerate(similar, 1):
        lines.append(
            f"### 案例 {i}：{c['incident_id']}（相似度 {c['score']}）\n"
            f"- 事件类型：{c['event_type']}\n"
            f"- 位置：{c['location']}\n"
            f"- 管材/压力：{c['pipeline_material'] or '?'} / {c['pressure_class'] or '?'}\n"
            f"- 失效模式：{c['failure_mode'] or '?'}\n"
            f"- 维修方式：{c['repair_method'] or '?'}\n"
            f"- 恢复时间：{c['recovery_time'] or '?'}\n"
            + (f"- 处置方案：{c['answer'][:400]}...\n" if c.get('answer') else "")
            + (f"- 推理过程：{c['think_trace'][:200]}...\n" if c.get('think_trace') else "")
        )

    case_context = "\n".join(lines)
    # Store in state for planner to use
    return {
        "retrieved_docs": list(state.get("retrieved_docs") or []) + [case_context],
    }


# ── Planner ──────────────────────────────────────────────────────────


# ── Planner ──────────────────────────────────────────────────────────

async def planner_node(state: AgentState) -> dict:
    """Analyze user intent and decide next action via LLM."""
    llm = get_llm()

    system_prompt = PLANNER_SYSTEM_TEMPLATE.format(
        tool_descriptions=get_tool_descriptions(),
        skill_descriptions=SkillRegistry.describe_for_planner(),
    )

    # Append already-collected context so the planner doesn't repeat work
    context_parts: list[str] = []
    if state.get("tool_results"):
        context_parts.append(
            "### 已有工具调用结果\n"
            + json.dumps(state["tool_results"], ensure_ascii=False, indent=2)
        )
    if state.get("skill_results"):
        context_parts.append(
            "### 已有技能执行结果\n"
            + json.dumps(state["skill_results"], ensure_ascii=False, indent=2)
        )
    if state.get("retrieved_docs"):
        context_parts.append(
            "### 已检索文档\n" + "\n---\n".join(state["retrieved_docs"])
        )
    if context_parts:
        system_prompt += "\n\n## 已收集的信息\n" + "\n\n".join(context_parts)

    messages = [SystemMessage(content=system_prompt), *list(state["messages"])]

    try:
        response = await llm.ainvoke(messages)
        raw = extract_json(response.content)
        planner_output = json.loads(raw)
        decision = planner_output.get("decision", "direct_answer")
        logger.info(
            "planner_decision",
            decision=decision,
            reasoning=planner_output.get("reasoning", "")[:120],
        )
    except Exception as exc:
        logger.warning("planner_parse_error", error=str(exc))
        planner_output = {
            "decision": "direct_answer",
            "reasoning": "规划解析失败，直接回答",
            "tool_calls": [],
        }
        decision = "direct_answer"

    return {
        "current_plan": decision,
        "planner_output": planner_output,
        "iteration_count": state.get("iteration_count", 0) + 1,
    }


def route_decision(state: AgentState) -> str:
    """Conditional edge: route based on planner decision."""
    plan = state.get("current_plan", "direct_answer")
    if plan == "use_tools":
        return "use_tools"
    if plan == "use_skills":
        return "use_skills"
    if plan == "need_rag":
        return "need_rag"
    return "direct_answer"


# ── Tool Executor ────────────────────────────────────────────────────

async def tool_executor_node(state: AgentState) -> dict:
    """Execute the tools specified by the planner."""
    planner_output = state.get("planner_output") or {}
    tool_calls = planner_output.get("tool_calls") or []

    results: list[dict] = list(state.get("tool_results") or [])
    skill_results: list[dict] = list(state.get("skill_results") or [])

    for tc in tool_calls:
        name = tc.get("name", "")
        args = tc.get("args", {})
        tool_fn = TOOL_MAP.get(name)

        if tool_fn is None:
            # Fallback: check if it's actually a skill (LLM mis-routed)
            skill_cls = SkillRegistry.get(name)
            if skill_cls is not None:
                logger.info("tool_rerouted_to_skill", name=name)
                try:
                    skill = skill_cls()
                    args = _inject_coords(args, state)
                    result = await skill.ainvoke(args)
                    result_dict = result.model_dump()
                    if result.pending and hasattr(result, "_resume_state"):
                        result_dict["_resume_state"] = result._resume_state  # noqa: SLF001
                    skill_results.append({"skill": name, "args": args, "result": result_dict})
                    logger.info("skill_exec_done", name=name, pending=result.pending)
                except Exception as exc:
                    logger.error("skill_exec_fail", name=name, error=str(exc))
                    skill_results.append({"skill": name, "args": args, "error": str(exc)})
                continue
            logger.warning("unknown_tool", name=name)
            results.append({"tool": name, "error": f"未知工具: {name}"})
            continue

        try:
            logger.info("tool_exec_start", name=name, args=args)
            result = await tool_fn.ainvoke(args)
            results.append({"tool": name, "args": args, "result": result})
            logger.info("tool_exec_done", name=name)
        except Exception as exc:
            logger.error("tool_exec_fail", name=name, error=str(exc))
            results.append({"tool": name, "args": args, "error": str(exc)})

    return {"tool_results": results, "skill_results": skill_results}


# ── Skill Executor (Phase 6.1) ───────────────────────────────────────

def _inject_coords(args: dict, state: AgentState) -> dict:
    """If the LLM didn't extract coordinates, parse them from the raw message text.

    ReportForm embeds coordinates as "纬度X, 经度Y" which the LLM may skip.
    This ensures the diffusion/valve skills always get the click coordinates.
    """
    import re

    # Already has coords — skip
    if args.get("leak_point_lat") and args.get("leak_point_lng"):
        return args

    # Gather text from user messages
    from langchain_core.messages import HumanMessage
    user_msgs = [m for m in state.get("messages", []) if isinstance(m, HumanMessage)]
    text = " ".join(m.content for m in user_msgs if hasattr(m, "content"))

    lat_m = re.search(r"纬度[=:：]?\s*([\d.]+)", text)
    lng_m = re.search(r"经度[=:：]?\s*([\d.]+)", text)
    if lat_m and lng_m:
        try:
            args = dict(args)  # don't mutate original
            args["leak_point_lat"] = float(lat_m.group(1))
            args["leak_point_lng"] = float(lng_m.group(1))
            logger.info("coords_injected", lat=args["leak_point_lat"], lng=args["leak_point_lng"])
        except ValueError:
            pass
    return args


async def skill_executor_node(state: AgentState) -> dict:
    """Execute skills specified by the planner (virtual tools routed to subgraphs)."""
    planner_output = state.get("planner_output") or {}
    tool_calls = planner_output.get("tool_calls") or []

    skill_results: list[dict] = list(state.get("skill_results") or [])

    for tc in tool_calls:
        name = tc.get("name", "")
        args = tc.get("args", {})
        skill_cls = SkillRegistry.get(name)

        if skill_cls is None:
            logger.warning("unknown_skill", name=name)
            skill_results.append({"skill": name, "error": f"未知技能: {name}"})
            continue

        # Phase 6.5: inject coordinates from raw message if LLM missed them
        if name in ("diffusion_zone", "valve_isolation"):
            args = _inject_coords(args, state)

        try:
            logger.info("skill_exec_start", name=name, args=args)
            skill = skill_cls()
            result = await skill.ainvoke(args)
            result_dict = result.model_dump()
            # Phase 6.5: preserve resume state for HITL recovery
            if result.pending and hasattr(result, "_resume_state"):
                result_dict["_resume_state"] = result._resume_state  # noqa: SLF001
            skill_results.append({
                "skill": name,
                "args": args,
                "result": result_dict,
            })
            logger.info("skill_exec_done", name=name, pending=result.pending)
        except Exception as exc:
            logger.error("skill_exec_fail", name=name, error=str(exc))
            skill_results.append({"skill": name, "args": args, "error": str(exc)})

    return {"skill_results": skill_results}


# ── RAG Retriever ─────────────────────────────────────────────────────

async def rag_retriever_node(state: AgentState) -> dict:
    """Retrieve relevant documents via hybrid search (vector + BM25 + reranker)."""
    from app.rag.retriever import get_retriever

    user_msgs = [m for m in state["messages"] if isinstance(m, HumanMessage)]
    query = user_msgs[-1].content if user_msgs else ""
    logger.info("rag_retrieval", query=query[:100])

    docs: list[str] = list(state.get("retrieved_docs") or [])

    retriever = get_retriever()
    if retriever is None:
        logger.info("rag_not_initialised")
        docs.append(
            f"[知识库未就绪] 针对「{query[:50]}」的检索无法执行，"
            "请先运行 'python -m app.rag.ingest' 入库文档。"
        )
        return {"retrieved_docs": docs}

    try:
        results = await retriever.retrieve(query)
        formatted = retriever.format_docs_for_state(results)
        docs.extend(formatted)
        logger.info("rag_retrieval_done", hits=len(results))
    except Exception as exc:
        logger.error("rag_retrieval_error", error=str(exc))
        docs.append(f"[检索异常] {exc}")

    return {"retrieved_docs": docs}


# ── Reflector ────────────────────────────────────────────────────────

async def reflector_node(state: AgentState) -> dict:
    """Check whether collected info is sufficient to answer the user."""
    iteration = state.get("iteration_count", 1)

    if iteration >= MAX_ITERATIONS:
        logger.info("max_iterations_reached", iteration=iteration)
        return {"current_plan": "sufficient"}

    llm = get_llm()

    user_msgs = [m for m in state["messages"] if isinstance(m, HumanMessage)]
    question = user_msgs[-1].content if user_msgs else ""

    system_prompt = REFLECTOR_SYSTEM.format(
        question=question,
        tool_results=json.dumps(
            state.get("tool_results") or [], ensure_ascii=False, indent=2
        ),
        retrieved_docs="\n---\n".join(state.get("retrieved_docs") or []) or "无",
        max_iterations=MAX_ITERATIONS,
        current_iteration=iteration,
    )

    try:
        response = await llm.ainvoke([SystemMessage(content=system_prompt)])
        raw = extract_json(response.content)
        verdict_data = json.loads(raw)
        verdict = verdict_data.get("verdict", "sufficient")
        logger.info(
            "reflector_verdict",
            verdict=verdict,
            reason=verdict_data.get("reason", "")[:120],
        )
        return {"current_plan": verdict}
    except Exception as exc:
        logger.warning("reflector_parse_error", error=str(exc))
        return {"current_plan": "sufficient"}


def check_completeness(state: AgentState) -> str:
    """Conditional edge: decide if more info is needed."""
    if state.get("current_plan") == "need_more":
        return "need_more"
    return "sufficient"


# ── Post-Mortem (Phase 6.4 L2 案例入库) ────────────────────────────

async def post_mortem_node(state: AgentState) -> dict:
    """Generate lessons_learned draft when an incident is closed.

    Called externally (not part of the main graph) when incident status
    changes to 'resolved'. Collects all agent outputs and asks LLM to
    produce a concise lessons-learned summary for case library storage.
    """
    from app.agent.llm import get_llm, extract_json
    from langchain_core.messages import SystemMessage

    llm = get_llm()

    # Gather everything the agent produced
    parts: list[str] = []
    if state.get("tool_results"):
        parts.append("工具结果: " + json.dumps(state["tool_results"], ensure_ascii=False, indent=2))
    if state.get("skill_results"):
        parts.append("技能结果: " + json.dumps(state["skill_results"], ensure_ascii=False, indent=2))
    if state.get("retrieved_docs"):
        parts.append("参考文档: " + "\n---\n".join(state["retrieved_docs"]))
    if state.get("planner_output"):
        parts.append("规划决策: " + json.dumps(state.get("planner_output"), ensure_ascii=False, indent=2))
    # Include last assistant message
    msgs = state.get("messages", [])
    for m in reversed(msgs):
        if hasattr(m, "content") and getattr(m, "type", "") == "ai":
            parts.append(f"最终回复摘要: {m.content[:2000]}")
            break

    if not parts:
        return {"final_report": None}

    prompt = (
        "你是燃气抢险复盘专家。根据以下事故处置过程，生成一段 200-400 字的事故复盘总结（lessons_learned），"
        "包含：事故概况、关键处置动作、成功经验、可改进之处。\n\n"
        + "\n\n".join(parts)
        + "\n\n输出格式（严格 JSON）：\n{\"lessons_learned\": \"复盘总结文本\"}"
    )

    try:
        response = await llm.ainvoke([SystemMessage(content=prompt)])
        raw = extract_json(response.content)
        data = json.loads(raw)
        lessons = data.get("lessons_learned", "")
        logger.info("post_mortem_generated", length=len(lessons))
        return {"final_report": lessons}
    except Exception as exc:
        logger.warning("post_mortem_failed", error=str(exc))
        return {"final_report": None}


# ── Responder ────────────────────────────────────────────────────────

async def responder_node(state: AgentState) -> dict:
    """Generate the final response for the user."""
    llm = get_llm()

    context_parts: list[str] = []
    if state.get("tool_results"):
        context_parts.append(
            "### 工具调用结果\n"
            + json.dumps(state["tool_results"], ensure_ascii=False, indent=2)
        )
    if state.get("skill_results"):
        context_parts.append(
            "### 技能执行结果\n"
            + json.dumps(state["skill_results"], ensure_ascii=False, indent=2)
        )
    if state.get("retrieved_docs"):
        context_parts.append(
            "### 检索到的知识文档\n" + "\n---\n".join(state["retrieved_docs"])
        )

    context = (
        "\n\n".join(context_parts)
        if context_parts
        else "无额外上下文，请根据你的知识直接回答。"
    )
    system_prompt = RESPONDER_SYSTEM.format(context=context)

    messages = [SystemMessage(content=system_prompt), *list(state["messages"])]

    try:
        response = await llm.ainvoke(messages)
        logger.info("responder_done", length=len(response.content))
        return {"messages": [response]}
    except Exception as exc:
        logger.error("responder_fail", error=str(exc))
        return {
            "messages": [
                AIMessage(content=f"抱歉，生成回答时发生错误：{exc}。请稍后重试。")
            ]
        }
