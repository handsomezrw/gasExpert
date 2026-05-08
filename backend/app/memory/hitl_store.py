"""HITL pending-approval store (Phase 6.5).

Tracks skills that are paused at HITL checkpoints, along with enough
state to resume them when the dispatcher approves or rejects.

Thread-safe for async access; data lives in-process (lost on restart —
acceptable for demo; Phase 9 can persist to DB).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.skills.base import HITLApproval, Skill
from app.skills import SkillRegistry

log = logging.getLogger(__name__)


@dataclass
class PendingApproval:
    session_id: str
    skill_name: str
    approval_type: str
    approval_prompt: str
    preview_payload: dict[str, Any]
    # For resume
    skill_cls_name: str
    input_args: dict[str, Any]
    partial_state: dict[str, Any]
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class HITLStore:
    """In-memory store for pending HITL approvals."""

    def __init__(self) -> None:
        self._pending: dict[str, PendingApproval] = {}  # session_id → PendingApproval
        self._lock = asyncio.Lock()

    async def set_pending(self, session_id: str, pa: PendingApproval) -> None:
        async with self._lock:
            self._pending[session_id] = pa
            log.info("hitl_pending_stored", session_id=session_id,
                     skill=pa.skill_name, approval_type=pa.approval_type)

    async def get_pending(self, session_id: str) -> PendingApproval | None:
        async with self._lock:
            return self._pending.get(session_id)

    async def remove_pending(self, session_id: str) -> PendingApproval | None:
        async with self._lock:
            return self._pending.pop(session_id, None)

    async def has_pending(self, session_id: str) -> bool:
        async with self._lock:
            return session_id in self._pending

    async def resume_with(
        self, session_id: str, approved: bool, reason: str | None = None
    ) -> dict[str, Any] | None:
        """Resume a pending skill with the given approval decision.

        Returns the final SkillResult.model_dump() on success, or None
        if no pending approval was found.
        """
        pa = await self.remove_pending(session_id)
        if pa is None:
            return None

        if not approved:
            log.info("hitl_rejected", session_id=session_id, reason=reason)
            from app.skills.base import SkillResult
            return SkillResult(
                skill_name=pa.skill_name,
                rejected=True,
                rejected_reason=reason or "审批驳回",
            ).model_dump()

        # Resume the skill with approval
        skill_cls = SkillRegistry.get(pa.skill_cls_name)
        if skill_cls is None:
            log.error("hitl_resume_skill_not_found", name=pa.skill_cls_name)
            return None

        skill: Skill = skill_cls()
        approval = HITLApproval(
            approved=True,
            approval_type=pa.approval_type,
            reason=reason,
        )

        try:
            result = await skill.ainvoke(
                pa.input_args,
                resume_approval=approval,
                state_override=pa.partial_state,
            )
            log.info("hitl_resumed", session_id=session_id, skill=pa.skill_name,
                     pending=result.pending, rejected=result.rejected)
            return result.model_dump()
        except Exception as exc:
            log.error("hitl_resume_failed", session_id=session_id,
                      skill=pa.skill_name, error=str(exc))
            return None

    @property
    def pending_count(self) -> int:
        return len(self._pending)


# Module-level singleton
_hitl_store: HITLStore | None = None


def get_hitl_store() -> HITLStore:
    global _hitl_store
    if _hitl_store is None:
        _hitl_store = HITLStore()
    return _hitl_store
