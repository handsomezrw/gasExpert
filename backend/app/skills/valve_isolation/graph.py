"""Valve isolation skill — LangGraph subgraph definition.

DAG (7 nodes + 1 HITL checkpoint):
    validate → load_topo
        → (error?) → END
        → (ok) → compute → operability → sequence
            → (feasible?) → hitl_preview
                → (resumed) → scada_dispatch → END
                → (rejected) → END
            → (infeasible) → END
"""
from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.skills.valve_isolation.nodes import (
    compute_isolation_node,
    hitl_preview_node,
    load_topology_node,
    operability_node,
    scada_dispatch_node,
    sequence_node,
    validate_input_node,
)
from app.skills.valve_isolation.state import ValveIsolationState


def _route_after_topo(state: dict) -> str:
    """If topology load failed, end immediately."""
    output = state.get("_output") or {}
    if output.get("success") is False:
        return "end_fail"
    return "continue"


def _route_after_sequence(state: dict) -> str:
    """Only show HITL for feasible plans. Infeasible plans end directly."""
    output = state.get("_output") or {}
    if not output.get("feasible", False):
        return "infeasible"
    return "hitl"


def _route_after_hitl(state: dict) -> str:
    """If HITL was approved (resume), continue to scada. Otherwise skip."""
    if state.get("_resume_from") == "valve_preview":
        return "scada_dispatch"
    return "end_after_reject"


def build_valve_isolation_graph():
    """Build and return the compiled valve isolation subgraph."""
    builder = StateGraph(ValveIsolationState)

    builder.add_node("validate", validate_input_node)
    builder.add_node("load_topo", load_topology_node)
    builder.add_node("compute", compute_isolation_node)
    builder.add_node("operability", operability_node)
    builder.add_node("sequence", sequence_node)
    builder.add_node("hitl_preview", hitl_preview_node)
    builder.add_node("scada_dispatch", scada_dispatch_node)

    builder.set_entry_point("validate")
    builder.add_edge("validate", "load_topo")

    # After topo: error → END, success → compute
    builder.add_conditional_edges("load_topo", _route_after_topo, {
        "continue": "compute",
        "end_fail": END,
    })
    builder.add_edge("compute", "operability")
    builder.add_edge("operability", "sequence")

    # After sequence: feasible → HITL, infeasible → END
    builder.add_conditional_edges("sequence", _route_after_sequence, {
        "hitl": "hitl_preview",
        "infeasible": END,
    })

    # HITL branch: approved → scada, rejected/skip → END
    builder.add_conditional_edges("hitl_preview", _route_after_hitl, {
        "scada_dispatch": "scada_dispatch",
        "end_after_reject": END,
    })

    builder.add_edge("scada_dispatch", END)

    return builder.compile()


# Expose as a plain async callable for the Skill base class
valve_isolation_graph = build_valve_isolation_graph()
__all__ = ["valve_isolation_graph", "build_valve_isolation_graph"]
