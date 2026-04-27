"""Mock Web Map server — FastAPI app serving demo topology data.

在没有真实 Web 地图系统时，启动此 mock server 提供拓扑/阀门/回写接口。
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

import structlog
from fastapi import FastAPI, Query
from pydantic import BaseModel

from app.topology import NodeType, ValveStatus, load_demo_topology

log = structlog.get_logger()

# ── In-memory "database" ─────────────────────────────────────────────

_overlay_store: list[dict] = []


# ── Pydantic models ──────────────────────────────────────────────────

class OverlayPushRequest(BaseModel):
    session_id: str
    layer_type: str
    title: str = ""
    geojson: dict = {}


class IncidentWebhookPayload(BaseModel):
    incident_id: str | None = None
    pipeline_id: str | None = None
    location: str | None = None
    pressure: float | None = None
    diameter: float | None = None
    leak_type: str | None = None
    severity: str | None = None
    timestamp: str | None = None


# ── Helpers ──────────────────────────────────────────────────────────

def _serialize_topo(topo, center: str = "", radius_km: float = 2.0) -> dict:
    """Serialize ``TopologyGraph`` to the JSON contract format."""
    nodes = []
    for nid, node in topo._nodes.items():  # noqa: SLF001
        entry: dict = {
            "id": nid,
            "type": node.type.value,
            "label": node.label or nid,
        }
        if node.lng is not None:
            entry["lng"] = node.lng
        if node.lat is not None:
            entry["lat"] = node.lat
        if hasattr(node, "status"):
            entry["status"] = node.status.value
        if hasattr(node, "remote_controllable"):
            entry["remote_controllable"] = node.remote_controllable
        if hasattr(node, "manual_access_desc"):
            entry["manual_access_desc"] = node.manual_access_desc
        nodes.append(entry)

    pipelines = []
    for pid, pipe in topo._pipelines.items():  # noqa: SLF001
        pipelines.append({
            "id": pid,
            "node_a": pipe.node_a,
            "node_b": pipe.node_b,
            "pressure_class": pipe.pressure_class,
            "material": pipe.material,
            "diameter": pipe.diameter,
            "length_m": pipe.length_m,
            "downstream_users": pipe.downstream_users,
            "is_active": pipe.is_active,
        })

    return {
        "nodes": nodes,
        "pipelines": pipelines,
        "center": center,
        "radius_km": radius_km,
    }


# ── App factory ──────────────────────────────────────────────────────

def create_mock_app() -> FastAPI:
    """Create the mock Web map FastAPI application."""
    app = FastAPI(title="Mock Web Map", version="0.1.0")

    topo = load_demo_topology()

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "service": "mock-web-map", "topology_nodes": len(topo._nodes)}  # noqa: SLF001

    @app.get("/api/topology/subgraph")
    async def topology_subgraph(
        center: str = Query("", description="中心位置"),
        radius: float = Query(2.0, description="搜索半径 (km)"),
    ):
        """返回拓扑子图（demo 模式下返回完整拓扑）"""
        data = _serialize_topo(topo, center=center, radius_km=radius)
        log.info("mock_topo_subgraph", center=center, radius=radius,
                 nodes=len(data["nodes"]))
        return data

    @app.get("/api/valves/status")
    async def valve_status(ids: str = Query("", description="逗号分隔的阀门 ID")):
        """查询阀门实时状态"""
        requested = [v.strip() for v in ids.split(",") if v.strip()]
        valves = []
        for v in topo.all_valves():
            if not requested or v.id in requested:
                valves.append({
                    "id": v.id,
                    "label": v.label or v.id,
                    "status": v.status.value,
                    "remote_controllable": v.remote_controllable,
                    "manual_access_desc": v.manual_access_desc,
                })
        return {
            "valves": valves,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }

    @app.post("/api/map/overlay")
    async def push_overlay(body: OverlayPushRequest):
        """接受地图图层回写"""
        layer_id = f"layer-{uuid.uuid4().hex[:8]}"
        record = {
            "layer_id": layer_id,
            "session_id": body.session_id,
            "layer_type": body.layer_type,
            "title": body.title,
            "feature_count": len(body.geojson.get("features", [])) if body.geojson else 0,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        _overlay_store.append(record)
        log.info("mock_overlay_pushed", layer_id=layer_id, **record)
        return {"status": "ok", "layer_id": layer_id, **record}

    @app.get("/api/map/overlays")
    async def list_overlays(session_id: str | None = Query(None)):
        """列出已回写的图层（供前端/调试使用）"""
        if session_id:
            items = [r for r in _overlay_store if r["session_id"] == session_id]
        else:
            items = list(_overlay_store)
        return {"overlays": items, "count": len(items)}

    @app.post("/api/incidents/webhook")
    async def incident_webhook(body: IncidentWebhookPayload):
        """失效上报推送 (Phase 8 stub)"""
        incident_id = body.incident_id or f"INC-{uuid.uuid4().hex[:8].upper()}"
        log.info("mock_incident_webhook", incident_id=incident_id)
        return {
            "status": "received",
            "incident_id": incident_id,
            "message": "事故已接收（mock）",
        }

    return app


# ── Standalone runner ────────────────────────────────────────────────

_mock_app = create_mock_app()


def run_mock_server(host: str = "0.0.0.0", port: int = 8099) -> None:
    """Run the mock server standalone (``python -m ...``)."""
    import uvicorn
    uvicorn.run(_mock_app, host=host, port=port)


app = _mock_app

if __name__ == "__main__":
    run_mock_server()
