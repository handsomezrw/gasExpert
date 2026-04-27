"""REST client for the external Web Map system.

契约接口（均为 Web 地图端暴露，Copilot 侧调用）：
  GET  /api/topology/subgraph    — 拉取事故点周边拓扑子图
  GET  /api/valves/status        — 查询阀门实时状态
  POST /api/map/overlay          — 把关阀/扩散 GeoJSON 写回地图
  POST /api/incidents/webhook    — 失效上报推送 (Phase 8)
  WS   /api/events               — 实时事件同步 (Phase 8)

构造时传入 base_url；若不传则自动探测 mock server。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx

log = logging.getLogger(__name__)


@dataclass
class TopologySubgraph:
    """Deserialized topology subgraph from the Web system."""
    nodes: list[dict]
    pipelines: list[dict]
    center: str | None = None
    radius_km: float | None = None

    def to_geojson(self) -> dict:
        """Convert to GeoJSON FeatureCollection for map overlay rendering."""
        features: list[dict] = []
        for n in self.nodes:
            if n.get("lng") is not None and n.get("lat") is not None:
                features.append({
                    "type": "Feature",
                    "properties": {"id": n["id"], "type": n.get("type", ""),
                                    "label": n.get("label", n["id"])},
                    "geometry": {"type": "Point", "coordinates": [n["lng"], n["lat"]]},
                })
        for p in self.pipelines:
            # Find endpoint coordinates for line geometry
            coords = []
            for pid in (p.get("node_a"), p.get("node_b")):
                for n in self.nodes:
                    if n["id"] == pid and n.get("lng") is not None:
                        coords.append([n["lng"], n["lat"]])
            if len(coords) == 2:
                features.append({
                    "type": "Feature",
                    "properties": {"id": p["id"], "type": "pipeline",
                                    "pressure_class": p.get("pressure_class", "")},
                    "geometry": {"type": "LineString", "coordinates": coords},
                })
        return {"type": "FeatureCollection", "features": features}


@dataclass
class ValveStatusResult:
    """Result of a valve status query."""
    valves: list[dict]
    timestamp: str = ""


class WebMapClient:
    """HTTP client for the external Web Map system APIs.

    If ``base_url`` is None, the client falls back to a hard-coded
    local mock server URL (``http://localhost:8099``).
    """

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or "http://localhost:8099").rstrip("/")
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self.base_url, timeout=15.0)
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    # ── Topology subgraph ────────────────────────────────────────────

    async def fetch_topology_subgraph(
        self, center: str = "", radius_km: float = 2.0
    ) -> TopologySubgraph:
        """``GET /api/topology/subgraph?center=&radius=``

        Returns the pipeline topology around *center* within *radius_km*.
        """
        client = await self._get_client()
        resp = await client.get("/api/topology/subgraph", params={
            "center": center,
            "radius": radius_km,
        })
        resp.raise_for_status()
        data = resp.json()
        return TopologySubgraph(
            nodes=data.get("nodes", []),
            pipelines=data.get("pipelines", []),
            center=center,
            radius_km=radius_km,
        )

    # ── Valve status ─────────────────────────────────────────────────

    async def fetch_valve_statuses(self, valve_ids: list[str]) -> ValveStatusResult:
        """``GET /api/valves/status?ids=id1,id2,...``"""
        client = await self._get_client()
        resp = await client.get("/api/valves/status", params={
            "ids": ",".join(valve_ids),
        })
        resp.raise_for_status()
        data = resp.json()
        return ValveStatusResult(
            valves=data.get("valves", []),
            timestamp=data.get("timestamp", ""),
        )

    # ── Map overlay push ─────────────────────────────────────────────

    async def push_overlay(
        self,
        session_id: str,
        geojson: dict,
        layer_type: str,
        title: str = "",
    ) -> dict:
        """``POST /api/map/overlay``

        Push a GeoJSON FeatureCollection to the Web map as a new layer.
        Returns the server's response (e.g. ``{"status": "ok", "layer_id": "..."}``).
        """
        client = await self._get_client()
        payload = {
            "session_id": session_id,
            "layer_type": layer_type,
            "title": title or layer_type,
            "geojson": geojson,
        }
        resp = await client.post("/api/map/overlay", json=payload)
        resp.raise_for_status()
        result = resp.json()
        log.info("overlay_pushed", layer_type=layer_type, response=result)
        return result

    # ── Incident webhook (Phase 8 stub) ──────────────────────────────

    async def push_incident_webhook(self, payload: dict) -> dict:
        """``POST /api/incidents/webhook`` (stub — Phase 8)"""
        client = await self._get_client()
        resp = await client.post("/api/incidents/webhook", json=payload)
        resp.raise_for_status()
        return resp.json()
