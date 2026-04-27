"""Topology domain models."""
from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


class NodeType(str, Enum):
    JUNCTION = "junction"       # 管道连接点
    VALVE = "valve"             # 阀门
    SOURCE = "source"           # 气源/调压站
    CONSUMER = "consumer"       # 用户入户点


class ValveStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    UNDER_MAINTENANCE = "maintenance"
    UNKNOWN = "unknown"


class Node(BaseModel):
    """通用节点（junction / source / consumer）。阀门有单独模型继承更多字段。"""
    id: str
    type: NodeType
    lng: float | None = None
    lat: float | None = None
    label: str | None = None


class Valve(Node):
    """阀门节点 — 关阀方案的关键对象。"""
    type: Literal[NodeType.VALVE] = NodeType.VALVE  # type: ignore[assignment]
    status: ValveStatus = ValveStatus.OPEN
    remote_controllable: bool = Field(False, description="是否支持 SCADA 远控")
    manual_access_desc: str | None = Field(None, description="手动操作说明（井盖位置等）")
    last_inspected_at: str | None = None


class Pipeline(BaseModel):
    """管段（无向边）。两个端点通过 node_ids 引用。"""
    id: str
    node_a: str
    node_b: str
    pressure_class: str = Field(description="低压 / 中压 / 高压 等")
    material: str | None = None
    diameter: str | None = Field(None, description="DN25 / De63 ...")
    length_m: float | None = None
    # 用户数，作为关阀影响评估
    downstream_users: int = 0
    # 状态
    is_active: bool = True


class LeakPoint(BaseModel):
    """泄漏点定位：落在某条管段的指定位置（0-1 表示管段上的相对位置）。"""
    pipeline_id: str
    position: float = Field(0.5, ge=0, le=1, description="沿管段相对位置 0=A 端, 1=B 端")
    severity: Literal["pinhole", "crack", "rupture"] = "crack"
    lng: float | None = None
    lat: float | None = None
