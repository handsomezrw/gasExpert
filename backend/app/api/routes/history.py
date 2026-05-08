"""Conversation history endpoints backed by SQLite (sessions + messages)."""

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.database import get_async_session
from app.memory import repository as repo

router = APIRouter()


def _dt_to_epoch_ms(dt: datetime) -> int:
    if dt.tzinfo is None:
        return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)
    return int(dt.timestamp() * 1000)


def _message_to_api(row) -> dict:
    extra: dict = {}
    try:
        extra = json.loads(row.metadata_json or "{}")
    except json.JSONDecodeError:
        extra = {}
    out: dict = {
        "id": str(row.id),
        "role": row.role,
        "content": row.content,
        "timestamp": _dt_to_epoch_ms(row.created_at),
    }
    if extra.get("toolCalls"):
        out["toolCalls"] = extra["toolCalls"]
    if extra.get("panelData"):
        out["panelData"] = extra["panelData"]
    return out


@router.get("/sessions")
async def list_sessions(db: AsyncSession = Depends(get_async_session)):
    """List conversation sessions, newest first."""
    rows = await repo.list_conversation_sessions(db)
    return {
        "sessions": [
            {
                "id": r.session_id,
                "title": r.title,
                "createdAt": _dt_to_epoch_ms(r.created_at),
                "updatedAt": _dt_to_epoch_ms(r.updated_at),
            }
            for r in rows
        ]
    }


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, db: AsyncSession = Depends(get_async_session)):
    """Return all messages for a session (chronological order)."""
    messages = await repo.get_messages_for_session(db, session_id)
    return {
        "session_id": session_id,
        "messages": [_message_to_api(m) for m in messages],
    }


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, db: AsyncSession = Depends(get_async_session)):
    """Delete a session and all its messages."""
    deleted = await repo.delete_session(db, session_id)
    if not deleted:
        return {"deleted": False, "message": "会话不存在"}
    await db.commit()
    return {"deleted": True, "session_id": session_id}
