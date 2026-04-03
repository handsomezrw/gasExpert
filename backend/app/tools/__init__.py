"""Tool registry — central catalog of all agent tools."""

from app.tools.evacuation import calculate_evacuation_zone
from app.tools.gas_expert import consult_gas_expert
from app.tools.inventory import query_material_inventory
from app.tools.report import generate_report
from app.tools.weather import get_weather_info

ALL_TOOLS = [
    get_weather_info,
    calculate_evacuation_zone,
    query_material_inventory,
    consult_gas_expert,
    generate_report,
]

TOOL_MAP: dict = {tool.name: tool for tool in ALL_TOOLS}


def get_tool_descriptions() -> str:
    """Generate human-readable tool descriptions for the planner prompt."""
    lines = []
    for t in ALL_TOOLS:
        lines.append(f"- **{t.name}**: {t.description}")
    return "\n".join(lines)
