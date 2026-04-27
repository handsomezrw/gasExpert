"""RepairPlanSkill — registered skill class."""
from app.skills import register_skill
from app.skills.base import Skill
from app.skills.repair_plan.graph import repair_plan_graph
from app.skills.repair_plan.state import RepairPlanInput, RepairPlanOutput


@register_skill
class RepairPlanSkill(Skill):
    name = "repair_plan"
    description = "基于关阀方案、扩散范围和物资库存，生成结构化抢修方案并下发工单"
    input_schema = RepairPlanInput
    output_schema = RepairPlanOutput

    def build_graph(self):
        return repair_plan_graph
