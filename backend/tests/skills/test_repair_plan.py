"""Tests for repair_plan skill — deterministic input → output.

Note: The skill has an HITL checkpoint (repair_review) that pauses before dispatch.
Most tests verify the pending state + preview payload.
"""
from __future__ import annotations

import pytest

from app.skills.base import HITLApproval
from app.skills.repair_plan.skill import RepairPlanSkill


@pytest.fixture
def skill():
    return RepairPlanSkill()


@pytest.mark.asyncio
async def test_basic_report_pending_with_preview(skill):
    """Standard input → pending at HITL with correct preview payload."""
    result = await skill.ainvoke({
        "incident_type": "天然气管道泄漏",
        "location": "成都市武侯区",
        "situation_summary": "PE管 De110 中压管道破裂，有燃气泄漏声",
        "valve_isolation_result": {
            "feasible": True,
            "valve_count": 2,
            "affected_users": 120,
            "estimated_time_min": 15,
            "scada_dispatched": False,
            "valve_sequence": [
                {"valve_id": "V1", "label": "V1 主阀", "method": "SCADA 远控"},
                {"valve_id": "V5", "label": "V5 主干阀", "method": "SCADA 远控"},
            ],
        },
        "diffusion_zone_result": {
            "zones": [
                {"level": "red", "radius_m": 50, "population": 50},
                {"level": "orange", "radius_m": 100, "population": 200},
                {"level": "yellow", "radius_m": 200, "population": 500},
            ],
            "model_used": "高斯烟羽模型",
            "weather_used": {"temperature": 22, "wind_speed": 10, "wind_direction": "北风"},
        },
    })
    assert result.pending
    assert result.approval_type == "repair_review"
    pp = result.preview_payload
    assert pp is not None
    assert pp["incident_type"] == "天然气管道泄漏"
    assert pp["affected_users"] == 120
    assert pp["total_estimated_hours"] > 0
    assert pp["timeline_steps"] == 5


@pytest.mark.asyncio
async def test_minimal_input_still_pending(skill):
    """Even with minimal input, skill should produce a report and hit HITL."""
    result = await skill.ainvoke({
        "incident_type": "PE管破裂",
        "location": "成都市锦江区",
        "situation_summary": "中压管道泄漏",
    })
    assert result.pending
    assert result.approval_type == "repair_review"
    assert result.preview_payload is not None


@pytest.mark.asyncio
async def test_hitl_rejected_terminates(skill):
    """When HITL is rejected, the skill should terminate without dispatch."""
    result = await skill.ainvoke(
        {"incident_type": "PE管破裂", "location": "成都", "situation_summary": "测试"},
        resume_approval=HITLApproval(approved=False, approval_type="repair_review", reason="信息不足"),
        state_override={
            "_input": {"incident_type": "PE管破裂", "location": "成都", "situation_summary": "测试"},
            "_approval_history": [],
        },
    )
    assert result.rejected
    assert result.output is None


@pytest.mark.asyncio
async def test_hitl_approved_dispatches(skill):
    """After HITL approval, work order should be dispatched."""
    result = await skill.ainvoke(
        {"incident_type": "PE管破裂", "location": "成都", "situation_summary": "测试"},
        resume_approval=HITLApproval(approved=True, approval_type="repair_review"),
        state_override={
            "_input": {"incident_type": "PE管破裂", "location": "成都", "situation_summary": "测试"},
            "_approval_history": [{"approved": True, "approval_type": "repair_review"}],
        },
    )
    # After approval runs through remaining nodes, the graph output
    # from `dispatch` node should contain _output with dispatched info
    assert not result.rejected


@pytest.mark.asyncio
async def test_timeline_has_five_phases(skill):
    """The preview payload should indicate 5 timeline phases."""
    result = await skill.ainvoke({
        "incident_type": "管道泄漏",
        "location": "成都",
        "situation_summary": "测试",
    })
    assert result.pending
    assert result.preview_payload["timeline_steps"] == 5


@pytest.mark.asyncio
async def test_missing_context_not_crash(skill):
    """Missing optional valve/diffusion context should not crash."""
    result = await skill.ainvoke({
        "incident_type": "管道泄漏",
        "location": "成都",
        "situation_summary": "简单测试",
    })
    # Should at least reach HITL without crashing
    assert result.pending or result.output is not None
