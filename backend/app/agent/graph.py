"""LangGraph core state graph definition."""

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, StateGraph

from app.agent.nodes import (
    check_completeness,
    planner_node,
    rag_retriever_node,
    reflector_node,
    responder_node,
    route_decision,
    tool_executor_node,
)
from app.agent.state import AgentState


def build_graph(checkpointer: BaseCheckpointSaver | None = None):
    """Build and compile the agent state graph.

    Returns a compiled ``CompiledGraph`` ready for invocation.
    """
    builder = StateGraph(AgentState)

    builder.add_node("planner", planner_node)
    builder.add_node("tool_executor", tool_executor_node)
    builder.add_node("rag_retriever", rag_retriever_node)
    builder.add_node("reflector", reflector_node)
    builder.add_node("responder", responder_node)

    builder.set_entry_point("planner")

    builder.add_conditional_edges(
        "planner",
        route_decision,
        {
            "use_tools": "tool_executor",
            "need_rag": "rag_retriever",
            "direct_answer": "responder",
        },
    )
    builder.add_edge("tool_executor", "reflector")
    builder.add_edge("rag_retriever", "reflector")
    builder.add_conditional_edges(
        "reflector",
        check_completeness,
        {
            "need_more": "planner",
            "sufficient": "responder",
        },
    )
    builder.add_edge("responder", END)

    return builder.compile(checkpointer=checkpointer)
