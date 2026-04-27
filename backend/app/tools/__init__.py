"""Tool registry — central catalog of all agent tools.

In Phase 6.1, evacuation and report-generation have been promoted to Skills.
The remaining tools are atomic, stateless utilities that Skills also consume internally.
"""
from app.tools.gas_expert import consult_gas_expert
from app.tools.inventory import query_material_inventory
from app.tools.weather import get_weather_info

# Only atomic, stateless tools remain in the registry.
# calculate_evacuation_zone → now part of diffusion_zone Skill
# generate_report          → now part of repair_plan Skill
ALL_TOOLS = [
    get_weather_info,
    query_material_inventory,
    consult_gas_expert,
]

TOOL_MAP: dict = {tool.name: tool for tool in ALL_TOOLS}


def get_tool_descriptions() -> str:
    """Generate human-readable tool descriptions for the planner prompt."""
    lines = []
    for t in ALL_TOOLS:
        lines.append(f"- **{t.name}**: {t.description}")
    return "\n".join(lines)
