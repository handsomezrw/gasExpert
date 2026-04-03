"""Conversation history endpoints."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/sessions")
async def list_sessions():
    """List all conversation sessions.

    TODO: Wire up SQLite persistence in Phase 2.
    """
    return {"sessions": []}


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    """Retrieve messages for a specific session."""
    return {"session_id": session_id, "messages": []}
