"""Parse historical incident xlsx (triple format) into structured IncidentCase objects.

xlsx 结构：四列 [subject, predicate, object, location]，记录以 (p='包括', o='接警阶段') 为边界分段。
每个事故约 ~52 行三元组，覆盖 6 个阶段：接警/出警/现场确认/先期处置/维修/后期恢复。

本脚本不依赖 openpyxl/pandas — 直接解压 xlsx 读取 XML，环境干净也能跑。

Usage:
    python3 backend/scripts/parse_incidents_xlsx.py \
        --in  backend/data/cases/raw/incidents.xlsx \
        --out backend/data/cases/processed/cases.json \
        --report backend/data/cases/processed/data_quality_report.md
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter, defaultdict
from typing import Any

# 把 backend 加进 sys.path，方便直接运行脚本时导入 app.cases.schema
_HERE = os.path.abspath(os.path.dirname(__file__))
_BACKEND = os.path.dirname(_HERE)
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from app.cases.schema import (  # noqa: E402
    AlarmStage,
    DispatchStage,
    FailurePoint,
    IncidentCase,
    InitialResponseStage,
    PipelineSpec,
    RecoveryStage,
    RepairAction,
    RepairStage,
    SceneConfirmStage,
    SurroundingEnv,
)

NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
NS_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"

# ---- 基础：解压 xlsx 读 XML ----

def _extract_xlsx(src: str, dst: str) -> None:
    if os.path.exists(dst):
        shutil.rmtree(dst)
    os.makedirs(dst)
    with zipfile.ZipFile(src) as z:
        z.extractall(dst)


def _load_shared_strings(extract_dir: str) -> list[str]:
    path = os.path.join(extract_dir, "xl", "sharedStrings.xml")
    if not os.path.exists(path):
        return []
    tree = ET.parse(path)
    out: list[str] = []
    for si in tree.getroot():
        texts = [t.text or "" for t in si.iter(f"{NS_MAIN}t")]
        out.append("".join(texts))
    return out


def _cell_value(c: ET.Element, shared: list[str]) -> str:
    t = c.get("t", "n")
    v = c.find("s:v", NS)
    if v is None:
        is_el = c.find("s:is", NS)
        if is_el is not None:
            txts = [tt.text or "" for tt in is_el.iter(f"{NS_MAIN}t")]
            return "".join(txts)
        return ""
    if t == "s":
        idx = int(v.text or "0")
        return shared[idx] if 0 <= idx < len(shared) else ""
    return v.text or ""


def load_triples(xlsx_path: str) -> list[tuple[str, str, str, str]]:
    """Return list of (subject, predicate, object, location) tuples."""
    with tempfile.TemporaryDirectory() as tmp:
        _extract_xlsx(xlsx_path, tmp)
        shared = _load_shared_strings(tmp)
        sheet_path = os.path.join(tmp, "xl", "worksheets", "sheet1.xml")
        tree = ET.parse(sheet_path)
        sheetdata = tree.getroot().find("s:sheetData", NS)
        triples: list[tuple[str, str, str, str]] = []
        for r in sheetdata.findall("s:row", NS):
            vals = [_cell_value(c, shared) for c in r.findall("s:c", NS)]
            vals += [""] * (4 - len(vals))
            triples.append(tuple(vals[:4]))  # type: ignore[arg-type]
    return triples


# ---- 值规整 ----

_TRUE_TOKENS = {"是", "有", "true", "True"}
_FALSE_TOKENS = {"否", "无", "false", "False", ""}

# 这几列："有/无"是真正的三态（含"其他说明"），不该走 bool
_TEXTUAL_YESNO_PREDICATES: set[str] = set()


def _to_bool(v: str) -> bool | None:
    v = (v or "").strip()
    if v in _TRUE_TOKENS:
        return True
    if v in _FALSE_TOKENS:
        return False
    return None


def _excel_serial_to_hhmm(v: str) -> str | None:
    """Excel time stored as fraction of a day → 'HH:MM'."""
    if not v:
        return None
    try:
        f = float(v)
    except ValueError:
        return None
    if not 0 <= f < 2:  # 正常时间 0~1，防御一下
        return None
    total_min = round(f * 24 * 60)
    h, m = divmod(total_min, 60)
    return f"{h:02d}:{m:02d}"


def _to_float(v: str) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _normalize_material(v: str) -> str:
    v = (v or "").strip().replace(" ", "")
    if v in {"钢管", "钢 管"}:
        return "钢管"
    if v in {"PE管", "PE"}:
        return "PE管"
    if v == "调压器":
        return "调压器"
    return v or "其他"


# ---- 记录切分 ----

EVENT_TYPES = {
    "三通接口漏气", "三通漏气", "三通锈蚀漏气", "变径接口漏气", "地质沉降管道破损漏气",
    "套筒接口漏气", "封堵", "弯头接口漏气", "弯头漏气", "弯头锈蚀漏气", "接口漏气",
    "漏气", "第三方破坏", "管道破裂", "管道破裂漏气", "管道锈蚀泄漏", "锈蚀漏气",
    "阀芯漏气", "阀门漏气",
}

STAGE_MARKERS = {"接警阶段", "出警阶段", "现场确认阶段", "先期处置阶段", "维修阶段", "后期恢复阶段"}


def split_records(triples: list[tuple[str, str, str, str]]) -> list[list[tuple[str, str, str, str]]]:
    """以 (p='包括', o='接警阶段') 作为新记录起点切分。"""
    records: list[list[tuple[str, str, str, str]]] = []
    cur: list[tuple[str, str, str, str]] = []
    for t in triples:
        if t[1] == "包括" and t[2] == "接警阶段":
            if cur:
                records.append(cur)
            cur = [t]
        else:
            cur.append(t)
    if cur:
        records.append(cur)
    return records


# ---- 单条记录解析 ----

def parse_record(idx: int, record: list[tuple[str, str, str, str]]) -> tuple[IncidentCase | None, list[str]]:
    """Parse one record's triples into an IncidentCase. Returns (case, warnings)."""
    warnings: list[str] = []

    # 事件类型 = 首行 subject
    event_type = record[0][0]
    if event_type not in EVENT_TYPES:
        warnings.append(f"未识别的事件类型: {event_type}")

    # 地点：取众数（一条记录的 col3 应该一致，个别行可能漂移）
    loc_counter = Counter(t[3] for t in record if t[3])
    location = loc_counter.most_common(1)[0][0] if loc_counter else ""

    # 按 subject 分桶，便于访问
    buckets: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for s, p, o, _ in record:
        buckets[s].append((p, o))

    def _get(subj: str, pred: str) -> str:
        for p, o in buckets.get(subj, []):
            if p == pred:
                return o
        return ""

    # 接警阶段
    alarm = AlarmStage(
        alarm_time=_excel_serial_to_hhmm(_get("接警阶段", "接警时间")),
        event_location=_get("接警阶段", "事件地点") or None,
        alarm_channel=_get("接警阶段", "接警方式") or None,  # type: ignore[arg-type]
        emergency_level=_get("接警阶段", "预启动应急预案等级") or None,  # type: ignore[arg-type]
    )

    # 出警阶段
    dispatch = DispatchStage(
        personnel_count=_get("出警阶段", "出警人员数量") or None,
        tools_config=_get("出警阶段", "工器具配置") or None,
        arrival_time=_excel_serial_to_hhmm(_get("出警阶段", "到达时间")),
    )

    # 现场确认 — 先把 pipeline/surrounding 解出来
    material_raw = _normalize_material(_get("现场确认阶段", "管材"))
    # 管材详情可能挂在 "钢管" / "PE管" / "调压器" 这几个子主语下
    detail_subj = material_raw if material_raw in {"钢管", "PE管", "调压器"} else None

    pipeline = None
    if detail_subj:
        pipeline = PipelineSpec(
            material=material_raw,  # type: ignore[arg-type]
            pressure_class=_get(detail_subj, "压力机制") or None,  # type: ignore[arg-type]
            steel_dn=(_get(detail_subj, "钢管公称直径") or None),
            pe_de=(_get(detail_subj, "PE管公称外径") or None),
            laying_environment=_get(detail_subj, "敷设环境") or None,  # type: ignore[arg-type]
            burial_depth_m=_to_float(_get(detail_subj, "管道埋深")),
        )
        # 清洗占位 "无"
        if pipeline.steel_dn == "无":
            pipeline.steel_dn = None
        if pipeline.pe_de == "无":
            pipeline.pe_de = None

    surrounding = SurroundingEnv(
        area_class=_get("周边环境", "地区等级") or None,  # type: ignore[arg-type]
        has_adjacent_infra=_to_bool(_get("周边环境", "有无相交相遇相邻")),
        has_confined_space_within_5m=_to_bool(_get("周边环境", "5m范围内有无密闭空间")),
        has_critical_building=_to_bool(_get("周边环境", "是否有重要建构筑物")),
        critical_building_note=(
            v if (v := _get("周边环境", "是否有重要建构筑物")) not in {"有", "无"} else None
        ),
    )

    scene = SceneConfirmStage(
        pipeline=pipeline,
        surrounding=surrounding,
        event_nature=_get("现场确认阶段", "事件性质") or None,
        emergency_level=_get("现场确认阶段", "预启动应急预案等级") or None,  # type: ignore[arg-type]
        has_casualties=_to_bool(_get("现场确认阶段", "有无人员伤亡")),
        has_property_loss=_to_bool(_get("现场确认阶段", "有无财产损失")),
        has_affected_users=_to_bool(_get("现场确认阶段", "有无影响用户")),
        leak_location=_get("现场确认阶段", "泄漏地点") or None,
    )

    # 先期处置阶段
    initial = InitialResponseStage(
        leak_detection_tools=_get("先期处置阶段", "测漏探边工器具") or None,
        valve_shutoff_tools=_get("先期处置阶段", "关阀放散工器具") or None,
        warning_evacuation_tools=_get("先期处置阶段", "警戒疏散工器具") or None,
        rescue_tools=_get("先期处置阶段", "救护救援工器具") or None,
    )

    # 维修阶段 = 失效点确认 + 维修作业
    failure_point = FailurePoint(
        leak_localization_method=_get("失效点确认", "泄漏点定位方式") or None,
        failure_mode=_get("失效点确认", "失效模式") or None,
        direct_cause=_get("失效点确认", "直接原因") or None,
        indirect_cause=_get("失效点确认", "间接原因") or None,
    )

    repair_action = RepairAction(
        is_replacement=_to_bool(_get("维修作业", "是否置换作业")),
        repair_method=_get("维修作业", "维修方式") or None,
        material_consumption=_get("维修作业", "管材管件消耗数量") or None,
        required_tools=_get("维修作业", "所需工器具") or None,
        personnel_count=_get("维修作业", "人员数量") or None,
        weld_quality_check=_get("维修作业", "焊缝质量检测") or None,
        steel_anticorrosion=_to_bool(_get("维修作业", "钢制管道防腐")),
        anticorrosion_quality_check=_to_bool(_get("维修作业", "防腐层质量检测")),
        civil_restoration=_to_bool(_get("维修作业", "土建恢复")),
    )

    repair = RepairStage(failure_point=failure_point, repair_action=repair_action)

    # 后期恢复阶段
    recovery = RecoveryStage(
        recovery_time=_excel_serial_to_hhmm(_get("后期恢复阶段", "恢复供气时间")),
        is_pressurized=_to_bool(_get("后期恢复阶段", "是否升压")),
        leak_recheck=_get("后期恢复阶段", "是否测漏") or None,
        user_notified=_to_bool(_get("后期恢复阶段", "是否通知用户")),
    )

    case = IncidentCase(
        incident_id=f"INC{idx:04d}",
        event_type=event_type,
        location=location,
        alarm=alarm,
        dispatch=dispatch,
        scene_confirm=scene,
        initial_response=initial,
        repair=repair,
        recovery=recovery,
    )
    return case, warnings


# ---- 质检报告 ----

def _field_completeness(cases: list[IncidentCase]) -> dict[str, float]:
    """Flatten each case's non-null leaf fields, compute per-field non-null ratio."""
    def _walk(prefix: str, v: Any, out: dict[str, int]) -> None:
        if isinstance(v, BaseModelLike):
            for k, sub in v.__dict__.items():
                _walk(f"{prefix}.{k}" if prefix else k, sub, out)
        else:
            out[prefix] = out.get(prefix, 0) + (0 if v in (None, "") else 1)

    # Use pydantic's model_dump to avoid importing BaseModel check issues
    totals: Counter[str] = Counter()
    non_null: Counter[str] = Counter()

    def walk(prefix: str, node: Any) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                walk(f"{prefix}.{k}" if prefix else k, v)
        else:
            totals[prefix] += 1
            if node not in (None, ""):
                non_null[prefix] += 1

    for c in cases:
        walk("", c.model_dump())

    return {k: non_null[k] / totals[k] for k in totals}


class BaseModelLike:  # sentinel, unused
    pass


def build_report(cases: list[IncidentCase], all_warnings: list[tuple[str, list[str]]]) -> str:
    lines = []
    lines.append("# 历史事故数据质检报告\n")
    lines.append(f"- 事故记录总数: **{len(cases)}**\n")

    # 事件类型分布
    lines.append("\n## 事件类型分布\n")
    et = Counter(c.event_type for c in cases)
    for e, n in et.most_common():
        lines.append(f"- {e}: {n}")

    # 管材 × 压力 分布
    lines.append("\n## 管材 × 压力 分布\n")
    mp = Counter()
    for c in cases:
        if c.scene_confirm and c.scene_confirm.pipeline:
            mp[(c.scene_confirm.pipeline.material or "未知",
                c.scene_confirm.pipeline.pressure_class or "未知")] += 1
    for (m, p), n in mp.most_common():
        lines.append(f"- {m} / {p}: {n}")

    # 应急等级
    lines.append("\n## 预启动应急预案等级\n")
    el = Counter(c.scene_confirm.emergency_level for c in cases if c.scene_confirm)
    for lv, n in el.most_common():
        lines.append(f"- {lv}: {n}")

    # 失效模式 Top
    lines.append("\n## 失效模式 Top 10\n")
    fm = Counter()
    for c in cases:
        if c.repair and c.repair.failure_point and c.repair.failure_point.failure_mode:
            fm[c.repair.failure_point.failure_mode] += 1
    for m, n in fm.most_common(10):
        lines.append(f"- {m}: {n}")

    # 字段完整度
    lines.append("\n## 关键字段非空率\n")
    comp = _field_completeness(cases)
    key_fields = [
        "event_type", "location",
        "alarm.alarm_time", "alarm.alarm_channel", "alarm.emergency_level",
        "scene_confirm.emergency_level", "scene_confirm.leak_location",
        "scene_confirm.pipeline.material", "scene_confirm.pipeline.pressure_class",
        "scene_confirm.pipeline.burial_depth_m",
        "repair.failure_point.failure_mode", "repair.failure_point.direct_cause",
        "repair.repair_action.repair_method", "repair.repair_action.personnel_count",
        "recovery.recovery_time", "recovery.is_pressurized",
    ]
    for f in key_fields:
        if f in comp:
            lines.append(f"- `{f}`: {comp[f] * 100:.1f}%")

    # 异常值
    lines.append("\n## 异常值扫描\n")
    anomalies = []
    for c in cases:
        if c.scene_confirm and c.scene_confirm.pipeline:
            d = c.scene_confirm.pipeline.burial_depth_m
            if d is not None and (d < 0 or d > 5):
                anomalies.append(f"{c.incident_id} 埋深越界: {d}m")
    if anomalies:
        for a in anomalies:
            lines.append(f"- {a}")
    else:
        lines.append("- ✅ 未发现埋深越界样本")

    # 警告
    warn_cases = [(i, ws) for i, ws in all_warnings if ws]
    lines.append(f"\n## 解析告警 ({len(warn_cases)} 条记录有告警)\n")
    for i, ws in warn_cases[:20]:
        lines.append(f"- {i}: {'; '.join(ws)}")
    if len(warn_cases) > 20:
        lines.append(f"- ...（省略 {len(warn_cases) - 20} 条）")

    return "\n".join(lines) + "\n"


# ---- CLI ----

def main() -> int:
    ap = argparse.ArgumentParser(description="Parse incidents.xlsx → structured IncidentCase JSON")
    ap.add_argument("--in", dest="in_path", default="backend/data/cases/raw/incidents.xlsx")
    ap.add_argument("--out", dest="out_path", default="backend/data/cases/processed/cases.json")
    ap.add_argument("--report", dest="report_path",
                    default="backend/data/cases/processed/data_quality_report.md")
    args = ap.parse_args()

    if not os.path.exists(args.in_path):
        print(f"输入不存在: {args.in_path}", file=sys.stderr)
        return 2

    print(f"[1/4] 加载三元组 {args.in_path}")
    triples = load_triples(args.in_path)
    print(f"      共 {len(triples)} 条三元组")

    print("[2/4] 切分事故记录")
    records = split_records(triples)
    print(f"      切分出 {len(records)} 条事故")

    print("[3/4] 解析为 IncidentCase")
    cases: list[IncidentCase] = []
    all_warnings: list[tuple[str, list[str]]] = []
    for i, rec in enumerate(records, start=1):
        case, warns = parse_record(i, rec)
        if case is None:
            continue
        cases.append(case)
        all_warnings.append((case.incident_id, warns))

    os.makedirs(os.path.dirname(args.out_path), exist_ok=True)
    with open(args.out_path, "w", encoding="utf-8") as f:
        json.dump([c.model_dump() for c in cases], f, ensure_ascii=False, indent=2)
    print(f"      已写入 {args.out_path}  ({len(cases)} 条)")

    print("[4/4] 生成质检报告")
    report = build_report(cases, all_warnings)
    with open(args.report_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"      已写入 {args.report_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
