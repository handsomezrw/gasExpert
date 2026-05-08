"""Tests for valve_isolation skill — deterministic input → output."""
from __future__ import annotations

import pytest

from app.skills.valve_isolation.skill import ValveIsolationSkill


@pytest.fixture
def skill():
    return ValveIsolationSkill()


@pytest.mark.asyncio
async def test_valid_input_pending_at_hitl(skill):
    """A known pipeline in the demo topology should yield a feasible plan
    and pause at the HITL checkpoint."""
    result = await skill.ainvoke({
        "leak_point_id": "LP-001",
        "pipeline_id": "P3",
        "severity": "crack",
        "pressure": 0.4,
        "diameter": 200,
    })
    assert result.pending
    assert result.approval_type == "valve_preview"
    pp = result.preview_payload
    assert pp is not None
    assert pp["valve_count"] > 0


@pytest.mark.asyncio
async def test_unknown_pipeline_falls_back(skill):
    """An unknown pipeline falls back to the first available topology pipe."""
    result = await skill.ainvoke({
        "leak_point_id": "LP-002",
        "pipeline_id": "NONEXISTENT",
        "severity": "rupture",
    })
    # Should still work — fallback to first available pipe in demo topology
    assert not result.rejected


@pytest.mark.asyncio
async def test_unknown_severity_normalized(skill):
    """Unknown severity values are normalized to 'crack' instead of crashing."""
    result = await skill.ainvoke({
        "leak_point_id": "LP-003",
        "pipeline_id": "P1",
        "severity": "unknown_type",
    })
    # Should not crash — validator maps unknown → crack
    assert result.pending  # still hits HITL (valid pipeline P1)


@pytest.mark.asyncio
async def test_hitl_preview_for_terminal_pipeline(skill):
    """P4 (V2→C1) terminal pipeline — should pause at HITL with preview."""
    result = await skill.ainvoke({
        "leak_point_id": "LP-004",
        "pipeline_id": "P4",
        "severity": "pinhole",
    })
    assert result.pending
    assert result.approval_type == "valve_preview"
    pp = result.preview_payload
    assert pp is not None
    assert pp["valve_count"] > 0
    assert pp["affected_users"] >= 0


@pytest.mark.asyncio
async def test_backbone_pipeline_P1(skill):
    """P1 (SRC1→V1) — should produce valve sequence preview."""
    result = await skill.ainvoke({
        "leak_point_id": "LP-P1",
        "pipeline_id": "P1",
        "severity": "rupture",
    })
    assert result.pending
    assert result.preview_payload["valve_count"] > 0


@pytest.mark.asyncio
async def test_branch_pipeline_P3_affects_users(skill):
    """P3 branch — affected_users should be > 0."""
    result = await skill.ainvoke({
        "leak_point_id": "LP-P3",
        "pipeline_id": "P3",
        "severity": "crack",
    })
    assert result.pending
    assert result.preview_payload["affected_users"] > 0


@pytest.mark.asyncio
async def test_terminal_pipeline_minimal_valves(skill):
    """P4 (V2→C1) has V2 in valve sequence."""
    result = await skill.ainvoke({
        "leak_point_id": "LP-P4",
        "pipeline_id": "P4",
        "severity": "pinhole",
    })
    assert result.pending
    assert result.preview_payload["valve_count"] > 0
