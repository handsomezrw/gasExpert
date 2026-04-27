"""Incident case schema — aligned with historical xlsx triple data.

Used by:
- `repair_plan` Skill 输出结构
- Phase 9 案例库 (L2 记忆) 存储 schema
- 历史数据反解脚本 scripts/parse_incidents_xlsx.py
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


# ---- 枚举说明 (仅作文档，实际字段放宽为 str，给原始数据留容错空间) ----
# EventType 取值示例: 锈蚀漏气 / 第三方破坏 / 管道破裂 / 三通接口漏气 / 弯头漏气 / ...
# EmergencyLevel: 一级 / 二级 / 三级 / 四级
# AlarmChannel:   自查 / 外报
# PipelineMaterial: 钢管 / PE管 / 调压器 / 其他
# PressureClass:  低压 / 中压 / 中压A / 中压B / 次高压 / 次高压A / 次高压B / 高压 / 高压A / 高压B
# LayingEnvironment: 人行道 / 机动车道 / 绿化带 / 田(土) / 明管 / 穿越 / 污水井内 / ...
# AreaClass:      一级 / 二级 / 三级 / 四级


# ---- 嵌套模型 ----

class AlarmStage(BaseModel):
    """接警阶段"""
    alarm_time: Optional[str] = Field(None, description="HH:MM")
    event_location: Optional[str] = None
    alarm_channel: Optional[str] = Field(None, description="自查 / 外报")
    emergency_level: Optional[str] = Field(None, description="一级 / 二级 / 三级 / 四级")


class DispatchStage(BaseModel):
    """出警阶段"""
    personnel_count: Optional[str] = None
    tools_config: Optional[str] = None
    arrival_time: Optional[str] = Field(None, description="HH:MM")


class PipelineSpec(BaseModel):
    """管材规格（钢管 / PE 管 / 调压器）"""
    material: Optional[str] = Field(None, description="钢管 / PE管 / 调压器")
    pressure_class: Optional[str] = Field(None, description="低压 / 中压 / 高压 ...")
    steel_dn: Optional[str] = Field(None, description="钢管公称直径 DNx")
    pe_de: Optional[str] = Field(None, description="PE 管公称外径 Dex")
    laying_environment: Optional[str] = Field(None, description="敷设环境")
    burial_depth_m: Optional[float] = None


class SurroundingEnv(BaseModel):
    """周边环境"""
    area_class: Optional[str] = Field(None, description="一级 / 二级 / 三级 / 四级")
    has_adjacent_infra: Optional[bool] = None
    has_confined_space_within_5m: Optional[bool] = None
    has_critical_building: Optional[bool] = None
    critical_building_note: Optional[str] = None


class SceneConfirmStage(BaseModel):
    """现场确认阶段"""
    pipeline: Optional[PipelineSpec] = None
    surrounding: Optional[SurroundingEnv] = None
    event_nature: Optional[str] = None
    emergency_level: Optional[str] = None
    has_casualties: Optional[bool] = None
    has_property_loss: Optional[bool] = None
    has_affected_users: Optional[bool] = None
    leak_location: Optional[str] = None


class InitialResponseStage(BaseModel):
    """先期处置阶段"""
    leak_detection_tools: Optional[str] = None
    valve_shutoff_tools: Optional[str] = None
    warning_evacuation_tools: Optional[str] = None
    rescue_tools: Optional[str] = None


class FailurePoint(BaseModel):
    """失效点确认"""
    leak_localization_method: Optional[str] = None
    failure_mode: Optional[str] = None
    direct_cause: Optional[str] = None
    indirect_cause: Optional[str] = None


class RepairAction(BaseModel):
    """维修作业"""
    is_replacement: Optional[bool] = None
    repair_method: Optional[str] = None
    material_consumption: Optional[str] = None
    required_tools: Optional[str] = None
    personnel_count: Optional[str] = None
    weld_quality_check: Optional[str] = None
    steel_anticorrosion: Optional[bool] = None
    anticorrosion_quality_check: Optional[bool] = None
    civil_restoration: Optional[bool] = None


class RepairStage(BaseModel):
    """维修阶段"""
    failure_point: Optional[FailurePoint] = None
    repair_action: Optional[RepairAction] = None


class RecoveryStage(BaseModel):
    """后期恢复阶段"""
    recovery_time: Optional[str] = Field(None, description="HH:MM")
    is_pressurized: Optional[bool] = None
    leak_recheck: Optional[str] = None
    user_notified: Optional[bool] = None


# ---- 顶层 ----

class IncidentCase(BaseModel):
    """一个完整事故记录（对应 xlsx 中一个 250 条记录）"""

    # 标识
    incident_id: str
    event_type: str = Field(description="锈蚀漏气 / 第三方破坏 / 管道破裂 ...")
    location: str = Field(description="事故发生地点（xlsx 最后一列）")

    # 六个阶段
    alarm: AlarmStage = Field(default_factory=AlarmStage)
    dispatch: DispatchStage = Field(default_factory=DispatchStage)
    scene_confirm: SceneConfirmStage = Field(default_factory=SceneConfirmStage)
    initial_response: InitialResponseStage = Field(default_factory=InitialResponseStage)
    repair: RepairStage = Field(default_factory=RepairStage)
    recovery: RecoveryStage = Field(default_factory=RecoveryStage)

    # 复盘（预留，Phase 9 接入 jsonl 的 think 字段）
    think_trace: Optional[str] = None
    lessons_learned: Optional[str] = None
