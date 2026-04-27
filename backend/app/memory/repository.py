"""Async CRUD for conversation sessions and messages."""

import json
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.models import ConversationSession, Message


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
