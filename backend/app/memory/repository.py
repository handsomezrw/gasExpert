"""Async CRUD for conversation sessions, messages, and incidents."""

import json
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.models import ConversationSession, Incident, Message


async def ensure_conversation_session(
    db: AsyncSession,
    session_id: str,
    *,
    title: str | None = None,
) -> ConversationSession:
    """Create session row if missing; bump updated_at."""
    result = await db.execute(
        select(ConversationSession).where(
            ConversationSession.session_id == session_id
        )
    )
    row = result.scalar_one_or_none()
    now = datetime.utcnow()
    if row:
        row.updated_at = now
        if title and (not row.title or row.title == "新对话"):
            row.title = title[:256]
        await db.flush()
        return row

    row = ConversationSession(
        session_id=session_id,
        title=(title[:256] if title else "新对话"),
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    await db.flush()
    return row


async def add_message(
    db: AsyncSession,
    session_id: str,
    role: str,
    content: str,
    *,
    extra: dict[str, Any] | None = None,
) -> Message:
    """Insert a message; updates parent session updated_at."""
    meta = extra or {}
    row = Message(
        session_id=session_id,
        role=role,
        content=content,
        metadata_json=json.dumps(meta, ensure_ascii=False),
    )
    db.add(row)
    await db.execute(
        update(ConversationSession)
        .where(ConversationSession.session_id == session_id)
        .values(updated_at=datetime.utcnow())
    )
    await db.flush()
    return row


async def list_conversation_sessions(
    db: AsyncSession,
) -> list[ConversationSession]:
    result = await db.execute(
        select(ConversationSession).order_by(ConversationSession.updated_at.desc())
    )
    return list(result.scalars().all())


async def get_messages_for_session(
    db: AsyncSession,
    session_id: str,
) -> list[Message]:
    result = await db.execute(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at.asc(), Message.id.asc())
    )
    return list(result.scalars().all())


async def delete_session(
    db: AsyncSession,
    session_id: str,
) -> bool:
    """Delete a conversation session and all its messages. Returns True if deleted."""
    session = await db.execute(
        select(ConversationSession).where(ConversationSession.session_id == session_id)
    )
    row = session.scalar_one_or_none()
    if row is None:
        return False
    await db.delete(row)
    # Also delete associated messages
    await db.execute(
        delete(Message).where(Message.session_id == session_id)
    )
    await db.flush()
    return True


# ── Incidents (Phase 6.3) ──────────────────────────────────────────────

async def create_incident(
    db: AsyncSession,
    incident_id: str,
    session_id: str,
    source: str = "webhook",
    status: str = "active",
    payload: dict | None = None,
) -> Incident:
    """Create a new incident record."""
    row = Incident(
        incident_id=incident_id,
        session_id=session_id,
        source=source,
        status=status,
        payload_json=json.dumps(payload or {}, ensure_ascii=False),
    )
    db.add(row)
    await db.flush()
    return row


async def find_incident(
    db: AsyncSession,
    incident_id: str,
) -> Incident | None:
    """Find an incident by its external id (for idempotency check)."""
    result = await db.execute(
        select(Incident).where(Incident.incident_id == incident_id)
    )
    return result.scalar_one_or_none()


async def list_incidents(
    db: AsyncSession,
    status: str | None = None,
) -> list[Incident]:
    """List incidents, newest first. Optionally filter by status."""
    stmt = select(Incident).order_by(Incident.created_at.desc())
    if status:
        stmt = stmt.where(Incident.status == status)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def update_incident_status(
    db: AsyncSession,
    incident_id: str,
    status: str,
) -> Incident | None:
    """Update incident status and return the updated row."""
    row = await find_incident(db, incident_id)
    if row is None:
        return None
    row.status = status
    row.updated_at = datetime.utcnow()
    await db.flush()
    return row


async def set_incident_hitl(db: AsyncSession, incident_id: str) -> Incident | None:
    """Mark an incident as waiting for HITL approval."""
    row = await find_incident(db, incident_id)
    if row is None:
        return None
    row.hitl_since = datetime.utcnow()
    row.updated_at = datetime.utcnow()
    await db.flush()
    return row


async def clear_incident_hitl(db: AsyncSession, incident_id: str) -> Incident | None:
    """Clear HITL timestamp (approval received)."""
    row = await find_incident(db, incident_id)
    if row is None:
        return None
    row.hitl_since = None
    row.updated_at = datetime.utcnow()
    await db.flush()
    return row


async def list_stalled_incidents(
    db: AsyncSession,
    timeout_minutes: int = 15,
) -> list[Incident]:
    """Find incidents stuck in HITL for longer than the timeout."""
    from datetime import timedelta
    cutoff = datetime.utcnow() - timedelta(minutes=timeout_minutes)
    result = await db.execute(
        select(Incident)
        .where(Incident.hitl_since.isnot(None))
        .where(Incident.hitl_since < cutoff)
        .where(Incident.status == "active")
    )
    return list(result.scalars().all())
