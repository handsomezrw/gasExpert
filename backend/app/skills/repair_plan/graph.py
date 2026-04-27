"""Repair plan skill — LangGraph subgraph definition.

DAG (6 nodes + 1 HITL):
    collect_context → check_materials → create_timeline → generate_report_draft
        → [HITL: repair_review] → (approved) → dispatch_work_order → END
        → (rejected) → END
"""
from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.skills.repair_plan.nodes import (
    check_materials_node,
    collect_context_node,
    create_timeline_node,
    dispatch_work_order_node,
    generate_report_draft_node,
    hitl_review_node,
)
from app.skills.repair_plan.state import RepairPlanState


def _route_after_hitl(state: dict) -> str:
    if state.get("_resume_from") == "repair_review":
        return "dispatch"
    return "end_reject"


def build_repair_plan_graph():
    """Build and return the compiled repair plan subgraph."""
    builder = StateGraph(RepairPlanState)

    builder.add_node("collect_context", collect_context_node)
    builder.add_node("check_materials", check_materials_node)
    builder.add_node("create_timeline", create_timeline_node)
    builder.add_node("generate_report", generate_report_draft_node)
    builder.add_node("hitl_review", hitl_review_node)
    builder.add_node("dispatch", dispatch_work_order_node)

    builder.set_entry_point("collect_context")

    builder.add_edge("collect_context", "check_materials")
    builder.add_edge("check_materials", "create_timeline")
    builder.add_edge("create_timeline", "generate_report")
    builder.add_edge("generate_report", "hitl_review")

    builder.add_conditional_edges("hitl_review", _route_after_hitl, {
        "dispatch": "dispatch",
        "end_reject": END,
    })

    builder.add_edge("dispatch", END)

    return builder.compile()


repair_plan_graph = build_repair_plan_graph()
__all__ = ["repair_plan_graph", "build_repair_plan_graph"]
