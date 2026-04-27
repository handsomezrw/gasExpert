"""Tests for Skill base class + registry."""
from __future__ import annotations

import pytest

from app.skills import (
    HITLApproval,
    HITLPending,
    Skill,
    SkillInput,
    SkillOutput,
    SkillRegistry,
    register_skill,
)


# ---- Test fixtures ----

class DemoInput(SkillInput):
    x: int


class DemoOutput(SkillOutput):
    doubled: int


@pytest.fixture(autouse=True)
def _clear_registry():
    # 每个测试独立清空
    SkillRegistry.clear()
    yield
    SkillRegistry.clear()


# ---- Simple skill (no HITL) ----

def _make_double_skill():
    @register_skill
    class DoubleSkill(Skill):
        name = "double"
        description = "double the number"
        input_schema = DemoInput
        output_schema = DemoOutput

        def build_graph(self):
            async def run(state):
                x = state["_input"]["x"]
                state["_output"] = {"doubled": x * 2}
                return state
            return run

    return DoubleSkill


# ---- HITL skill ----

def _make_hitl_skill():
    @register_skill
    class HitlDoubleSkill(Skill):
        name = "hitl_double"
        description = "double with approval"
        input_schema = DemoInput
        output_schema = DemoOutput

        def build_graph(self):
            async def run(state):
                if state.get("_resume_from") != "confirm":
                    raise HITLPending(
                        approval_type="confirm",
                        preview_payload={"about_to_double": state["_input"]["x"]},
                        prompt="确认执行翻倍？",
                    )
                x = state["_input"]["x"]
                state["_output"] = {"doubled": x * 2}
                return state
            return run

    return HitlDoubleSkill


# ---- Tests ----

@pytest.mark.asyncio
async def test_registry_records_skill():
    _make_double_skill()
    assert "double" in SkillRegistry.all()
    assert SkillRegistry.get("double").description == "double the number"


@pytest.mark.asyncio
async def test_simple_skill_invocation():
    Cls = _make_double_skill()
    result = await Cls().ainvoke({"x": 7})
    assert not result.pending
    assert not result.rejected
    assert result.output["doubled"] == 14
    assert result.output["success"] is True


@pytest.mark.asyncio
async def test_hitl_pending_then_resume():
    Cls = _make_hitl_skill()
    skill = Cls()

    # 第一次调用：暂停在审批点
    first = await skill.ainvoke({"x": 5})
    assert first.pending
    assert first.approval_type == "confirm"
    assert first.preview_payload == {"about_to_double": 5}

    # 审批通过后继续
    second = await skill.ainvoke(
        {"x": 5},
        resume_approval=HITLApproval(approved=True, approval_type="confirm"),
        state_override={"_input": {"x": 5}, "_approval_history": []},
    )
    assert not second.pending
    assert second.output["doubled"] == 10
    assert len(second.approval_history) == 1


@pytest.mark.asyncio
async def test_hitl_rejection_terminates():
    Cls = _make_hitl_skill()
    result = await Cls().ainvoke(
        {"x": 5},
        resume_approval=HITLApproval(approved=False, approval_type="confirm", reason="不需要"),
        state_override={"_input": {"x": 5}, "_approval_history": []},
    )
    assert result.rejected
    assert result.rejected_reason == "不需要"
    assert result.output is None


@pytest.mark.asyncio
async def test_describe_for_planner_lists_all():
    _make_double_skill()
    _make_hitl_skill()
    desc = SkillRegistry.describe_for_planner()
    assert "double" in desc
    assert "hitl_double" in desc
    assert "x: int" in desc  # input_schema fields present


@pytest.mark.asyncio
async def test_input_validation_rejects_unknown_field():
    Cls = _make_double_skill()
    with pytest.raises(Exception):
        await Cls().ainvoke({"x": 5, "extra_field": "nope"})
