"""Skill abstract base class + registry + HITL primitives.

设计要点：
1. Skill 是 LangGraph 子图的容器，**不**替代 LangGraph 本身，只提供统一包装
2. 每个 Skill 声明自己的 input_schema / output_schema（Pydantic）
3. HITL 检查点通过抛出 `HITLPending` 暂停执行，调用方用 `resume()` 注入审批结果
4. 注册表在模块加载时收集所有 `@register_skill` 装饰的类，供主 agent 查询

所有 Skill 子图遵循相同约定：
- 状态字典包含 `_input` / `_output` / `_pending_approval` / `_approval_history` 四个保留键
- 节点函数是纯函数，接收 state 返回 partial update
- 审批节点抛 `HITLPending`，runner 负责捕获并包装为返回值
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, ClassVar, Generic, Type, TypeVar

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)


# ---- HITL primitives -----------------------------------------------------

class HITLApproval(BaseModel):
    """用户对某个审批点的决定。"""
    approved: bool
    approval_type: str = Field(description="审批点类型标识，例如 'valve_preview' / 'scada_dispatch'")
    reason: str | None = Field(None, description="驳回时的原因")
    modifications: dict[str, Any] = Field(default_factory=dict, description="驳回时附带的修改建议")


class HITLPending(Exception):
    """由 Skill 节点抛出，表示流程需要人工审批后才能继续。

    Runner 捕获此异常后，把当前 state 持久化到 checkpointer，
    并向调用方返回 `SkillResult.pending=True` + `approval_type` + `preview_payload`。
    """

    def __init__(self, approval_type: str, preview_payload: dict[str, Any],
                 prompt: str = "请审批"):
        self.approval_type = approval_type
        self.preview_payload = preview_payload
        self.prompt = prompt
        super().__init__(f"HITL pending: {approval_type}")


class HITLRejected(Exception):
    """审批被驳回后，由节点决定是否抛出（用于终止整个 Skill）。"""

    def __init__(self, approval_type: str, reason: str | None = None):
        self.approval_type = approval_type
        self.reason = reason
        super().__init__(f"HITL rejected: {approval_type} ({reason or 'no reason'})")


# ---- Skill base + schemas ------------------------------------------------

class SkillInput(BaseModel):
    """Base class for skill input schemas. 子类自行添加字段。"""
    model_config = {"extra": "forbid"}


class SkillOutput(BaseModel):
    """Base class for skill output schemas."""
    model_config = {"extra": "allow"}
    success: bool = True
    error: str | None = None


class SkillResult(BaseModel):
    """Runner 返回给调用方的统一结果对象。"""
    model_config = {"extra": "allow"}

    skill_name: str
    # 正常完成时 output 非空；pending 或 rejected 时为空
    output: dict[str, Any] | None = None
    # HITL 暂停
    pending: bool = False
    approval_type: str | None = None
    approval_prompt: str | None = None
    preview_payload: dict[str, Any] | None = None
    # 驳回
    rejected: bool = False
    rejected_reason: str | None = None
    # 审批历史（供调用方展示）
    approval_history: list[dict[str, Any]] = Field(default_factory=list)


TInput = TypeVar("TInput", bound=SkillInput)
TOutput = TypeVar("TOutput", bound=SkillOutput)


class Skill(ABC, Generic[TInput, TOutput]):
    """Skill 基类。子类须定义 name / description / input_schema / output_schema / build_graph。"""

    name: ClassVar[str]
    description: ClassVar[str]
    input_schema: ClassVar[Type[SkillInput]]
    output_schema: ClassVar[Type[SkillOutput]]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        required = ("name", "description", "input_schema", "output_schema")
        for attr in required:
            if attr not in cls.__dict__:
                # 允许不定义（抽象/中间类），但实例化时会失败
                pass

    @abstractmethod
    def build_graph(self) -> Any:
        """Return a compiled LangGraph subgraph (or any callable with .invoke/ainvoke)."""

    # ---- 对外调用 ----
    async def ainvoke(self, input_data: dict | SkillInput,
                       resume_approval: HITLApproval | None = None,
                       state_override: dict | None = None) -> SkillResult:
        """Execute the skill. Returns SkillResult (possibly pending for HITL).

        - `input_data`: 首次调用时传入 input 字典
        - `resume_approval`: 继续被暂停的 skill 时传入
        - `state_override`: 继续时从 checkpoint 恢复的状态快照
        """
        if not isinstance(input_data, SkillInput):
            input_data = self.input_schema.model_validate(input_data)

        # 初始 state
        state: dict[str, Any] = state_override or {}
        state.setdefault("_input", input_data.model_dump())
        state.setdefault("_approval_history", [])
        state.setdefault("_output", None)

        if resume_approval is not None:
            state["_approval_history"].append(resume_approval.model_dump())
            if not resume_approval.approved:
                return SkillResult(
                    skill_name=self.name,
                    rejected=True,
                    rejected_reason=resume_approval.reason or "审批驳回",
                    approval_history=state["_approval_history"],
                )
            state["_resume_from"] = resume_approval.approval_type

        graph = self.build_graph()
        try:
            final_state = await _ainvoke_any(graph, state)
        except HITLPending as p:
            return SkillResult(
                skill_name=self.name,
                pending=True,
                approval_type=p.approval_type,
                approval_prompt=p.prompt,
                preview_payload=p.preview_payload,
                approval_history=state.get("_approval_history", []),
            )
        except HITLRejected as r:
            return SkillResult(
                skill_name=self.name,
                rejected=True,
                rejected_reason=r.reason,
                approval_history=state.get("_approval_history", []),
            )

        output_dict = final_state.get("_output") or {}
        # 用 output_schema 校验一次，校验失败时降级为 success=False
        try:
            validated = self.output_schema.model_validate(output_dict)
            output_dict = validated.model_dump()
            success = True
        except Exception as exc:
            log.warning("skill_output_validation_failed", extra={
                "skill": self.name, "error": str(exc)})
            output_dict = {**output_dict, "success": False, "error": str(exc)}
            success = False

        return SkillResult(
            skill_name=self.name,
            output=output_dict,
            approval_history=final_state.get("_approval_history", []),
        )


async def _ainvoke_any(graph: Any, state: dict) -> dict:
    """Support both LangGraph compiled graphs and plain async callables."""
    if hasattr(graph, "ainvoke"):
        return await graph.ainvoke(state)
    if hasattr(graph, "invoke"):
        return graph.invoke(state)
    # plain async function
    return await graph(state)


# ---- Registry -----------------------------------------------------------

class SkillRegistry:
    _skills: ClassVar[dict[str, Type[Skill]]] = {}

    @classmethod
    def register(cls, skill_cls: Type[Skill]) -> Type[Skill]:
        if not hasattr(skill_cls, "name"):
            raise ValueError(f"{skill_cls.__name__} 缺少 name 属性")
        if skill_cls.name in cls._skills:
            log.warning("skill_re_registered", extra={"name": skill_cls.name})
        cls._skills[skill_cls.name] = skill_cls
        return skill_cls

    @classmethod
    def get(cls, name: str) -> Type[Skill] | None:
        return cls._skills.get(name)

    @classmethod
    def all(cls) -> dict[str, Type[Skill]]:
        return dict(cls._skills)

    @classmethod
    def describe_for_planner(cls) -> str:
        """生成主 agent planner prompt 用的 skill 描述块。"""
        lines: list[str] = []
        for name, sk in cls._skills.items():
            # 提取 input schema 的字段名 + 类型
            fields: list[str] = []
            for fname, finfo in sk.input_schema.model_fields.items():
                ftype = getattr(finfo.annotation, "__name__", str(finfo.annotation))
                fields.append(f"{fname}: {ftype}")
            lines.append(f"- **{name}** — {sk.description}")
            lines.append(f"  输入: {{{', '.join(fields)}}}")
        return "\n".join(lines)

    @classmethod
    def clear(cls) -> None:
        """For tests only."""
        cls._skills.clear()


def register_skill(skill_cls: Type[Skill]) -> Type[Skill]:
    """Decorator to register a skill class."""
    return SkillRegistry.register(skill_cls)
