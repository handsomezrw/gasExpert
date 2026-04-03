"""LangGraph checkpointer for session state persistence."""

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver


def get_memory_checkpointer() -> MemorySaver:
    """In-memory checkpointer — data lost on restart, suitable for dev."""
    return MemorySaver()


def get_sqlite_checkpointer(
    db_path: str = "./data/copilot_checkpoints.db",
) -> AsyncSqliteSaver:
    """SQLite-based checkpointer — persists sessions across restarts."""
    return AsyncSqliteSaver.from_conn_string(db_path)
