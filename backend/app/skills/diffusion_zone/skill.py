"""DiffusionZoneSkill — registered skill class."""
from app.skills import register_skill
from app.skills.base import Skill
from app.skills.diffusion_zone.graph import diffusion_zone_graph
from app.skills.diffusion_zone.state import DiffusionZoneInput, DiffusionZoneOutput


@register_skill
class DiffusionZoneSkill(Skill):
    name = "diffusion_zone"
    description = "计算泄漏扩散范围与疏散圈，产出 GeoJSON 地图覆盖层（集成气象+GIS）"
    input_schema = DiffusionZoneInput
    output_schema = DiffusionZoneOutput

    def build_graph(self):
        return diffusion_zone_graph
