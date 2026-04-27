"""ValveIsolationSkill — registered skill class."""
from app.skills import register_skill
from app.skills.base import Skill
from app.skills.valve_isolation.graph import valve_isolation_graph
from app.skills.valve_isolation.state import ValveIsolationInput, ValveIsolationOutput


@register_skill
class ValveIsolationSkill(Skill):
    name = "valve_isolation"
    description = "给定泄漏管段，生成关阀方案（含阀门序列、影响评估与审批预览）"
    input_schema = ValveIsolationInput
    output_schema = ValveIsolationOutput

    def build_graph(self):
        return valve_isolation_graph
