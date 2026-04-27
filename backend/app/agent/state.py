"""LangGraph agent state definition."""

from typing import Annotated, Sequence, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    current_plan: str
    planner_output: dict
    tool_results: list[dict]
    skill_results: list[dict]     # Phase 6.1: results from skill invocations
    retrieved_docs: list[str]
    final_report: str | None
    iteration_count: int
