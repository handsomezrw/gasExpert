"""In-memory pipeline topology store backed by NetworkX.

- 节点：junction / valve / source / consumer
- 边：pipeline（带 pressure_class / diameter / downstream_users 等属性）
- 查询：邻居、子图、按圆心距离筛选

Phase 7 接入真实 Web 地图后，换成从远端 API 加载，接口保持不变。
"""
from __future__ import annotations

import math
from typing import Iterable

import networkx as nx

from .schema import LeakPoint, Node, NodeType, Pipeline, Valve, ValveStatus


class TopologyGraph:
    """轻量包装：对外暴露"按泄漏点查子图 / 列阀门 / 划分上下游"等原语。"""

    def __init__(self) -> None:
        self._g: nx.Graph = nx.Graph()
        self._nodes: dict[str, Node] = {}
        self._pipelines: dict[str, Pipeline] = {}
        self._pipeline_aliases: dict[str, str] = {}  # alias → canonical id

    # ---- 构建 ----
    def add_node(self, node: Node) -> None:
        self._nodes[node.id] = node
        self._g.add_node(node.id, data=node)

    def add_pipeline(self, pipe: Pipeline) -> None:
        if pipe.node_a not in self._nodes or pipe.node_b not in self._nodes:
            raise ValueError(f"pipeline {pipe.id} 的端点未注册")
        self._pipelines[pipe.id] = pipe
        self._g.add_edge(pipe.node_a, pipe.node_b, data=pipe, key=pipe.id)

    # ---- 查询 ----
    def get_node(self, node_id: str) -> Node | None:
        return self._nodes.get(node_id)

    def get_pipeline(self, pipeline_id: str) -> Pipeline | None:
        # Try exact match first, then alias lookup
        if pipeline_id in self._pipelines:
            return self._pipelines[pipeline_id]
        canonical = self._pipeline_aliases.get(pipeline_id)
        if canonical:
            return self._pipelines.get(canonical)
        # Case-insensitive fallback
        upper = pipeline_id.upper()
        if upper in self._pipelines:
            return self._pipelines[upper]
        canonical = self._pipeline_aliases.get(upper)
        if canonical:
            return self._pipelines.get(canonical)
        return None

    @property
    def graph(self) -> nx.Graph:
        return self._g

    def all_valves(self) -> list[Valve]:
        return [n for n in self._nodes.values() if isinstance(n, Valve)]

    def operable_valves(self) -> list[Valve]:
        return [v for v in self.all_valves()
                if v.status in (ValveStatus.OPEN, ValveStatus.CLOSED)]

    def subgraph_within(self, center_node_id: str, radius_hops: int = 3) -> "TopologyGraph":
        """以指定节点为中心、BFS radius_hops 跳的子图（阀门隔离前的搜索域）。"""
        if center_node_id not in self._g:
            raise ValueError(f"节点 {center_node_id} 不在拓扑中")
        reachable = nx.single_source_shortest_path_length(
            self._g, center_node_id, cutoff=radius_hops
        )
        return self._materialize_subgraph(reachable.keys())

    def _materialize_subgraph(self, node_ids: Iterable[str]) -> "TopologyGraph":
        ids = set(node_ids)
        out = TopologyGraph()
        for nid in ids:
            out.add_node(self._nodes[nid])
        for pid, pipe in self._pipelines.items():
            if pipe.node_a in ids and pipe.node_b in ids:
                out.add_pipeline(pipe)
        return out

    def count_downstream_users(self, pipeline_ids: Iterable[str]) -> int:
        return sum(self._pipelines[p].downstream_users
                   for p in pipeline_ids if p in self._pipelines)

    # ---- 几何 ----
    @staticmethod
    def _haversine_m(a: Node, b: Node) -> float:
        if None in (a.lng, a.lat, b.lng, b.lat):
            return math.inf
        lng1, lat1, lng2, lat2 = map(math.radians, [a.lng, a.lat, b.lng, b.lat])  # type: ignore[arg-type]
        dlng = lng2 - lng1
        dlat = lat2 - lat1
        h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
        return 2 * 6_371_000 * math.asin(math.sqrt(h))


# ---- Demo / fixture topology -------------------------------------------

def load_demo_topology() -> TopologyGraph:
    """构造一个用于开发与测试的小拓扑。

    形状：两个气源 → 主管 → 分支 → 用户；若干阀门穿插其间。

        SRC1 ─[P1]─ V1 ─[P2]─ J1 ─[P3]─ V2 ─[P4]─ C1
                                │
                               [P5a]
                                │
                                V5
                                │
                               [P5b]
                                │
                                J2 ─[P6]─ V3 ─[P7]─ C2
                                │
                               [P8a]
                                │
                                V4
                                │
                               [P8b]
                                │
                                SRC2
    """
    t = TopologyGraph()

    # sources / junctions / consumers
    t.add_node(Node(id="SRC1", type=NodeType.SOURCE, lng=104.060, lat=30.680, label="调压站 A"))
    t.add_node(Node(id="SRC2", type=NodeType.SOURCE, lng=104.070, lat=30.670, label="调压站 B"))
    t.add_node(Node(id="J1",   type=NodeType.JUNCTION, lng=104.065, lat=30.676))
    t.add_node(Node(id="J2",   type=NodeType.JUNCTION, lng=104.067, lat=30.673))
    t.add_node(Node(id="C1",   type=NodeType.CONSUMER, lng=104.069, lat=30.677, label="用户组 1"))
    t.add_node(Node(id="C2",   type=NodeType.CONSUMER, lng=104.069, lat=30.671, label="用户组 2"))

    # valves
    t.add_node(Valve(id="V1", lng=104.062, lat=30.678, label="V1 主阀",
                     status=ValveStatus.OPEN, remote_controllable=True))
    t.add_node(Valve(id="V2", lng=104.067, lat=30.676, label="V2 分支阀",
                     status=ValveStatus.OPEN, remote_controllable=False,
                     manual_access_desc="井盖在学校门口"))
    t.add_node(Valve(id="V3", lng=104.068, lat=30.672, label="V3 分支阀",
                     status=ValveStatus.OPEN, remote_controllable=True))
    t.add_node(Valve(id="V4", lng=104.068, lat=30.670, label="V4 SRC2 侧主阀",
                     status=ValveStatus.OPEN, remote_controllable=True))
    t.add_node(Valve(id="V5", lng=104.066, lat=30.674, label="V5 主干阀",
                     status=ValveStatus.OPEN, remote_controllable=True))

    # pipelines — also expose human-friendly aliases for LLM-generated IDs
    t.add_pipeline(Pipeline(id="P1", node_a="SRC1", node_b="V1", pressure_class="中压",
                            material="PE管", diameter="De110", length_m=180,
                            downstream_users=120))
    t.add_pipeline(Pipeline(id="P2", node_a="V1", node_b="J1", pressure_class="中压",
                            material="PE管", diameter="De110", length_m=210,
                            downstream_users=120))
    t.add_pipeline(Pipeline(id="P3", node_a="J1", node_b="V2", pressure_class="中压",
                            material="PE管", diameter="De90", length_m=90,
                            downstream_users=45))
    t.add_pipeline(Pipeline(id="P4", node_a="V2", node_b="C1", pressure_class="低压",
                            material="PE管", diameter="De63", length_m=110,
                            downstream_users=45))
    t.add_pipeline(Pipeline(id="P5a", node_a="J1", node_b="V5", pressure_class="中压",
                            material="钢管", diameter="DN100", length_m=70,
                            downstream_users=75))
    t.add_pipeline(Pipeline(id="P5b", node_a="V5", node_b="J2", pressure_class="中压",
                            material="钢管", diameter="DN100", length_m=70,
                            downstream_users=75))
    t.add_pipeline(Pipeline(id="P6", node_a="J2", node_b="V3", pressure_class="中压",
                            material="钢管", diameter="DN80", length_m=95,
                            downstream_users=75))
    t.add_pipeline(Pipeline(id="P7", node_a="V3", node_b="C2", pressure_class="低压",
                            material="PE管", diameter="De63", length_m=120,
                            downstream_users=75))
    t.add_pipeline(Pipeline(id="P8a", node_a="J2", node_b="V4", pressure_class="中压",
                            material="钢管", diameter="DN100", length_m=80,
                            downstream_users=0))
    t.add_pipeline(Pipeline(id="P8b", node_a="V4", node_b="SRC2", pressure_class="中压",
                            material="钢管", diameter="DN100", length_m=80,
                            downstream_users=0))

    # Aliases for LLM-generated pipeline IDs (map to canonical demo IDs)
    t._pipeline_aliases["ZG-001"] = "P3"   # 新都花园支线
    t._pipeline_aliases["P001"] = "P1"     # LLM 补零变体
    t._pipeline_aliases["P002"] = "P2"
    t._pipeline_aliases["P003"] = "P3"
    t._pipeline_aliases["P004"] = "P4"
    return t
