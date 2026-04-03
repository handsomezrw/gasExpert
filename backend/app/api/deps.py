"""Shared FastAPI dependencies for dependency injection."""

from fastapi import Request

from app.config import Settings, get_settings


def get_app_settings() -> Settings:
    return get_settings()


def get_agent_graph(request: Request):
    """Retrieve the compiled agent graph stored in app.state at startup."""
    return request.app.state.agent_graph
