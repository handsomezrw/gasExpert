"""Skill abstraction — composite LangGraph workflows with HITL checkpoints.

分层定位（见 PLAN.md 6.1）：
- Tool   原子、无状态、单次调用（@tool 装饰的函数）
- Skill  确定性多步工作流，有内部状态、HITL 检查点；**本模块定义的抽象**
- Agent  LLM 自由决策，决定调哪些 skill、什么顺序

Skill 对主 agent 呈现为"虚拟 tool"——planner 看到的是 input/output 契约，
实际执行时路由到子图。子图共享父图的 checkpointer，以便 HITL 中断/恢复。
"""
from __future__ import annotations

from .base import (
    HITLApproval,
    HITLPending,
    HITLRejected,
    Skill,
    SkillInput,
    SkillOutput,
    SkillRegistry,
    register_skill,
)

# ── Register all skills (import triggers @register_skill decorator) ─────
from .diffusion_zone.skill import DiffusionZoneSkill
from .repair_plan.skill import RepairPlanSkill
from .valve_isolation.skill import ValveIsolationSkill

__all__ = [
    "Skill",
    "SkillInput",
    "SkillOutput",
    "SkillRegistry",
    "HITLApproval",
    "HITLPending",
    "HITLRejected",
    "register_skill",
    # Registered skills
    "ValveIsolationSkill",
    "DiffusionZoneSkill",
    "RepairPlanSkill",
]
