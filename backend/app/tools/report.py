"""Structured emergency report generation tool — LLM-driven."""

import json
from datetime import datetime

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool

logger = structlog.get_logger()

REPORT_SYSTEM_PROMPT = """\
你是燃气抢险报告撰写专家。根据提供的现场信息，生成一份规范的抢险处置报告。

## 报告格式要求（严格按以下章节输出 Markdown）

# 燃气抢险处置报告

## 一、事故概况
- 事故类型、时间、地点
- 管道参数（压力、管径、泄漏类型）

## 二、现场环境评估
- 气象条件及对抢险的影响
- 风险等级判定

## 三、疏散方案
- 疏散半径及影响面积
- 疏散方向（根据风向，优先上风向）
- 警戒线设置要求
- 特殊人群（医院、学校、养老院）疏散安排

## 四、抢修资源调配
- 可调用的抢险站及距离
- 关键物资清单及数量
- 人员调配建议

## 五、处置步骤
1. 先期处置（到达前）
2. 现场警戒与疏散
3. 检测与定位
4. 管道处置（关阀、堵漏/封堵）
5. 通气恢复与检验

## 六、安全注意事项
- 作业安全要求
- 个人防护要求
- 禁止事项

## 报告补充说明
- 所有数据引用需标注来源（工具计算结果/规范条款）
- 如果信息不完整，在对应章节注明"待补充"并说明缺少什么
- 语言简练、指令明确、可直接用于现场指挥
"""


@tool
async def generate_report(
    incident_type: str,
    location: str,
    situation_summary: str,
) -> str:
    """基于已收集的事故信息，生成结构化的燃气抢险处置报告。

    Args:
        incident_type: 事故类型，如 "天然气管道泄漏"、"PE管破裂"
        location: 事故发生地点
        situation_summary: 现场情况综合摘要，应包含已知的天气、疏散计算、物资查询等信息
    """
    from app.agent.llm import get_llm

    timestamp = datetime.now().strftime("%Y年%m月%d日 %H:%M")
    user_prompt = (
        f"请根据以下信息生成抢险处置报告。\n\n"
        f"**报告时间**：{timestamp}\n"
        f"**事故类型**：{incident_type}\n"
        f"**事故地点**：{location}\n\n"
        f"**现场综合信息**：\n{situation_summary}"
    )

    llm = get_llm()
    try:
        response = await llm.ainvoke([
            SystemMessage(content=REPORT_SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ])
        report = response.content
        logger.info("report_generated", length=len(report))
        return report
    except Exception as exc:
        logger.error("report_generation_failed", error=str(exc))
        return (
            f"# 燃气抢险处置报告（简要版）\n\n"
            f"**生成时间**：{timestamp}\n"
            f"**事故类型**：{incident_type}\n"
            f"**事故地点**：{location}\n\n"
            f"## 已知信息\n{situation_summary}\n\n"
            f"> ⚠️ 完整报告生成失败（{exc}），以上为已收集信息汇总，请人工补充完善。"
        )
