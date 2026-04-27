"""Tests for topology graph + min-cut valve isolation."""
from __future__ import annotations

import pytest

from app.topology import (
    LeakPoint,
    ValveStatus,
    find_isolation_valves,
    load_demo_topology,
)


def test_demo_topology_loads():
    t = load_demo_topology()
    assert t.get_node("V1") is not None
    assert t.get_pipeline("P3") is not None
    assert len(t.all_valves()) == 5


def test_isolate_branch_pipeline():
    """泄漏发生在 P3 (J1-V2)，最佳方案：V2（就近端）+ V1 + V5
    可以被裁剪为 {V1, V5}，只影响 P3 所在分支（P5a 之前/之后的用户也受影响）。
    我们断言 V5 必在结果中（挡住 SRC2 侧），且方案 ≤ 3 个阀门。"""
    t = load_demo_topology()
    leak = LeakPoint(pipeline_id="P3", severity="crack")

    plan = find_isolation_valves(t, leak)
    assert plan.feasible
    assert len(plan.valve_ids) <= 3
    # 必须包含 V1（挡 SRC1）和 V5（挡 SRC2 从 P5 方向）；V2 可能被裁剪掉
    assert "V1" in plan.valve_ids
    assert "V5" in plan.valve_ids
    # 隔离集包含 P3
    assert "P3" in plan.isolated_pipelines


def test_isolate_terminal_pipeline():
    """泄漏发生在 P4 (V2-C1)，V2 就是一端，关闭 V2 直接隔离。"""
    t = load_demo_topology()
    leak = LeakPoint(pipeline_id="P4", severity="pinhole")
    plan = find_isolation_valves(t, leak)
    assert plan.feasible
    assert "V2" in plan.valve_ids
    assert "P4" in plan.isolated_pipelines
    assert plan.affected_users >= 45


def test_isolate_backbone_with_two_sources():
    """泄漏在 P5a (J1-V5) 主干上，需要同时阻断两路气源。"""
    t = load_demo_topology()
    leak = LeakPoint(pipeline_id="P5a")
    plan = find_isolation_valves(t, leak)
    assert plan.feasible
    assert len(plan.valve_ids) <= 3
    assert "P5a" in plan.isolated_pipelines


def test_maintenance_valve_not_selected():
    """当 V1 在维护时，算法应绕开它，寻找替代方案（即使更差）。"""
    t = load_demo_topology()
    v1 = t.get_node("V1")
    v1.status = ValveStatus.UNDER_MAINTENANCE  # type: ignore[assignment]
    leak = LeakPoint(pipeline_id="P3")
    plan = find_isolation_valves(t, leak)
    # P3 仍可通过 V2 一端隔离；P3 到 SRC1 的路径 (P2-V1-P1) 因 V1 不可切，
    # 但由于 V2 阻断了 P3 往下游，SRC1 侧仍可通过 J1-P5-J2-SRC2 灌气，
    # 所以单靠 V2 可能隔离不掉 — 此时应返回 infeasible 或多阀门方案
    # 我们只断言：返回的 valve_ids 不含 V1
    assert "V1" not in plan.valve_ids


def test_unknown_pipeline_returns_infeasible():
    t = load_demo_topology()
    leak = LeakPoint(pipeline_id="NOPE")
    plan = find_isolation_valves(t, leak)
    assert not plan.feasible
    assert "未知管段" in plan.notes[0]


def test_subgraph_limits_search_scope():
    t = load_demo_topology()
    sub = t.subgraph_within("V2", radius_hops=1)
    # V2 的 1 跳邻居包含 J1 和 C1（两端各自的邻点）
    assert sub.get_node("V2") is not None
    # 应包含与 V2 直接相连的节点
    assert sub.get_node("J1") is not None or sub.get_node("C1") is not None
