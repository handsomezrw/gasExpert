"""Incident webhook + listing endpoints (Phase 6.3 event-driven entry).

POST /api/incidents/webhook — receive incident report, create session, start agent
GET  /api/incidents          — list all incidents
GET  /api/incidents/{id}     — get single incident detail
"""

import json
import asyncio
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.deps import get_app_settings
from app.config import Settings
from app.memory import repository as repo
from app.memory.database import session_factory
from app.agent.state import AgentState

router = APIRouter()
logger = structlog.get_logger()


class WebhookPayload(BaseModel):
    incident_id: str = Field(description="外部系统唯一事故 ID（幂等键）")
    source: str = Field(default="map", description="来源: map / manual / scada")
    message: str = Field(description="事故描述消息，将作为 agent 首条消息")
    payload: dict | None = Field(default_factory=dict, description="附加数据（泄漏参数等）")


class IncidentResponse(BaseModel):
    incident_id: str
    session_id: str
    source: str
    status: str
    created_at: str | None = None


def _uid() -> str:
    import uuid
    return str(uuid.uuid4())


# ── Webhook receiver ────────────────────────────────────────────────────

@router.post("/incidents/webhook", response_model=IncidentResponse)
async def receive_incident(
    body: WebhookPayload,
    http_request: Request,
    settings: Settings = Depends(get_app_settings),
):
    """Receive an incident report from the map / external system.

    Idempotent: duplicate incident_id returns the existing record (no-op).
    On first receipt: creates session, primes agent with message, returns immediately.
    """
    factory = session_factory()
    graph = http_request.app.state.agent_graph

    async with factory() as db:
        # ── Idempotency check ──
        existing = await repo.find_incident(db, body.incident_id)
        if existing is not None:
            logger.info("incident_duplicate", incident_id=body.incident_id)
            return IncidentResponse(
                incident_id=existing.incident_id,
                session_id=existing.session_id,
                source=existing.source,
                status=existing.status,
                created_at=str(existing.created_at) if existing.created_at else None,
            )

        # ── Create session ──
        session_id = f"inc-{body.incident_id}-{_uid()[:8]}"
        await repo.ensure_conversation_session(
            db, session_id, title=f"事故 {body.incident_id[:12]}"
        )

        # ── Persist incident ──
        incident = await repo.create_incident(
            db,
            incident_id=body.incident_id,
            session_id=session_id,
            source=body.source,
            status="active",
            payload=body.payload or {},
        )
        await db.commit()

    # ── Fire-and-forget: start agent with the incident message ──
    async def _run_agent():
        from langchain_core.messages import HumanMessage
        input_state: AgentState = {
            "messages": [HumanMessage(content=body.message)],
            "current_plan": "",
            "planner_output": {},
            "tool_results": [],
            "skill_results": [],
            "retrieved_docs": [],
            "final_report": None,
            "iteration_count": 0,
        }
        config = {"configurable": {"thread_id": session_id}}
        try:
            async for _ in graph.astream(input_state, config=config):
                pass  # SSE subscribers pick up events via their own connection
        except Exception as exc:
            logger.error("incident_agent_failed", incident_id=body.incident_id, error=str(exc))

    _ = asyncio.ensure_future(_run_agent())

    logger.info("incident_created", incident_id=body.incident_id, session_id=session_id)
    return IncidentResponse(
        incident_id=body.incident_id,
        session_id=session_id,
        source=body.source,
        status="active",
        created_at=str(incident.created_at),
    )


# ── Incident listing ────────────────────────────────────────────────────

@router.get("/incidents")
async def list_incidents(status: str | None = None):
    """List all incidents, optionally filtered by status."""
    factory = session_factory()
    async with factory() as db:
        rows = await repo.list_incidents(db, status=status)
        return [
            IncidentResponse(
                incident_id=r.incident_id,
                session_id=r.session_id,
                source=r.source,
                status=r.status,
                created_at=str(r.created_at) if r.created_at else None,
            )
            for r in rows
        ]


@router.get("/incidents/{incident_id}")
async def get_incident(incident_id: str):
    """Get a single incident by id."""
    factory = session_factory()
    async with factory() as db:
        inc = await repo.find_incident(db, incident_id)
        if inc is None:
            raise HTTPException(status_code=404, detail="incident not found")
        return IncidentResponse(
            incident_id=inc.incident_id,
            session_id=inc.session_id,
            source=inc.source,
            status=inc.status,
            created_at=str(inc.created_at) if inc.created_at else None,
        )


@router.patch("/incidents/{incident_id}/resolve")
async def resolve_incident(
    incident_id: str,
    http_request: Request,
):
    """Mark an incident as resolved and run post-mortem.

    Triggers the post_mortem_node on the associated agent session,
    generating a lessons_learned draft for case library storage.
    """
    factory = session_factory()
    graph = http_request.app.state.agent_graph

    async with factory() as db:
        inc = await repo.find_incident(db, incident_id)
        if inc is None:
            raise HTTPException(status_code=404, detail="incident not found")

        await repo.update_incident_status(db, incident_id, "resolved")
        await repo.clear_incident_hitl(db, incident_id)
        await db.commit()

    # Run post-mortem on the associated session
    from app.agent.nodes import post_mortem_node
    from app.memory.checkpointer import get_sqlite_checkpointer

    config = {"configurable": {"thread_id": inc.session_id}}
    try:
        async with get_sqlite_checkpointer() as checkpointer:
            compiled = graph
            state = await compiled.aget_state(config)
            if state and state.values:
                agent_state = dict(state.values)
                result = await post_mortem_node(agent_state)
                lessons = result.get("final_report")
                if lessons:
                    logger.info(
                        "post_mortem_complete",
                        incident_id=incident_id,
                        lessons_length=len(lessons),
                    )
                    # Phase 6.4: auto-write lessons_learned back to case store
                    _ = asyncio.ensure_future(
                        _append_to_case_store(
                            incident_id=incident_id,
                            session_id=inc.session_id,
                            agent_state=agent_state,
                            lessons_learned=lessons,
                        )
                    )
    except Exception as exc:
        logger.error("post_mortem_failed", incident_id=incident_id, error=str(exc))
        lessons = None

    return {
        "incident_id": incident_id,
        "status": "resolved",
        "lessons_learned": lessons,
    }


# ── Case store persistence helper (Phase 6.4) ──────────────────────────

async def _append_to_case_store(
    incident_id: str,
    session_id: str,
    agent_state: dict,
    lessons_learned: str,
) -> None:
    """Extract fields from agent state, build an IncidentCase, append to file.

    Fire-and-forget — failures are logged but don't block the resolve response.
    """
    try:
        import json
        from datetime import datetime, timezone
        from pathlib import Path

        from app.cases.schema import (
            AlarmStage,
            DispatchStage,
            FailurePoint,
            IncidentCase,
            InitialResponseStage,
            PipelineSpec,
            RecoveryStage,
            RepairAction,
            RepairStage,
            SceneConfirmStage,
            SurroundingEnv,
        )
        from app.memory.case_store import get_case_store

        # ── Extract structured fields from agent state ──
        messages = agent_state.get("messages", [])
        user_text = ""
        for m in messages:
            if hasattr(m, "type") and m.type == "human" and hasattr(m, "content"):
                user_text = m.content
                break

        # Try to extract fields from skill_results (most structured source)
        skill_results = agent_state.get("skill_results", [])
        event_type = ""
        failure_mode = ""
        material = ""
        pressure_class = ""
        repair_method = ""

        for sr in skill_results:
            result = sr.get("result", {})
            # Unwrap SkillResult wrapper
            output = result.get("output") or result
            if isinstance(output, dict):
                # diffusion_zone output
                pass  # no structured case fields in diffusion output
                # repair_plan output
                if output.get("report_markdown"):
                    # Extract from repair plan
                    pass

        # Extract from user message text
        import re
        for pattern, target in [
            (r"事件类型[：:]\s*(\S+)", "event_type"),
            (r"失效模式[：:]\s*(\S+)", "failure_mode"),
            (r"管材[：:]\s*(\S+)", "material"),
            (r"压力等级[：:]\s*(\S+)", "pressure_class"),
            (r"维修方式[：:]\s*(\S+)", "repair_method"),
            (r"直接原因[：:]\s*(\S+)", "direct_cause"),
            (r"间接原因[：:]\s*(\S+)", "indirect_cause"),
        ]:
            m = re.search(pattern, user_text)
            if m:
                val = m.group(1).strip().rstrip("，,。")
                if target == "event_type":
                    event_type = val
                elif target == "failure_mode":
                    failure_mode = val
                elif target == "material":
                    material = val
                elif target == "pressure_class":
                    pressure_class = val
                elif target == "repair_method":
                    repair_method = val

        # Also try comma-separated fields from the message
        if not event_type:
            m = re.search(r"发生(\S+)", user_text)
            if m:
                event_type = m.group(1).strip().rstrip("，,")

        # Fallback: extract from case_recall injected docs
        retrieved = agent_state.get("retrieved_docs", [])
        for doc in retrieved:
            if isinstance(doc, str) and "失效模式" in doc:
                fm = re.search(r"失效模式[：:]\s*(\S+)", doc)
                if fm and not failure_mode:
                    failure_mode = fm.group(1).strip().rstrip("，,。")

        # ── Build IncidentCase ──
        now = datetime.now(timezone.utc)
        case = IncidentCase(
            incident_id=incident_id,
            event_type=event_type or "未知",
            location="",
            alarm=AlarmStage(alarm_time=now.strftime("%H:%M")),
            dispatch=DispatchStage(),
            scene_confirm=SceneConfirmStage(
                pipeline=PipelineSpec(
                    material=material or None,
                    pressure_class=pressure_class or None,
                ),
            ),
            initial_response=InitialResponseStage(),
            repair=RepairStage(
                failure_point=FailurePoint(
                    failure_mode=failure_mode or None,
                ),
                repair_action=RepairAction(
                    repair_method=repair_method or None,
                ),
            ),
            recovery=RecoveryStage(recovery_time=now.strftime("%H:%M")),
            lessons_learned=lessons_learned,
        )

        # ── Append to cases file ──
        processed_dir = (
            Path(__file__).resolve().parents[3] / "data/cases/processed"
        )
        cases_file = processed_dir / "cases_redacted.json"
        existing: list[dict] = []
        if cases_file.exists():
            existing = json.loads(cases_file.read_text(encoding="utf-8"))
        # Avoid duplicate incident_id
        if not any(c.get("incident_id") == incident_id for c in existing):
            existing.append(case.model_dump())
            cases_file.write_text(
                json.dumps(existing, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            # Also update enriched file
            enriched_file = processed_dir / "cases_enriched.json"
            if enriched_file.exists():
                enriched = json.loads(enriched_file.read_text(encoding="utf-8"))
                if not any(c.get("incident_id") == incident_id for c in enriched):
                    enriched.append(case.model_dump())
                    enriched_file.write_text(
                        json.dumps(enriched, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )

            # ── Refresh the in-memory CaseStore cache ──
            store = get_case_store()
            store.ingest()  # re-index

            logger.info(
                "case_appended_to_store",
                incident_id=incident_id,
                total_cases=store.count,
            )
        else:
            logger.info("case_already_in_store", incident_id=incident_id)

    except Exception as exc:
        logger.error("case_store_append_failed", incident_id=incident_id, error=str(exc))
