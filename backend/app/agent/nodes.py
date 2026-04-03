"""LangGraph node implementations with real LLM calls."""

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
from app.tools import TOOL_MAP, get_tool_descriptions

logger = structlog.get_logger()

MAX_ITERATIONS = 3


# ── Planner ──────────────────────────────────────────────────────────

async def planner_node(state: AgentState) -> dict:
    """Analyze user intent and decide next action via LLM."""
    llm = get_llm()

    system_prompt = PLANNER_SYSTEM_TEMPLATE.format(
        tool_descriptions=get_tool_descriptions(),
    )

    # Append already-collected context so the planner doesn't repeat work
    context_parts: list[str] = []
    if state.get("tool_results"):
        context_parts.append(
            "### 已有工具调用结果\n"
            + json.dumps(state["tool_results"], ensure_ascii=False, indent=2)
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
    if plan == "need_rag":
        return "need_rag"
    return "direct_answer"


# ── Tool Executor ────────────────────────────────────────────────────

async def tool_executor_node(state: AgentState) -> dict:
    """Execute the tools specified by the planner."""
    planner_output = state.get("planner_output") or {}
    tool_calls = planner_output.get("tool_calls") or []

    results: list[dict] = list(state.get("tool_results") or [])

    for tc in tool_calls:
        name = tc.get("name", "")
        args = tc.get("args", {})
        tool_fn = TOOL_MAP.get(name)

        if tool_fn is None:
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

    return {"tool_results": results}


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
