"""Evacuation zone calculation tool.

Calculation model references:
- GB 50028-2006 《城镇燃气设计规范》
- CJJ 51-2016 《城镇燃气设施运行、维护和抢修安全技术规程》
"""

import math

from langchain_core.tools import tool

_LEAK_MULTIPLIER = {
    "pinhole": 1.0,
    "crack": 2.0,
    "rupture": 3.5,
}

_LEAK_TYPE_CN = {
    "pinhole": "针孔泄漏",
    "crack": "裂缝泄漏",
    "rupture": "断裂泄漏",
}

_PRESSURE_CLASS = [
    (0.01, "低压"),
    (0.2, "中压B"),
    (0.4, "中压A"),
    (0.8, "次高压B"),
    (1.6, "次高压A"),
    (4.0, "高压B"),
    (float("inf"), "高压A"),
]

_RISK_THRESHOLDS = [
    (200, "高危", "red"),
    (50, "中危", "orange"),
    (0, "低危", "yellow"),
]

_SAFETY_INSTRUCTIONS = {
    "高危": [
        "立即启动一级应急响应",
        "通知消防、公安、医疗部门联动",
        "疏散范围内所有人员，设置三级警戒线",
        "禁止一切车辆进入警戒区域",
        "切断警戒区域内所有电源",
        "安排专人在各路口引导交通疏导",
    ],
    "中危": [
        "启动二级应急响应",
        "疏散范围内人员，设置警戒线",
        "禁止明火和产生火花的操作",
        "通知周边单位和居民",
        "安排检测人员持续监测燃气浓度",
    ],
    "低危": [
        "启动三级应急响应",
        "设置警示标识和警戒带",
        "禁止在泄漏点附近使用明火",
        "安排检测人员监测燃气浓度变化",
    ],
}


def _classify_pressure(pressure_mpa: float) -> str:
    for threshold, label in _PRESSURE_CLASS:
        if pressure_mpa <= threshold:
            return label
    return "高压A"


@tool
def calculate_evacuation_zone(
    pressure: float,
    diameter: float,
    leak_type: str,
    wind_speed: float = 0.0,
    is_indoor: bool = False,
) -> dict:
    """根据燃气管道参数计算疏散范围，并给出安全处置建议。

    Args:
        pressure: 管道压力 (MPa)
        diameter: 管道直径 (mm)
        leak_type: 泄漏类型 ("pinhole" 针孔 | "crack" 裂缝 | "rupture" 断裂)
        wind_speed: 当前风速 (km/h)，用于修正疏散范围，默认 0
        is_indoor: 是否为室内泄漏，室内场景疏散范围扩大
    """
    multiplier = _LEAK_MULTIPLIER.get(leak_type, 2.0)
    base_radius = math.sqrt(pressure * diameter) * multiplier

    wind_factor = 1.0
    if wind_speed >= 39:
        wind_factor = 1.5
    elif wind_speed >= 20:
        wind_factor = 1.2

    indoor_factor = 1.3 if is_indoor else 1.0

    radius = base_radius * wind_factor * indoor_factor
    area = math.pi * radius ** 2

    risk_level = "低危"
    risk_color = "yellow"
    for threshold, level, color in _RISK_THRESHOLDS:
        if radius > threshold:
            risk_level = level
            risk_color = color
            break

    pressure_class = _classify_pressure(pressure)

    return {
        "radius_m": round(radius, 1),
        "affected_area_m2": round(area, 1),
        "risk_level": risk_level,
        "risk_color": risk_color,
        "pressure_class": pressure_class,
        "leak_type": leak_type,
        "leak_type_cn": _LEAK_TYPE_CN.get(leak_type, leak_type),
        "base_radius_m": round(base_radius, 1),
        "wind_correction": f"×{wind_factor}" if wind_factor > 1 else "无",
        "indoor_correction": f"×{indoor_factor}" if indoor_factor > 1 else "无",
        "safety_instructions": _SAFETY_INSTRUCTIONS.get(risk_level, []),
        "immediate_actions": [
            "使用可燃气体检测仪确认泄漏浓度和范围",
            f"以泄漏点为中心设置 {round(radius, 0)}m 警戒区域",
            "从上风向接近泄漏点",
            "关闭泄漏管段上下游阀门",
        ],
    }
