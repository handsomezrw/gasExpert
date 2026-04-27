"""Valve isolation skill — LangGraph nodes."""
from __future__ import annotations

import structlog

from app.skills.base import HITLPending
from app.topology import (
    LeakPoint,
    ValveStatus,
    find_isolation_valves,
    load_demo_topology,
)

logger = structlog.get_logger()

# ── Node 1: Validate input ───────────────────────────────────────────────

def validate_input_node(state: dict) -> dict:
    """Verify input parameters are minimally sane."""
    inp = state.get("_input", {})
    pipeline_id = inp.get("pipeline_id", "")
    severity = inp.get("severity", "")
    if not pipeline_id:
        return {
            "_output": {
                "success": False,
                "error": "缺少 pipeline_id",
            },
            "isolation_plan_raw": None,
        }
    if severity not in ("pinhole", "crack", "rupture"):
        return {
            "_output": {
                "success": False,
                "error": f"无效泄漏类型: {severity}",
            },
            "isolation_plan_raw": None,
        }
    logger.info("valve_input_validated", pipeline_id=pipeline_id, severity=severity)
    return {"topology_loaded": False, "isolation_plan_raw": None}


# ── Node 2: Load topology & extract subgraph ────────────────────────────

def load_topology_node(state: dict) -> dict:
    """Load the pipeline topology and extract subgraph around the leak."""
    inp = state.get("_input", {})
    pipeline_id = inp.get("pipeline_id", "")

    topo = load_demo_topology()
    pipe = topo.get_pipeline(pipeline_id)
    if pipe is None:
        return {
            "_output": {"success": False, "error": f"管段 {pipeline_id} 不在拓扑中"},
        }

    # Phase 6 demo: use full topology (small, 11 nodes).
    # Phase 7: replace with remote topology fetch + subgraph extraction.
    logger.info("topo_loaded", nodes=len(topo._nodes))  # noqa: SLF001
    return {"topology_loaded": True, "_merged_topo": topo}


# ── Node 3: Compute min-cut / isolation plan ────────────────────────────

def compute_isolation_node(state: dict) -> dict:
    """Run the min-cut algorithm to determine which valves to close."""
    inp = state.get("_input", {})
    topo = state.get("_merged_topo")
    if topo is None:
        return {"_output": {"success": False, "error": "拓扑未加载"}}

    try:
        leak = LeakPoint(
            pipeline_id=inp["pipeline_id"],
            position=0.5,
            severity=inp.get("severity", "crack"),
        )
    except Exception as exc:
        return {"_output": {"success": False, "error": f"泄漏参数无效: {exc}"}}

    try:
        plan = find_isolation_valves(topo, leak)
        return {"isolation_plan_raw": plan.to_dict()}
    except Exception as exc:
        return {"_output": {"success": False, "error": f"隔离计算失败: {exc}"}}


# ── Node 4: Check valve operability & sort by distance/priority ─────────

def operability_node(state: dict) -> dict:
    """Filter valve candidates for operability and sort by execution order."""
    plan_raw = state.get("isolation_plan_raw", {})
    if not plan_raw.get("feasible"):
        return {"valve_candidates": []}

    # Load fresh topology to get valve details
    topo = load_demo_topology()
    valves = []
    for vid in plan_raw.get("valve_ids", []):
        v = topo.get_node(vid)
        if v is None:
            continue
        operable = v.status not in (ValveStatus.UNKNOWN,)
        valves.append({
            "id": vid,
            "label": getattr(v, "label", vid),
            "operable": operable,
            "remote_controllable": getattr(v, "remote_controllable", False),
            "manual_access": getattr(v, "manual_access_desc", None),
            "status": v.status.value,
        })

    # Sort: remote-controllable first, then by label
    valves.sort(key=lambda x: (not x["remote_controllable"], x["label"] or x["id"]))
    return {"valve_candidates": valves}


# ── Node 5: Generate execution sequence ────────────────────────────────

def sequence_node(state: dict) -> dict:
    """Build the final valve closure sequence with estimated times."""
    candidates = state.get("valve_candidates", [])
    plan_raw = state.get("isolation_plan_raw", {})

    sequence = []
    total_min = 0.0
    for i, v in enumerate(candidates):
        time_min = 2.0 if v["remote_controllable"] else 10.0
        total_min += time_min
        sequence.append({
            "order": i + 1,
            "valve_id": v["id"],
            "label": v["label"],
            "action": "close",
            "method": "SCADA 远控" if v["remote_controllable"] else "现场手动",
            "estimated_time_min": time_min,
            "remote_controllable": v["remote_controllable"],
            "manual_access": v.get("manual_access"),
        })

    return {
        "valve_sequence": sequence,
        "_output": {
            "success": True,
            "feasible": plan_raw.get("feasible", False),
            "valve_sequence": sequence,
            "isolated_pipelines": plan_raw.get("isolated_pipelines", []),
            "affected_users": plan_raw.get("affected_users", 0),
            "estimated_time_min": round(total_min, 1),
            "risk_notes": plan_raw.get("notes", []),
        },
    }


# ── Node 6: HITL checkpoint ─────────────────────────────────────────────

def hitl_preview_node(state: dict) -> dict:
    """Raise HITLPending to pause execution for dispatcher approval."""
    if state.get("_resume_from") == "valve_preview":
        return {"_pending_approval": None}

    seq = state.get("valve_sequence", [])
    preview = {
        "valve_count": len(seq),
        "affected_users": state.get("_output", {}).get("affected_users", 0),
        "estimated_time_min": state.get("_output", {}).get("estimated_time_min", 0),
        "valves": seq,
    }
    raise HITLPending(
        approval_type="valve_preview",
        preview_payload=preview,
        prompt="方案预览：请审批关阀序列",
    )


# ── Node 7: Mock SCADA dispatch ─────────────────────────────────────────

def scada_dispatch_node(state: dict) -> dict:
    """Mock SCADA dispatch — mark valves as being closed."""
    seq = state.get("valve_sequence", [])
    dispatched = []
    for v in seq:
        dispatched.append({
            "valve_id": v["valve_id"],
            "dispatched": True,
            "method": v["method"],
        })

    output = dict(state.get("_output", {}))
    output["scada_dispatched"] = True
    output["scada_dispatch_log"] = dispatched
    logger.info("scada_dispatched", count=len(dispatched))
    return {"_output": output, "scada_result": {"dispatched": len(dispatched)}}
