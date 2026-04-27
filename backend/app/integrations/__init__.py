"""Web Map Integration — client + mock server + cache + overlay push.

与现有 Web 地图系统的集成契约（详见 PLAN.md 6.2）：
  GET  /api/topology/subgraph  拉取拓扑子图
  GET  /api/valves/status      查询阀门状态
  POST /api/map/overlay        回写地图图层 (GeoJSON)
  POST /api/incidents/webhook  失效上报推送 (Phase 8)
  WS   /api/events             实时事件同步 (Phase 8)

前期 Mock Server 兜底，Phase 7 切到真实 Web 地图。
"""
from __future__ import annotations

from .web_map.client import WebMapClient
from .web_map.cache import TopologyCache, topo_cache
from .web_map import create_mock_app, run_mock_server

__all__ = [
    "WebMapClient",
    "create_mock_app",
    "run_mock_server",
    "TopologyCache",
    "topo_cache",
]
