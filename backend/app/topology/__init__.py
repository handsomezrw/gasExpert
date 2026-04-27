"""Gas pipeline topology — domain models + graph operations.

作为 `valve_isolation` Skill 的专属依赖，也对 Phase 7 拓扑感知开放。

Phase 6 先用 NetworkX 做内存图；Phase 7 与 Web 地图深度集成后再换 Neo4j。
算法接口对 Skill 层是稳定的，底层存储切换不影响上层。
"""
from __future__ import annotations

from .schema import LeakPoint, Node, NodeType, Pipeline, Valve, ValveStatus
from .graph_store import TopologyGraph, load_demo_topology
from .min_cut import find_isolation_valves, IsolationPlan

__all__ = [
    "LeakPoint",
    "Node",
    "NodeType",
    "Pipeline",
    "Valve",
    "ValveStatus",
    "TopologyGraph",
    "load_demo_topology",
    "find_isolation_valves",
    "IsolationPlan",
]
