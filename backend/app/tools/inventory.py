"""Material inventory query tool — JSON data-driven with haversine distance."""

import json
import math
from pathlib import Path

import structlog
from langchain_core.tools import tool

logger = structlog.get_logger()

_DATA_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "inventory.json"
_inventory_cache: dict | None = None


def _load_inventory() -> dict:
    global _inventory_cache
    if _inventory_cache is not None:
        return _inventory_cache
    try:
        _inventory_cache = json.loads(_DATA_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.error("inventory_load_failed", path=str(_DATA_FILE), error=str(exc))
        _inventory_cache = {"stations": [], "district_coordinates": {}}
    return _inventory_cache


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _resolve_coordinates(location: str, data: dict) -> tuple[float, float] | None:
    """Try to resolve a location string to (lat, lon) via district lookup."""
    coords = data.get("district_coordinates", {})
    for district, (lat, lon) in coords.items():
        if district in location:
            return (lat, lon)
    return None


@tool
def query_material_inventory(location: str, radius_km: float = 10.0) -> dict:
    """查询指定位置周边的抢险物资站点及库存情况。

    Args:
        location: 抢险现场位置，如 "成都市武侯区"
        radius_km: 搜索半径 (公里)，默认 10
    """
    data = _load_inventory()
    stations = data.get("stations", [])
    origin = _resolve_coordinates(location, data)

    results = []
    for station in stations:
        if origin:
            dist = _haversine_km(origin[0], origin[1], station["lat"], station["lon"])
            if dist > radius_km:
                continue
        else:
            dist = None

        results.append({
            "station_name": station["name"],
            "district": station["district"],
            "address": station["address"],
            "contact": station["contact"],
            "available_24h": station.get("available_24h", False),
            "distance_km": round(dist, 1) if dist is not None else None,
            "items": station["items"],
        })

    if origin:
        results.sort(key=lambda s: s["distance_km"] or 999)

    return {
        "query_location": location,
        "search_radius_km": radius_km,
        "matched_stations": len(results),
        "coordinate_resolved": origin is not None,
        "stations": results,
    }
