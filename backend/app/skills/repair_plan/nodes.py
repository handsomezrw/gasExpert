"""Repair plan skill — LangGraph nodes.

DAG (6 nodes + 1 HITL):
    collect_context → check_materials → create_timeline → generate_report_draft
        → [HITL: repair_review] → dispatch_work_order → END
"""
from __future__ import annotations

import json
from datetime import datetime

import structlog

from app.skills.base import HITLPending

logger = structlog.get_logger()

# ── Node 1: Collect context from upstream skills ────────────────────────

def collect_context_node(state: dict) -> dict:
    """Ingest valve_isolation and diffusion_zone outputs into state."""
    inp = state.get("_input", {})

    valve = inp.get("valve_isolation_result") or {}
    diffusion = inp.get("diffusion_zone_result") or {}

    valve_ctx = {
        "feasible": valve.get("feasible", False),
        "valve_count": len(valve.get("valve_sequence", [])),
        "affected_users": valve.get("affected_users", 0),
        "estimated_time_min": valve.get("estimated_time_min", 0),
        "valve_sequence": valve.get("valve_sequence", []),
        "scada_dispatched": valve.get("scada_dispatched", False),
    }

    zones = diffusion.get("zones", [])
    diffusion_ctx = {
        "zone_count": len(zones),
        "max_radius_m": max((z.get("radius_m", 0) for z in zones), default=0),
        "risk_level": diffusion.get("model_used", ""),
        "weather": diffusion.get("weather_used", {}),
        "population_estimate": sum(
            z.get("population", 0) for z in zones
        ) or None,
    }

    logger.info("context_collected", valves=valve_ctx["valve_count"],
                max_radius=diffusion_ctx["max_radius_m"])
    return {
        "valve_context": valve_ctx,
        "diffusion_context": diffusion_ctx,
    }


# ── Node 2: Check material inventory ────────────────────────────────────

async def check_materials_node(state: dict) -> dict:
    """Query inventory for nearby material depots and required supplies."""
    inp = state.get("_input", {})

    if inp.get("material_inventory"):
        return {"material_list": inp["material_inventory"].get("stations", [])}

    location = inp.get("location", "")
    from app.tools.inventory import query_material_inventory

    try:
        result = await query_material_inventory.ainvoke({
            "location": location,
            "radius_km": 15.0,
        })
        materials = result.get("stations", [])
    except Exception as exc:
        logger.warning("inventory_query_failed", error=str(exc))
        materials = []

    return {"material_list": materials}


# ── Node 3: Create repair timeline ──────────────────────────────────────

def create_timeline_node(state: dict) -> dict:
    """Build a phased repair timeline (Gantt-style)."""
    valve = state.get("valve_context", {})
    diffusion = state.get("diffusion_context", {})

    valve_time = valve.get("estimated_time_min", 30)
    total_hours = 0.0

    phases = []
    now = datetime.now()

    # Phase 1: Site arrival & setup
    phases.append({
        "phase": 1,
        "task": "现场到达与警戒设置",
        "duration_hours": 0.5,
        "description": "抢险人员到达现场，设置警戒区和警示标识",
    })
    total_hours += 0.5

    # Phase 2: Valve isolation
    phases.append({
        "phase": 2,
        "task": "阀门关闭操作",
        "duration_hours": round(valve_time / 60, 1),
        "valve_count": valve.get("valve_count", 0),
        "description": f"按序列关闭 {valve.get('valve_count', 0)} 个阀门",
    })
    total_hours += valve_time / 60

    # Phase 3: Gas concentration monitoring
    phases.append({
        "phase": 3,
        "task": "燃气浓度检测与持续监测",
        "duration_hours": 0.5,
        "description": "使用检测仪确认泄漏点周边燃气浓度变化",
    })
    total_hours += 0.5

    # Phase 4: Repair work
    phases.append({
        "phase": 4,
        "task": "管道修复作业",
        "duration_hours": 2.0,
        "description": "根据泄漏类型执行对应修复方案",
    })
    total_hours += 2.0

    # Phase 5: Pressure test & restoration
    phases.append({
        "phase": 5,
        "task": "试压与恢复供气",
        "duration_hours": 1.0,
        "description": "修复后进行压力测试，确认无泄漏后恢复供气",
    })
    total_hours += 1.0

    timeline = []
    cumulative = 0.0
    for p in phases:
        start_h = round(cumulative, 1)
        end_h = round(cumulative + p["duration_hours"], 1)
        cumulative += p["duration_hours"]
        timeline.append({
            "task": p["task"],
            "start_hour": start_h,
            "end_hour": end_h,
            "duration_hours": p["duration_hours"],
            "description": p.get("description", ""),
        })

    return {"timeline": timeline, "personnel_plan": {
        "total_estimated_hours": round(total_hours, 1),
    }}


# ── Node 4: Generate report draft via LLM ───────────────────────────────

async def generate_report_draft_node(state: dict) -> dict:
    """Generate the structured emergency repair report using LLM."""
    inp = state.get("_input", {})
    valve = state.get("valve_context", {})
    diffusion = state.get("diffusion_context", {})
    materials = state.get("material_list", [])
    timeline = state.get("timeline", [])
    personnel = state.get("personnel_plan", {})

    header = (
        f"# 燃气抢险处置报告\n\n"
        f"**报告时间**：{datetime.now().strftime('%Y年%m月%d日 %H:%M')}\n"
        f"**事故类型**：{inp.get('incident_type', '未知')}\n"
        f"**事故地点**：{inp.get('location', '未知')}\n\n"
    )

    summary = (
        f"## 一、事故概况\n"
        f"- 事故类型：{inp.get('incident_type', '未知')}\n"
        f"- 事故地点：{inp.get('location', '未知')}\n"
        f"- 现场摘要：{inp.get('situation_summary', '无')}\n\n"
    )

    valve_section = "## 二、关阀方案\n"
    if valve.get("feasible"):
        valve_section += (
            f"- 关阀数量：{valve.get('valve_count', 0)} 个\n"
            f"- 影响用户：{valve.get('affected_users', 0)} 户\n"
            f"- 预计关阀时间：{valve.get('estimated_time_min', 0)} 分钟\n"
            f"- SCADA 下发：{'已完成' if valve.get('scada_dispatched') else '待审批'}\n\n"
        )
    else:
        valve_section += "- 关阀方案不可行，需人工介入\n\n"

    diffusion_section = "## 三、疏散方案\n"
    d = diffusion
    if d.get("max_radius_m"):
        diffusion_section += (
            f"- 最大疏散半径：{d['max_radius_m']} 米\n"
            f"- 疏散圈数：{d.get('zone_count', 0)} 级\n"
            f"- 估计受影响人口：{d.get('population_estimate', '待评估')}\n"
            f"- 气象条件：{json.dumps(d.get('weather', {}), ensure_ascii=False)}\n\n"
        )
    else:
        diffusion_section += "- 未执行扩散范围计算\n\n"

    resource_section = "## 四、抢修资源\n"
    if materials:
        for m in materials[:3]:
            resource_section += (
                f"- **{m.get('station_name', '未知站点')}**"
                f"（{m.get('distance_km', '?')} km）\n"
            )
    else:
        resource_section += "- 未查询到附近物资站点\n"
    resource_section += "\n"

    timeline_section = "## 五、处置时序\n"
    for t in timeline:
        timeline_section += (
            f"- `{t['start_hour']}h–{t['end_hour']}h` {t['task']}"
            f"（{t['duration_hours']}h）\n"
        )
    timeline_section += "\n"

    report = header + summary + valve_section + diffusion_section + resource_section + timeline_section

    return {
        "report_draft": report,
        "_output": {
            "success": True,
            "report_markdown": report,
            "status": "draft",
            "material_list": materials[:5] if materials else [],
            "personnel_plan": personnel,
            "timeline": timeline,
            "affected_users": valve.get("affected_users", 0),
            "total_estimated_hours": personnel.get("total_estimated_hours", 0),
        },
    }


# ── Node 5: HITL checkpoint ─────────────────────────────────────────────

def hitl_review_node(state: dict) -> dict:
    """Pause for dispatcher to review and approve the repair plan."""
    if state.get("_resume_from") == "repair_review":
        return {"_pending_approval": None}

    output = state.get("_output", {})
    preview = {
        "incident_type": state.get("_input", {}).get("incident_type", ""),
        "location": state.get("_input", {}).get("location", ""),
        "total_estimated_hours": output.get("total_estimated_hours", 0),
        "affected_users": output.get("affected_users", 0),
        "timeline_steps": len(output.get("timeline", [])),
    }
    raise HITLPending(
        approval_type="repair_review",
        preview_payload=preview,
        prompt="请审批抢修方案与工单",
    )


# ── Node 6: Dispatch work order ─────────────────────────────────────────

def dispatch_work_order_node(state: dict) -> dict:
    """Generate and dispatch the work order (mock)."""
    import uuid

    output = dict(state.get("_output", {}))
    work_order_id = f"WO-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
    output["status"] = "dispatched"
    output["work_order_dispatched"] = True
    output["work_order_id"] = work_order_id

    logger.info("work_order_dispatched", work_order_id=work_order_id)
    return {"_output": output}
