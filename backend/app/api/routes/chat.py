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

import asyncio
import structlog
from fastapi import APIRouter, Depends, Request
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app.api.deps import get_app_settings
from app.config import Settings
from app.memory import repository as repo
from app.memory.database import session_factory

router = APIRouter()
logger = structlog.get_logger()


# ── DB persistence (parallel to LangGraph checkpoint) ────────────────


def _title_from_first_message(text: str) -> str:
    t = text.strip()
    if len(t) <= 24:
        return t
    return t[:24] + "..."


class _ToolCallMerge:
    """Mirror front-end merge: tool_start rows updated by tool_end."""

    def __init__(self) -> None:
        self.items: list[dict] = []

    def add_start(self, data: dict) -> None:
        self.items.append({
            "id": data.get("id", ""),
            "name": data.get("name", ""),
            "args": data.get("args") or {},
            "result": data.get("result"),
            "status": data.get("status", "running"),
            "timestamp": data.get("timestamp", _ts()),
        })

    def end(self, data: dict) -> None:
        name = data.get("name", "")
        for i in range(len(self.items) - 1, -1, -1):
            if self.items[i]["name"] == name and self.items[i]["status"] == "running":
                self.items[i]["status"] = data.get("status", "done")
                self.items[i]["result"] = data.get("result")
                self.items[i]["timestamp"] = data.get("timestamp", _ts())
                break


def _persist_from_yield(sse_dict: dict, ctx: dict | None) -> None:
    if ctx is None:
        return
    try:
        ev = sse_dict.get("event", "")
        raw = sse_dict.get("data", "{}")
        payload = json.loads(raw) if isinstance(raw, str) else raw
        if ev == "token":
            ctx["assistant"] += payload.get("content", "")
        elif ev == "tool_start":
            ctx["tool_merge"].add_start(payload)
        elif ev == "tool_end":
            ctx["tool_merge"].end(payload)
        elif ev == "panel_data":
            ctx["panels"].append({
                "type": payload.get("type"),
                "data": payload.get("data") or {},
            })
    except Exception:
        pass


async def _save_user_turn(session_id: str, message: str) -> None:
    factory = session_factory()
    title = _title_from_first_message(message)
    try:
        async with factory() as db:
            await repo.ensure_conversation_session(db, session_id, title=title)
            await repo.add_message(db, session_id, "user", message)
            await db.commit()
    except Exception as exc:
        logger.error("persist_user_failed", error=str(exc), session_id=session_id)


async def _save_assistant_turn(session_id: str, ctx: dict) -> None:
    factory = session_factory()
    extra: dict = {}
    if ctx["tool_merge"].items:
        extra["toolCalls"] = ctx["tool_merge"].items
    if ctx["panels"]:
        extra["panelData"] = ctx["panels"]
    try:
        async with factory() as db:
            await repo.add_message(
                db,
                session_id,
                "assistant",
                ctx["assistant"],
                extra=extra if extra else None,
            )
            await db.commit()
    except Exception as exc:
        logger.error("persist_assistant_failed", error=str(exc), session_id=session_id)


# ── Request / Response models ────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


class ApproveRequest(BaseModel):
    session_id: str = Field(description="会话 ID（对应 incident session）")
    approved: bool = Field(description="是否批准")
    reason: str | None = Field(None, description="驳回原因")


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
        "skill_results": [],
        "retrieved_docs": [],
        "final_report": None,
        "iteration_count": 0,
    }



# ── Map overlay push (Phase 6.2) ───────────────────────────────────


async def _maybe_push_overlay(skill_name: str, result_data: dict, session_id: str) -> None:
    """Auto-push GeoJSON overlay to the Web map when a skill completes."""
    geojson = None
    layer_type = None
    title = ""
    if skill_name == "diffusion_zone" and result_data.get("geojson"):
        geojson = result_data["geojson"]
        layer_type = "evacuation_zone"
        title = "疏散范围"
    elif skill_name == "valve_isolation" and result_data.get("feasible"):
        # Build a lightweight GeoJSON from valve sequence
        features = []
        for v in result_data.get("valve_sequence", []):
            features.append({
                "type": "Feature",
                "properties": {"id": v["valve_id"], "label": v.get("label", ""),
                                "action": v["action"], "method": v.get("method", "")},
                "geometry": {"type": "Point", "coordinates": [0, 0]},
            })
        if features:
            geojson = {"type": "FeatureCollection", "features": features}
            layer_type = "valve_isolation"
            title = "关阀方案"

    if geojson and layer_type:
        try:
            from app.integrations import WebMapClient
            client = WebMapClient()
            await client.push_overlay(session_id, geojson, layer_type, title=title)
        except Exception as exc:
            logger.debug("overlay_push_skipped", skill=skill_name, reason=str(exc)[:120])
# ── HITL pending store helper (Phase 6.5) ────────────────────────────

def _store_pending_hitl(
    session_id: str,
    skill_name: str,
    skill_cls_name: str,
    input_args: dict,
    result_data: dict,
) -> None:
    """If a skill returned pending, persist it so the approve endpoint can resume."""
    if not result_data.get("pending"):
        return
    try:
        from app.memory.hitl_store import get_hitl_store, PendingApproval

        store = get_hitl_store()
        pa = PendingApproval(
            session_id=session_id,
            skill_name=skill_name,
            approval_type=result_data.get("approval_type", ""),
            approval_prompt=result_data.get("approval_prompt", ""),
            preview_payload=result_data.get("preview_payload") or {},
            skill_cls_name=skill_cls_name,
            input_args=input_args,
            partial_state=result_data.get("_resume_state") or {},
        )
        asyncio.ensure_future(store.set_pending(session_id, pa))
    except Exception as exc:
        logger.warning("hitl_store_failed", error=str(exc))


# ── Panel data mapping ──────────────────────────────────────────────

_PANEL_MAP = {
    "calculate_evacuation_zone": "evacuation",
    "query_material_inventory": "inventory",
    "get_weather_info": "weather",
    "generate_report": "report",
    "valve_isolation": "valve_isolation",
    "diffusion_zone": "evacuation",
    "repair_plan": "report",
    "case_recall": "case_recall",
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
                if not isinstance(out, dict):
                    continue
                # Tool results
                if "tool_results" in out:
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
                # Skill results from tool→skill rerouting
                if "skill_results" in out:
                    for sr in out["skill_results"]:
                        has_err = "error" in sr
                        result_data = sr.get("result", {})
                        yield _sse("tool_end", {
                            "id": _uid(),
                            "name": sr.get("skill", "unknown"),
                            "args": sr.get("args", {}),
                            "status": "error" if has_err else "done",
                            "result": result_data,
                            "timestamp": _ts(),
                        })
                        skill_name = sr.get("skill", "")
                        panel_type = _PANEL_MAP.get(skill_name)
                        actual_output = (result_data.get("output") or {}) if isinstance(result_data, dict) else {}
                        pending = result_data.get("pending", False) if isinstance(result_data, dict) else False
                        preview = (result_data.get("preview_payload") or {}) if isinstance(result_data, dict) else {}
                        panel_data = actual_output if actual_output else preview
                        if panel_type and panel_data:
                            yield _sse("panel_data", {
                                "type": panel_type,
                                "data": {"skill": skill_name, "pending": pending, "session_id": session_id, **panel_data},
                            })
                        if pending:
                            _store_pending_hitl(
                                session_id=session_id, skill_name=skill_name,
                                skill_cls_name=skill_name,
                                input_args=sr.get("args", {}), result_data=result_data,
                            )
                        _ = asyncio.ensure_future(_maybe_push_overlay(skill_name, actual_output, session_id))

            # ── Skill executor completed (Phase 6.1) ──────────────
            elif kind == "on_chain_end" and node == "skill_executor":
                out = ev["data"].get("output")
                if not isinstance(out, dict) or "skill_results" not in out:
                    continue
                for sr in out["skill_results"]:
                    has_err = "error" in sr
                    result_data = sr.get("result", {})
                    yield _sse("tool_end", {
                        "id": _uid(),
                        "name": sr.get("skill", "unknown"),
                        "args": sr.get("args", {}),
                        "status": "error" if has_err else "done",
                        "result": result_data,
                        "timestamp": _ts(),
                    })
                    skill_name = sr.get("skill", "")
                    panel_type = _PANEL_MAP.get(skill_name)
                    # Unwrap SkillResult: data is in "output" (completed) or "preview_payload" (pending HITL)
                    actual_output = (result_data.get("output") or {}) if isinstance(result_data, dict) else {}
                    pending = result_data.get("pending", False) if isinstance(result_data, dict) else False
                    preview = (result_data.get("preview_payload") or {}) if isinstance(result_data, dict) else {}
                    panel_data = actual_output if actual_output else preview
                    if panel_type and panel_data:
                        yield _sse("panel_data", {
                            "type": panel_type,
                            "data": {
                                "skill": skill_name,
                                "pending": pending,
                                "session_id": session_id,
                                **panel_data,
                            },
                        })
                    # Phase 6.5: if pending, store for later resume
                    if pending:
                        _store_pending_hitl(
                            session_id=session_id,
                            skill_name=skill_name,
                            skill_cls_name=skill_name,
                            input_args=sr.get("args", {}),
                            result_data=result_data,
                        )
                    # Phase 6.2: auto-push overlay to Web map
                    _ = asyncio.ensure_future(
                        _maybe_push_overlay(skill_name, actual_output, session_id)
                    )

            # ── Case recall completed (Phase 6.4) ─────────────────
            elif kind == "on_chain_end" and node == "case_recall":
                out = ev["data"].get("output")
                if not isinstance(out, dict) or "retrieved_docs" not in out:
                    continue
                docs = out["retrieved_docs"]
                # Find case recall docs (those starting with "## 相似历史事故")
                for doc in docs:
                    if isinstance(doc, str) and "相似历史事故" in doc:
                        yield _sse("panel_data", {
                            "type": "case_recall",
                            "data": {"content": doc},
                        })
                        break

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
                    # Also handle skill results from tool→skill rerouting
                    for sr in out.get("skill_results") or []:
                        has_err = "error" in sr
                        result_data = sr.get("result", {})
                        yield _sse("tool_end", {
                            "id": _uid(),
                            "name": sr.get("skill", "unknown"),
                            "args": sr.get("args", {}),
                            "status": "error" if has_err else "done",
                            "result": result_data,
                            "timestamp": _ts(),
                        })
                        skill_name = sr.get("skill", "")
                        panel_type = _PANEL_MAP.get(skill_name)
                        actual_output = (result_data.get("output") or {}) if isinstance(result_data, dict) else {}
                        pending = result_data.get("pending", False) if isinstance(result_data, dict) else False
                        preview = (result_data.get("preview_payload") or {}) if isinstance(result_data, dict) else {}
                        panel_data = actual_output if actual_output else preview
                        if panel_type and panel_data:
                            yield _sse("panel_data", {
                                "type": panel_type,
                                "data": {"skill": skill_name, "pending": pending, "session_id": session_id, **panel_data},
                            })
                        if pending:
                            _store_pending_hitl(
                                session_id=session_id, skill_name=skill_name,
                                skill_cls_name=skill_name,
                                input_args=sr.get("args", {}), result_data=result_data,
                            )
                        _ = asyncio.ensure_future(_maybe_push_overlay(skill_name, actual_output, session_id))

                elif node_name == "skill_executor":
                    for sr in out.get("skill_results") or []:
                        has_err = "error" in sr
                        result_data = sr.get("result", {})
                        yield _sse("tool_end", {
                            "id": _uid(),
                            "name": sr.get("skill", "unknown"),
                            "args": sr.get("args", {}),
                            "status": "error" if has_err else "done",
                            "result": result_data,
                            "timestamp": _ts(),
                        })
                        skill_name = sr.get("skill", "")
                        panel_type = _PANEL_MAP.get(skill_name)
                        # Unwrap SkillResult: data is in "output" (completed) or "preview_payload" (pending HITL)
                        actual_output = (result_data.get("output") or {}) if isinstance(result_data, dict) else {}
                        pending = result_data.get("pending", False) if isinstance(result_data, dict) else False
                        preview = (result_data.get("preview_payload") or {}) if isinstance(result_data, dict) else {}
                        panel_data = actual_output if actual_output else preview
                        if panel_type and panel_data:
                            yield _sse("panel_data", {
                                "type": panel_type,
                                "data": {
                                    "skill": skill_name,
                                    "pending": pending,
                                    "session_id": session_id,
                                    **panel_data,
                                },
                            })
                        if pending:
                            _store_pending_hitl(
                                session_id=session_id,
                                skill_name=skill_name,
                                skill_cls_name=skill_name,
                                input_args=sr.get("args", {}),
                                result_data=result_data,
                            )
                        # Phase 6.2: auto-push overlay to Web map
                        _ = asyncio.ensure_future(
                            _maybe_push_overlay(skill_name, actual_output, session_id)
                        )

                elif node_name == "case_recall":
                    docs = out.get("retrieved_docs") or []
                    for doc in docs:
                        if isinstance(doc, str) and "相似历史事故" in doc:
                            yield _sse("panel_data", {
                                "type": "case_recall",
                                "data": {"content": doc},
                            })
                            break

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

    persist_ctx = {
        "assistant": "",
        "tool_merge": _ToolCallMerge(),
        "panels": [],
    }

    await _save_user_turn(sid, request.message)

    use_fallback = False
    primary = _stream_events(request.message, sid, graph)
    try:
        first_ev = await primary.__anext__()
        _persist_from_yield(first_ev, persist_ctx)
        yield first_ev
    except Exception as exc:
        logger.warning("astream_events_unavailable", error=str(exc))
        use_fallback = True

    if not use_fallback:
        async for ev in primary:
            _persist_from_yield(ev, persist_ctx)
            yield ev
    else:
        async for ev in _stream_updates(request.message, sid, graph):
            _persist_from_yield(ev, persist_ctx)
            yield ev

    await _save_assistant_turn(sid, persist_ctx)


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


@router.get("/stream/{session_id}")
async def watch_session(
    session_id: str,
    http_request: Request,
):
    """Watch an existing session's progress (Phase 6.3 multi-terminal sync).

    Streams historical messages as replay events, then stays open for live updates.
    Clients that share a session_id see the same incident progress.
    """
    factory = session_factory()

    async def _replay_and_watch() -> AsyncGenerator[dict, None]:
        # 1. Replay existing messages from DB
        try:
            async with factory() as db:
                msgs = await repo.get_messages_for_session(db, session_id)
                for msg in msgs:
                    extra = {}
                    try:
                        extra = json.loads(msg.metadata_json or "{}")
                    except (json.JSONDecodeError, TypeError):
                        pass
                    if msg.role == "user":
                        yield _sse("token", {"content": ""})  # no-op token
                    elif msg.role == "assistant":
                        yield _sse("token", {"content": msg.content})
                        # Replay tool calls
                        for tc in extra.get("toolCalls", []):
                            yield _sse("tool_end", tc)
                        # Replay panel data
                        for pd in extra.get("panelData", []):
                            yield _sse("panel_data", pd)
        except Exception as exc:
            logger.warning("watch_replay_failed", session_id=session_id, error=str(exc))

        # 2. Keep connection open, polling for new messages
        last_msg_count = 0
        while True:
            try:
                async with factory() as db:
                    msgs = await repo.get_messages_for_session(db, session_id)
                    if len(msgs) > last_msg_count:
                        # Send new messages
                        for msg in msgs[last_msg_count:]:
                            if msg.role == "assistant":
                                yield _sse("token", {"content": msg.content})
                        last_msg_count = len(msgs)
                await asyncio.sleep(2)
            except Exception:
                await asyncio.sleep(5)

    return EventSourceResponse(
        _replay_and_watch(),
        media_type="text/event-stream",
    )


# ── HITL approve endpoint (Phase 6.5) ──────────────────────────────────

@router.post("/approve")
async def approve_hitl(
    body: ApproveRequest,
    http_request: Request,
):
    """Approve or reject a pending HITL checkpoint.

    On approval: resumes the paused skill with ``resume_approval``,
    adds the skill output to the chat stream, and triggers the reflector
    to continue the agent loop.
    """
    from app.memory.hitl_store import get_hitl_store

    store = get_hitl_store()

    # Check if there's a pending approval
    pa = await store.get_pending(body.session_id)
    if pa is None:
        return {"status": "no_pending", "message": "没有待审批的项目"}

    # Resume the skill
    result = await store.resume_with(
        body.session_id,
        approved=body.approved,
        reason=body.reason,
    )

    if result is None:
        return {"status": "error", "message": "审批恢复失败"}

    # If approved and skill completed, run reflector → responder
    if body.approved and not result.get("pending") and not result.get("rejected"):
        graph = http_request.app.state.agent_graph
        config = {"configurable": {"thread_id": body.session_id}}

        # Get current agent state
        state_snapshot = await graph.aget_state(config)
        if state_snapshot and state_snapshot.values:
            agent_state = dict(state_snapshot.values)
            # Append the resumed skill output
            skill_results = list(agent_state.get("skill_results") or [])
            skill_results.append({
                "skill": pa.skill_name,
                "args": pa.input_args,
                "result": result,
            })
            agent_state["skill_results"] = skill_results
            agent_state["current_plan"] = ""  # reset so reflector runs

            # Re-enter the agent graph (skip planner → go to reflector)
            try:
                async for ev in graph.astream(agent_state, config=config):
                    pass  # Events handled by watch endpoint / SSE subscribers
            except Exception as exc:
                logger.error("approve_resume_failed",
                            session_id=body.session_id, error=str(exc))

    return {
        "status": "approved" if body.approved else "rejected",
        "session_id": body.session_id,
        "result": result,
    }
