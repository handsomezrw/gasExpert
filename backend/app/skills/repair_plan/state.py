"""Repair plan skill — state & I/O schemas."""
from __future__ import annotations

from typing import TypedDict

from pydantic import Field

from app.skills.base import SkillInput, SkillOutput


class RepairPlanInput(SkillInput):
    """Skill input: incident context + prerequisite skill outputs."""
    incident_type: str = Field(description="事故类型，如 '天然气管道泄漏'")
    location: str = Field(description="事故发生地点")
    situation_summary: str = Field(description="现场情况综合摘要")
    valve_isolation_result: dict | None = Field(None, description="valve_isolation skill 产出")
    diffusion_zone_result: dict | None = Field(None, description="diffusion_zone skill 产出")
    material_inventory: dict | None = Field(None, description="物资库存查询结果")


class RepairPlanOutput(SkillOutput):
    """Skill output: structured report + resource plan + work order."""
    report_markdown: str = Field("", description="完整抢险处置报告 (Markdown)")
    status: str = Field("draft", description="draft / approved / dispatched")
    material_list: list[dict] = Field(default_factory=list, description="所需物资清单")
    personnel_plan: dict = Field(default_factory=dict, description="人员调度计划")
    timeline: list[dict] = Field(default_factory=list, description="时序甘特图数据")
    affected_users: int = 0
    total_estimated_hours: float = 0.0
    work_order_dispatched: bool = False
    work_order_id: str | None = None


class RepairPlanState(TypedDict, total=False):
    """Internal LangGraph state (TypedDict — all fields optional)."""
    _input: dict
    _output: dict | None
    _approval_history: list
    _resume_from: str | None
    valve_context: dict | None
    diffusion_context: dict | None
    material_list: list
    personnel_plan: dict
    timeline: list
    report_draft: str | None
