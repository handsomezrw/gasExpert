"""Valve isolation skill — state & I/O schemas."""
from __future__ import annotations

from typing import Literal, TypedDict

from pydantic import Field

from app.skills.base import SkillInput, SkillOutput


class ValveIsolationInput(SkillInput):
    """Skill input: leak point + pipeline context."""
    leak_point_id: str = Field(description="泄漏点唯一标识")
    pipeline_id: str = Field(description="泄漏管段 ID")
    severity: Literal["pinhole", "crack", "rupture"] = Field(description="泄漏严重程度")
    pressure: float | None = Field(None, description="管道压力 (MPa)")
    diameter: float | None = Field(None, description="管道直径 (mm)")
    location: str | None = Field(None, description="位置描述")


class ValveIsolationOutput(SkillOutput):
    """Skill output: valve sequence + impact assessment."""
    feasible: bool = False
    valve_sequence: list[dict] = Field(default_factory=list, description="关阀序列（排序后）")
    isolated_pipelines: list[str] = Field(default_factory=list)
    affected_users: int = 0
    estimated_time_min: float = 0.0
    risk_notes: list[str] = Field(default_factory=list)
    scada_dispatched: bool = False


class ValveIsolationState(TypedDict, total=False):
    """Internal LangGraph state (TypedDict — all fields optional)."""
    _input: dict
    _output: dict | None
    _approval_history: list
    _resume_from: str | None
    isolation_plan_raw: dict | None
    valve_candidates: list
    valve_sequence: list
    topology_loaded: bool
    scada_result: dict | None
    _merged_topo: object
