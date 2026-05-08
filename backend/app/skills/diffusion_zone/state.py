"""Diffusion zone skill — state & I/O schemas."""
from __future__ import annotations

from typing import Literal, TypedDict

from pydantic import Field, field_validator

from app.skills.base import SkillInput, SkillOutput

# Canonical leak type values — LLM-generated aliases are mapped via validator
_LEAK_TYPE_VALUES = {"pinhole", "crack", "rupture"}

_LEAK_ALIASES: dict[str, str] = {
    # pinhole
    "hole": "pinhole", "small": "pinhole", "tiny": "pinhole",
    "pin_hole": "pinhole", "针孔": "pinhole",
    # crack
    "cracked": "crack", "moderate": "crack", "medium": "crack",
    "mid": "crack", "裂缝": "crack",
    # rupture
    "burst": "rupture", "large": "rupture", "big": "rupture",
    "major": "rupture", "破裂": "rupture",
}


class DiffusionZoneInput(SkillInput):
    """Skill input: leak parameters + environmental context."""
    location: str = Field(description="事故发生位置")
    pressure: float = Field(description="管道压力 (MPa)")
    diameter: float = Field(description="管道直径 (mm)")
    leak_type: str = Field(description="泄漏类型: pinhole / crack / rupture")
    is_indoor: bool = Field(False, description="是否为室内泄漏")
    wind_speed: float | None = Field(None, description="已知风速 (km/h)，不提供则自动拉取")
    leak_point_lat: float | None = Field(None, description="泄漏点纬度")
    leak_point_lng: float | None = Field(None, description="泄漏点经度")
    timestamp: str | None = Field(None, description="事故时间")

    @field_validator("leak_type", mode="before")
    @classmethod
    def _normalize_leak_type(cls, v: str) -> str:
        v = str(v).strip().lower()
        if v in _LEAK_TYPE_VALUES:
            return v
        if v in _LEAK_ALIASES:
            return _LEAK_ALIASES[v]
        # Fuzzy match: if v contains any canonical value, use it
        for canonical in _LEAK_TYPE_VALUES:
            if canonical in v:
                return canonical
        # Default fallback
        return "crack"


class DiffusionZoneOutput(SkillOutput):
    """Skill output: tiered evacuation zones + GeoJSON overlay."""
    zones: list[dict] = Field(default_factory=list, description="分级疏散圈")
    model_used: str = Field(description="扩散模型名称")
    confidence: str = Field("中", description="置信度: 高/中/低")
    weather_used: dict = Field(default_factory=dict, description="所用气象数据")
    geojson: dict = Field(default_factory=dict, description="地图叠加 GeoJSON")


class DiffusionZoneState(TypedDict, total=False):
    """Internal LangGraph state (TypedDict — all fields optional)."""
    _input: dict
    _output: dict | None
    _approval_history: list
    weather_data: dict | None
    evacuation_result: dict | None
    gis_overlay: dict | None
    zones_raw: list
