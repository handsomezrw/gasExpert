"""Diffusion zone skill — LangGraph subgraph definition.

DAG (5 nodes):
    fetch_weather → compute_evacuation → overlay_gis → generate_zones → output_geojson → END
"""
from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.skills.diffusion_zone.nodes import (
    compute_evacuation_node,
    fetch_weather_node,
    generate_zones_node,
    output_geojson_node,
    overlay_gis_node,
)
from app.skills.diffusion_zone.state import DiffusionZoneState


def _skip_on_weather_fail(state: dict) -> str:
    """If weather fetch failed but we have manual data, continue anyway."""
    inp = state.get("_input", {})
    if state.get("weather_data") is None and not inp.get("wind_speed"):
        return "skip_weather"
    return "continue"


def build_diffusion_zone_graph():
    """Build and return the compiled diffusion zone subgraph."""
    builder = StateGraph(DiffusionZoneState)

    # fetch_weather is async; others are sync
    builder.add_node("fetch_weather", fetch_weather_node)
    builder.add_node("compute_evacuation", compute_evacuation_node)
    builder.add_node("overlay_gis", overlay_gis_node)
    builder.add_node("generate_zones", generate_zones_node)
    builder.add_node("output_geojson", output_geojson_node)

    builder.set_entry_point("fetch_weather")

    builder.add_conditional_edges("fetch_weather", _skip_on_weather_fail, {
        "continue": "compute_evacuation",
        "skip_weather": "compute_evacuation",
    })
    builder.add_edge("compute_evacuation", "overlay_gis")
    builder.add_edge("overlay_gis", "generate_zones")
    builder.add_edge("generate_zones", "output_geojson")
    builder.add_edge("output_geojson", END)

    return builder.compile()


diffusion_zone_graph = build_diffusion_zone_graph()
__all__ = ["diffusion_zone_graph", "build_diffusion_zone_graph"]
