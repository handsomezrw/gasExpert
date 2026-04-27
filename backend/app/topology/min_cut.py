"""Valve isolation algorithm — greedy BFS outward from the leak.

设计取舍（与 PLAN 6.1.2 一致）：
    NetworkX 纯 min-cut 会返回多个可行最小割中"任意一个"，
    常出现选了远端主阀（造成巨大爆破半径）而不是就近阀门的情况。
    本算法以**就近原则 + 最小阀门数**为目标：

    1. 列出"管段邻接阀门"候选 — 从泄漏管段两端 BFS，把先遇到的操作阀门排在前面
    2. 贪心：逐个关闭最近的可操作阀门，检查是否已把所有气源与泄漏点断开
    3. 所有气源都不可达泄漏点时停止
    4. 返回累积的阀门集 + 被隔离管段 + 影响用户数

备注：
    - 维护中的阀门被自动跳过
    - 无解情况返回 `feasible=False`，上层决定是否升级（扩大搜索半径）
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Iterable

import networkx as nx

from .graph_store import TopologyGraph
from .schema import LeakPoint, NodeType, Valve, ValveStatus


@dataclass
class IsolationPlan:
    feasible: bool
    valve_ids: list[str]
    isolated_pipelines: list[str]
    affected_users: int
    notes: list[str]

    def to_dict(self) -> dict:
        return {
            "feasible": self.feasible,
            "valve_ids": list(self.valve_ids),
            "isolated_pipelines": list(self.isolated_pipelines),
            "affected_users": self.affected_users,
            "notes": list(self.notes),
        }


def _operable(node: Valve) -> bool:
    return node.status != ValveStatus.UNDER_MAINTENANCE


def _sources_still_reach_leak(topo: TopologyGraph, closed: set[str],
                               leak_endpoints: set[str]) -> bool:
    g = topo.graph.copy()
    for v in closed:
        if v in g:
            g.remove_node(v)
    sources = [nid for nid, n in topo._nodes.items()  # noqa: SLF001
               if n.type == NodeType.SOURCE and nid not in closed]
    for src in sources:
        if src not in g:
            continue
        comp = nx.node_connected_component(g, src)
        # A source isolated to itself doesn't reach the leak
        # (edge case: source IS a leak endpoint, e.g. P1 leak at SRC1)
        if comp == {src}:
            continue
        if comp & leak_endpoints:
            return True
    return False


def _ordered_valve_candidates(topo: TopologyGraph, leak_endpoints: set[str]) -> list[str]:
    """BFS from leak endpoints; return valves in distance order (nearest first)."""
    g = topo.graph
    visited: set[str] = set(leak_endpoints)
    q: deque[tuple[str, int]] = deque([(e, 0) for e in leak_endpoints])
    ordered: list[tuple[int, str]] = []
    while q:
        node, dist = q.popleft()
        n = topo.get_node(node)
        if n is None:
            continue
        if isinstance(n, Valve) and _operable(n):
            ordered.append((dist, node))
        for nbr in g.neighbors(node):
            if nbr not in visited:
                visited.add(nbr)
                q.append((nbr, dist + 1))
    ordered.sort()
    return [vid for _, vid in ordered]


def find_isolation_valves(topo: TopologyGraph, leak: LeakPoint) -> IsolationPlan:
    pipe = topo.get_pipeline(leak.pipeline_id)
    if pipe is None:
        return IsolationPlan(
            feasible=False, valve_ids=[], isolated_pipelines=[],
            affected_users=0, notes=[f"未知管段 {leak.pipeline_id}"]
        )

    leak_endpoints = {pipe.node_a, pipe.node_b}
    candidates = _ordered_valve_candidates(topo, leak_endpoints)

    # 初始：假设还没关任何阀门；若气源就已经不可达（罕见），直接返回空方案
    if not _sources_still_reach_leak(topo, closed=set(), leak_endpoints=leak_endpoints):
        isolated = _isolated_pipelines(topo, closed=[])
        return IsolationPlan(
            feasible=True, valve_ids=[], isolated_pipelines=isolated,
            affected_users=topo.count_downstream_users(isolated),
            notes=["泄漏点与所有气源已无连通路径，无需关阀"],
        )

    # 贪心：依次关最近的可操作阀门
    closed: list[str] = []
    notes: list[str] = []
    for vid in candidates:
        closed.append(vid)
        if not _sources_still_reach_leak(topo, set(closed), leak_endpoints):
            break
    else:
        # 所有候选阀门都关完仍有气源到达
        return IsolationPlan(
            feasible=False, valve_ids=closed, isolated_pipelines=[],
            affected_users=0,
            notes=["即使关闭所有可操作阀门，气源仍可到达泄漏点；建议升级处置（扩大范围或启用维护中阀门）"]
        )

    # 尝试"减枝"：从已选阀门里逐个尝试移除，只要仍然隔离就移除
    final: list[str] = list(closed)
    for vid in list(closed):
        trial = [v for v in final if v != vid]
        if not _sources_still_reach_leak(topo, set(trial), leak_endpoints):
            final = trial
    final.sort()

    isolated = _isolated_pipelines(topo, closed=final)
    return IsolationPlan(
        feasible=True,
        valve_ids=final,
        isolated_pipelines=isolated,
        affected_users=topo.count_downstream_users(isolated),
        notes=notes,
    )


def _isolated_pipelines(topo: TopologyGraph, closed: Iterable[str]) -> list[str]:
    closed_set = set(closed)
    g = topo.graph.copy()
    for v in closed_set:
        if v in g:
            g.remove_node(v)
    sources = [nid for nid, n in topo._nodes.items()  # noqa: SLF001
               if n.type == NodeType.SOURCE and nid not in closed_set]
    reachable_nodes: set[str] = set()
    for src in sources:
        if src in g:
            reachable_nodes.update(nx.node_connected_component(g, src))

    isolated: list[str] = []
    for pid, pipe in topo._pipelines.items():  # noqa: SLF001
        if pipe.node_a in closed_set or pipe.node_b in closed_set:
            isolated.append(pid)
            continue
        if pipe.node_a not in reachable_nodes or pipe.node_b not in reachable_nodes:
            isolated.append(pid)
    return sorted(isolated)
