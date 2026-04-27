"""Diffusion zone skill — LangGraph nodes.

Integrates existing weather + evacuation tools as internal nodes,
adds GIS overlay and GeoJSON output steps.
"""
from __future__ import annotations

import structlog
from langchain_core.tools import tool

logger = structlog.get_logger()

# ── Node 1: Fetch weather ───────────────────────────────────────────────

async def fetch_weather_node(state: dict) -> dict:
    """Pull real-time weather for the incident location."""
    inp = state.get("_input", {})
    location = inp.get("location", "")
    wind_speed_override = inp.get("wind_speed")

    from app.tools.weather import get_weather_info

    try:
        weather = await get_weather_info.ainvoke({"location": location})
    except Exception as exc:
        logger.warning("weather_fetch_failed", error=str(exc))
        weather = {"location": location, "weather": "未知", "temperature": 20,
                    "humidity": 50, "wind_direction": "未知", "wind_speed": 0,
                    "source": "获取失败，使用默认值"}

    # Allow override of wind_speed if provided in input
    if wind_speed_override is not None:
        weather["wind_speed"] = wind_speed_override
        weather["wind_override"] = True

    logger.info("weather_fetched", location=location, wind=weather.get("wind_speed"))
    return {"weather_data": weather}


# ── Node 2: Compute evacuation zones ────────────────────────────────────

def compute_evacuation_node(state: dict) -> dict:
    """Run the evacuation zone calculation using existing algorithm."""
    inp = state.get("_input", {})
    weather = state.get("weather_data", {})

    pressure = inp.get("pressure", 0.4)
    diameter = inp.get("diameter", 200)
    leak_type = inp.get("leak_type", "crack")
    wind_speed = weather.get("wind_speed", 0)
    is_indoor = inp.get("is_indoor", False)

    # Reuse the existing evacuation calculation directly
    from app.tools.evacuation import calculate_evacuation_zone

    result = calculate_evacuation_zone.invoke({
        "pressure": pressure,
        "diameter": diameter,
        "leak_type": leak_type,
        "wind_speed": wind_speed,
        "is_indoor": is_indoor,
    })

    logger.info("evacuation_computed",
                radius=result.get("radius_m"), risk=result.get("risk_level"))
    return {"evacuation_result": result}


# ── Node 3: Overlay GIS data ────────────────────────────────────────────

def overlay_gis_node(state: dict) -> dict:
    """Superimpose evacuation zone with critical facility data.

    Phase 7 will replace hardcoded fixtures with real GIS queries.
    """
    evac = state.get("evacuation_result", {})
    inp = state.get("_input", {})

    radius = evac.get("radius_m", 0)
    risk_level = evac.get("risk_level", "低危")

    # Mock critical facilities within the evacuation zone
    facilities = []
    if radius > 50:
        facilities = [
            {"type": "school", "name": "示例小学", "distance_m": round(radius * 0.6), "risk": risk_level},
            {"type": "hospital", "name": "示例医院", "distance_m": round(radius * 0.8), "risk": risk_level},
            {"type": "elderly", "name": "示例养老院", "distance_m": round(radius * 0.4), "risk": risk_level},
        ]

    gis = {
        "critical_facilities": facilities,
        "population_estimate": max(100, int(radius * 2.5)),
        "road_blocks": [
            {"road": f"泄漏点周边主要道路", "action": "临时管制"},
        ],
    }
    return {"gis_overlay": gis}


# ── Node 4: Generate tiered zones ───────────────────────────────────────

def generate_zones_node(state: dict) -> dict:
    """Create tiered evacuation zones (red/orange/yellow)."""
    evac = state.get("evacuation_result", {})
    gis = state.get("gis_overlay", {})
    weather = state.get("weather_data", {})

    base_radius = evac.get("radius_m", 100)
    risk_level = evac.get("risk_level", "低危")
    wind_dir = weather.get("wind_direction", "")

    # Build zones based on risk level and wind direction
    if risk_level == "高危":
        zones = [
            {"level": "red", "label": "核心警戒区", "radius_m": round(base_radius * 0.4),
             "color": "#FF0000", "description": "严禁任何人员进入"},
            {"level": "orange", "label": "中间警戒区", "radius_m": round(base_radius * 0.7),
             "color": "#FF8C00", "description": "只允许抢险人员进入"},
            {"level": "yellow", "label": "外围警戒区", "radius_m": round(base_radius),
             "color": "#FFD700", "description": "禁止无关人员进入"},
        ]
    elif risk_level == "中危":
        zones = [
            {"level": "orange", "label": "核心警戒区", "radius_m": round(base_radius * 0.5),
             "color": "#FF8C00", "description": "只允许抢险人员进入"},
            {"level": "yellow", "label": "外围警戒区", "radius_m": round(base_radius),
             "color": "#FFD700", "description": "禁止无关人员进入"},
        ]
    else:
        zones = [
            {"level": "yellow", "label": "警戒区", "radius_m": round(base_radius),
             "color": "#FFD700", "description": "设置警示标识"},
        ]

    # Add wind direction influence
    if wind_dir:
        for z in zones:
            z["upwind_radius"] = round(z["radius_m"] * 0.6)
            z["downwind_radius"] = round(z["radius_m"] * 1.4)
            z["wind_direction"] = wind_dir

    return {"zones_raw": zones}


# ── Node 5: Build GeoJSON output ────────────────────────────────────────

def output_geojson_node(state: dict) -> dict:
    """Wrap evacuation zones into GeoJSON FeatureCollection for map overlay."""
    zones = state.get("zones_raw", [])
    evac = state.get("evacuation_result", {})
    gis = state.get("gis_overlay", {})
    weather = state.get("weather_data", {})

    inp = state.get("_input", {})
    features = []

    center_lat = inp.get("leak_point_lat", 30.676)
    center_lng = inp.get("leak_point_lng", 104.065)

    for i, z in enumerate(zones):
        features.append({
            "type": "Feature",
            "properties": {
                "level": z["level"],
                "label": z["label"],
                "description": z["description"],
                "radius_m": z["radius_m"],
                "fill": z["color"],
                "fill-opacity": 0.2,
                "stroke": z["color"],
                "stroke-width": 2,
            },
            "geometry": {
                "type": "Point",
                "coordinates": [center_lng, center_lat],
            },
        })

    geojson = {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "model_used": "高斯烟羽模型（简化）",
            "risk_level": evac.get("risk_level", "低危"),
            "base_radius_m": evac.get("radius_m"),
            "wind_speed_kmh": weather.get("wind_speed"),
            "wind_direction": weather.get("wind_direction", ""),
            "critical_facilities": gis.get("critical_facilities", []),
            "population_estimate": gis.get("population_estimate", 0),
        },
    }

    output = {
        "success": True,
        "zones": zones,
        "model_used": "高斯烟羽模型（简化）",
        "confidence": evac.get("risk_level", "低危") if evac.get("risk_level") != "低危" else "中",
        "weather_used": {
            "location": weather.get("location", inp.get("location", "")),
            "temperature": weather.get("temperature"),
            "wind_speed": weather.get("wind_speed"),
            "wind_direction": weather.get("wind_direction", ""),
            "humidity": weather.get("humidity"),
            "source": weather.get("source", ""),
        },
        "geojson": geojson,
    }
    return {"_output": output}
