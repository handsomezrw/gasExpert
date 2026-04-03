"""SSE streaming chat endpoint — wires the LangGraph agent to HTTP.

Outputs five SSE event types:
  token      — incremental LLM content from the Responder (real-time)
  tool_start — a node / tool begins execution or has produced a decision
  tool_end   — a tool / retrieval has finished with results
  panel_data — structured data for front-end business panels
  done       — stream complete
"""

import json
import time
import uuid
from typing import AsyncGenerator

import structlog
from fastapi import APIRouter, Depends, Request
from langchain_core.messages import HumanMessage
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app.api.deps import get_app_settings
from app.config import Settings

router = APIRouter()
logger = structlog.get_logger()


# ── Request / Response models ────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


# ── Helpers ──────────────────────────────────────────────────────────

def _uid() -> str:
    return str(uuid.uuid4())


def _ts() -> int:
    """Epoch milliseconds — ready for ``new Date()`` on the front-end."""
    return int(time.time() * 1000)


def _sse(event: str, payload: dict) -> dict:
    return {"event": event, "data": json.dumps(payload, ensure_ascii=False)}


def _build_input(message: str) -> dict:
    return {
        "messages": [HumanMessage(content=message)],
        "current_plan": "",
        "planner_output": {},
        "tool_results": [],
        "retrieved_docs": [],
        "final_report": None,
        "iteration_count": 0,
    }


# ── Panel data mapping ──────────────────────────────────────────────

_PANEL_MAP = {
    "calculate_evacuation_zone": "evacuation",
    "query_material_inventory": "inventory",
    "get_weather_info": "weather",
    "generate_report": "report",
}


def _maybe_panel(tool_result: dict) -> dict | None:
    """If the tool result maps to a front-end panel, build a panel_data SSE event."""
    name = tool_result.get("tool", "")
    result = tool_result.get("result")
    if result is None:
        return None
    panel_type = _PANEL_MAP.get(name)
    if panel_type is None:
        return None
    return _sse("panel_data", {"type": panel_type, "data": result})


# ── Primary strategy: astream_events (token-level streaming) ────────

async def _stream_events(
    message: str,
    session_id: str,
    graph,
) -> AsyncGenerator[dict, None]:
    """Use ``graph.astream_events(version='v2')`` for real-time token streaming.

    LangGraph emits fine-grained events including ``on_chat_model_stream``
    which lets us push individual tokens to the client as they arrive.
    """
    config = {"configurable": {"thread_id": session_id}}
    input_state = _build_input(message)

    emitted_tool_count = 0

    try:
        async for ev in graph.astream_events(
            input_state, config=config, version="v2"
        ):
            kind = ev["event"]
            node = ev.get("metadata", {}).get("langgraph_node", "")

            # ── Planner completed ─────────────────────────────────
            if kind == "on_chain_end" and node == "planner":
                out = ev["data"].get("output")
                if not isinstance(out, dict) or "planner_output" not in out:
                    continue
                po = out["planner_output"]
                yield _sse("tool_start", {
                    "id": _uid(),
                    "name": "planner",
                    "args": {},
                    "status": "done",
                    "result": {
                        "decision": po.get("decision"),
                        "reasoning": po.get("reasoning"),
                    },
                    "timestamp": _ts(),
                })
                decision = po.get("decision")
                if decision == "use_tools":
                    for tc in po.get("tool_calls", []):
                        yield _sse("tool_start", {
                            "id": _uid(),
                            "name": tc.get("name", "unknown"),
                            "args": tc.get("args", {}),
                            "status": "running",
                            "timestamp": _ts(),
                        })
                elif decision == "need_rag":
                    yield _sse("tool_start", {
                        "id": _uid(),
                        "name": "knowledge_search",
                        "args": {},
                        "status": "running",
                        "timestamp": _ts(),
                    })

            # ── Tool executor completed ───────────────────────────
            elif kind == "on_chain_end" and node == "tool_executor":
                out = ev["data"].get("output")
                if not isinstance(out, dict) or "tool_results" not in out:
                    continue
                results = out["tool_results"]
                new_results = results[emitted_tool_count:]
                emitted_tool_count = len(results)
                for tr in new_results:
                    has_err = "error" in tr
                    yield _sse("tool_end", {
                        "id": _uid(),
                        "name": tr.get("tool", "unknown"),
                        "args": tr.get("args", {}),
                        "status": "error" if has_err else "done",
                        "result": tr.get("result") or tr.get("error"),
                        "timestamp": _ts(),
                    })
                    panel = _maybe_panel(tr)
                    if panel:
                        yield panel

            # ── RAG retriever completed ───────────────────────────
            elif kind == "on_chain_end" and node == "rag_retriever":
                out = ev["data"].get("output")
                if not isinstance(out, dict) or "retrieved_docs" not in out:
                    continue
                docs = out["retrieved_docs"]
                yield _sse("tool_end", {
                    "id": _uid(),
                    "name": "knowledge_search",
                    "args": {},
                    "status": "done",
                    "result": f"检索到 {len(docs)} 条相关文档",
                    "timestamp": _ts(),
                })

            # ── Reflector verdict ─────────────────────────────────
            elif kind == "on_chain_end" and node == "reflector":
                out = ev["data"].get("output")
                if not isinstance(out, dict) or "current_plan" not in out:
                    continue
                yield _sse("tool_start", {
                    "id": _uid(),
                    "name": "reflector",
                    "args": {},
                    "status": "done",
                    "result": {"verdict": out["current_plan"]},
                    "timestamp": _ts(),
                })

            # ── Responder token-by-token streaming ────────────────
            elif kind == "on_chat_model_stream" and node == "responder":
                chunk = ev["data"].get("chunk")
                if chunk and hasattr(chunk, "content") and chunk.content:
                    yield _sse("token", {"content": chunk.content})

    except Exception as exc:
        logger.error("sse_stream_error", error=str(exc))
        yield _sse("error", {"message": str(exc)})

    yield _sse("done", {"session_id": session_id, "timestamp": _ts()})


# ── Fallback strategy: astream updates (node-level) ─────────────────

async def _stream_updates(
    message: str,
    session_id: str,
    graph,
) -> AsyncGenerator[dict, None]:
    """Fallback: ``graph.astream()`` gives node-level output only.

    The responder text arrives as a single token event rather than streaming.
    """
    config = {"configurable": {"thread_id": session_id}}
    input_state = _build_input(message)

    try:
        async for event in graph.astream(input_state, config=config):
            for node_name, out in event.items():

                if node_name == "planner":
                    po = out.get("planner_output") or {}
                    yield _sse("tool_start", {
                        "id": _uid(), "name": "planner", "args": {},
                        "status": "done", "timestamp": _ts(),
                        "result": {
                            "decision": po.get("decision"),
                            "reasoning": po.get("reasoning"),
                        },
                    })

                elif node_name == "tool_executor":
                    for tr in out.get("tool_results") or []:
                        has_err = "error" in tr
                        yield _sse("tool_end", {
                            "id": _uid(),
                            "name": tr.get("tool", "unknown"),
                            "args": tr.get("args", {}),
                            "status": "error" if has_err else "done",
                            "result": tr.get("result") or tr.get("error"),
                            "timestamp": _ts(),
                        })
                        panel = _maybe_panel(tr)
                        if panel:
                            yield panel

                elif node_name == "rag_retriever":
                    docs = out.get("retrieved_docs") or []
                    yield _sse("tool_end", {
                        "id": _uid(), "name": "knowledge_search",
                        "args": {}, "status": "done", "timestamp": _ts(),
                        "result": f"检索到 {len(docs)} 条文档",
                    })

                elif node_name == "reflector":
                    yield _sse("tool_start", {
                        "id": _uid(), "name": "reflector", "args": {},
                        "status": "done", "timestamp": _ts(),
                        "result": {"verdict": out.get("current_plan")},
                    })

                elif node_name == "responder":
                    for msg in out.get("messages") or []:
                        content = (
                            msg.content if hasattr(msg, "content") else str(msg)
                        )
                        yield _sse("token", {"content": content})

    except Exception as exc:
        logger.error("sse_fallback_error", error=str(exc))
        yield _sse("error", {"message": str(exc)})

    yield _sse("done", {"session_id": session_id, "timestamp": _ts()})


# ── SSE endpoint ─────────────────────────────────────────────────────

async def _event_generator(
    request: ChatRequest,
    graph,
    settings: Settings,
) -> AsyncGenerator[dict, None]:
    sid = request.session_id or _uid()
    logger.info("sse_start", session_id=sid, message=request.message[:80])

    use_fallback = False
    primary = _stream_events(request.message, sid, graph)
    try:
        first_ev = await primary.__anext__()
        yield first_ev
    except Exception as exc:
        logger.warning("astream_events_unavailable", error=str(exc))
        use_fallback = True

    if not use_fallback:
        async for ev in primary:
            yield ev
    else:
        async for ev in _stream_updates(request.message, sid, graph):
            yield ev


@router.post("/stream")
async def stream_chat(
    request_body: ChatRequest,
    http_request: Request,
    settings: Settings = Depends(get_app_settings),
):
    """SSE streaming chat — token / tool_start / tool_end / panel_data / done."""
    graph = http_request.app.state.agent_graph
    return EventSourceResponse(
        _event_generator(request_body, graph, settings),
        media_type="text/event-stream",
    )
