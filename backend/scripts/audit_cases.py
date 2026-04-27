"""Deep quality audit for parsed IncidentCase JSON + raw jsonl.

Produces three artifacts in `backend/data/cases/processed/`:
- `data_quality_report.md` — 完整度 / 枚举分布 / 异常值 / jsonl 重复度
- `value_normalization.yaml` — 低频枚举值归并映射表（人工可编辑）
- `enum_distributions.json` — 所有 enum-like 字段的原始分布（供后续脚本消费）

Usage:
    python backend/scripts/audit_cases.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

# ---- 路径 ----
_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
_ROOT = _BACKEND.parent

DEFAULT_CASES = _BACKEND / "data/cases/processed/cases.json"
DEFAULT_JSONL = _BACKEND / "data/cases/raw/incidents.jsonl"
DEFAULT_REPORT = _BACKEND / "data/cases/processed/data_quality_report.md"
DEFAULT_NORM = _BACKEND / "data/cases/processed/value_normalization.yaml"
DEFAULT_ENUM_DIST = _BACKEND / "data/cases/processed/enum_distributions.json"


# ---- Enum-like 字段清单（叶子路径 → 字段语义） ----
ENUM_FIELDS: dict[str, str] = {
    "event_type": "事件类型",
    "alarm.alarm_channel": "接警方式",
    "alarm.emergency_level": "预启动应急预案等级",
    "scene_confirm.event_nature": "事件性质",
    "scene_confirm.emergency_level": "预启动应急预案等级",
    "scene_confirm.pipeline.material": "管材",
    "scene_confirm.pipeline.pressure_class": "压力机制",
    "scene_confirm.pipeline.laying_environment": "敷设环境",
    "scene_confirm.surrounding.area_class": "地区等级",
    "repair.failure_point.failure_mode": "失效模式",
    "repair.failure_point.direct_cause": "直接原因",
    "repair.failure_point.indirect_cause": "间接原因",
    "repair.repair_action.repair_method": "维修方式",
    "repair.repair_action.personnel_count": "人员数量",
    "repair.repair_action.weld_quality_check": "焊缝质量检测",
}

# ---- 遍历 helper ----
def walk_field(case: dict, dotted: str) -> Any:
    cur: Any = case
    for k in dotted.split("."):
        if cur is None:
            return None
        cur = cur.get(k) if isinstance(cur, dict) else None
    return cur


def walk_all_leaves(node: Any, prefix: str = "") -> list[tuple[str, Any]]:
    """Flatten nested dict → list of (dotted_path, leaf_value)."""
    out: list[tuple[str, Any]] = []
    if isinstance(node, dict):
        for k, v in node.items():
            p = f"{prefix}.{k}" if prefix else k
            out.extend(walk_all_leaves(v, p))
    else:
        out.append((prefix, node))
    return out


# ---- 归一化候选 ----
def _strip_spaces(s: str) -> str:
    return re.sub(r"\s+", "", s)


def _canonical_hint(vals: list[str]) -> str | None:
    """Pick a canonical form for a group by (a) shortest, (b) no spaces, (c) highest freq."""
    if not vals:
        return None
    # 先按去空格后一致聚合，挑频次最高的
    return max(vals, key=lambda v: (vals.count(v), -len(v)))


def propose_normalization(enum_dist: dict[str, Counter]) -> dict[str, dict[str, str]]:
    """Group values that collapse to the same stripped string; flag low-freq variants as aliases.

    输出：{field_path: {raw_value: canonical_value}}，仅当 raw != canonical 时才写入。
    """
    mapping: dict[str, dict[str, str]] = {}
    for field, counter in enum_dist.items():
        groups: dict[str, list[str]] = defaultdict(list)
        for v in counter:
            if v is None or v == "":
                continue
            key = _strip_spaces(str(v))
            groups[key].append(str(v))
        field_map: dict[str, str] = {}
        for key, variants in groups.items():
            if len(variants) <= 1:
                continue
            # 挑频次最高的做规范形式
            canon = max(variants, key=lambda v: counter[v])
            for v in variants:
                if v != canon:
                    field_map[v] = canon
        # 另：超低频值（<=1 次）单列为 review 区，不自动合并
        if field_map:
            mapping[field] = field_map
    return mapping


# ---- 异常值扫描 ----
def scan_anomalies(cases: list[dict]) -> list[str]:
    out: list[str] = []
    for c in cases:
        cid = c.get("incident_id", "?")
        pipe = (c.get("scene_confirm") or {}).get("pipeline") or {}
        depth = pipe.get("burial_depth_m")
        if depth is not None and (depth < 0 or depth > 5):
            out.append(f"{cid} 埋深越界: {depth}m")
        # 管径格式：钢管应为 DN<num>，PE 管应为 De<num>
        steel_dn = pipe.get("steel_dn")
        if steel_dn and not re.match(r"^DN\d+", steel_dn):
            out.append(f"{cid} 钢管公称直径格式异常: {steel_dn}")
        pe_de = pipe.get("pe_de")
        if pe_de and not re.match(r"^De\d+", pe_de):
            out.append(f"{cid} PE 管外径格式异常: {pe_de}")
        # 时间格式
        for stage_name, time_field in [
            ("alarm", "alarm_time"),
            ("dispatch", "arrival_time"),
            ("recovery", "recovery_time"),
        ]:
            t = (c.get(stage_name) or {}).get(time_field)
            if t and not re.match(r"^\d{2}:\d{2}$", t):
                out.append(f"{cid} {stage_name}.{time_field} 格式异常: {t}")
    return out


# ---- jsonl 重复度 ----
def audit_jsonl_duplicates(jsonl_path: Path) -> dict[str, Any]:
    """用 MinHash-free 的简易做法：question 前 60 字符去空白后做 SHA1 分桶。"""
    if not jsonl_path.exists():
        return {"exists": False}
    buckets: dict[str, list[int]] = defaultdict(list)
    total = 0
    with jsonl_path.open(encoding="utf-8") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            total += 1
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            q = obj.get("question") or ""
            fingerprint = re.sub(r"\s+", "", q)[:120]
            h = hashlib.sha1(fingerprint.encode("utf-8")).hexdigest()
            buckets[h].append(i)
    dup_buckets = {h: idxs for h, idxs in buckets.items() if len(idxs) > 1}
    dup_records = sum(len(v) for v in dup_buckets.values())
    return {
        "exists": True,
        "total": total,
        "unique_fingerprints": len(buckets),
        "duplicate_buckets": len(dup_buckets),
        "duplicate_records": dup_records,
        "dup_rate": dup_records / total if total else 0.0,
    }


# ---- 报告构建 ----
def build_report(
    cases: list[dict],
    enum_dist: dict[str, Counter],
    completeness: dict[str, float],
    anomalies: list[str],
    jsonl_stats: dict[str, Any],
    norm_proposals: dict[str, dict[str, str]],
) -> str:
    L: list[str] = []
    L.append("# 历史事故数据深度质检报告（6.0.5.2）\n")
    L.append(f"- 事故记录总数: **{len(cases)}**")
    L.append("- 数据来源: `backend/data/cases/processed/cases.json`（由 6.0.5.1 产出）")
    L.append("")

    # ---- 字段完整度 ----
    L.append("## 1. 字段完整度（所有叶子字段）\n")
    L.append("| 字段路径 | 非空率 |")
    L.append("|---|---|")
    for path, rate in sorted(completeness.items(), key=lambda x: x[1]):
        L.append(f"| `{path}` | {rate * 100:.1f}% |")
    L.append("")

    # ---- 枚举分布 ----
    L.append("## 2. 枚举字段分布\n")
    for field, semantic in ENUM_FIELDS.items():
        c = enum_dist.get(field) or Counter()
        total = sum(c.values())
        if not total:
            continue
        L.append(f"### `{field}`（{semantic}，共 {total} 个非空值，{len(c)} 个不同取值）\n")
        L.append("| 值 | 次数 | 占比 |")
        L.append("|---|---|---|")
        for v, n in c.most_common():
            pct = n / total * 100
            flag = " ⚠️" if n <= 1 else ""
            display = v if v != "" else "(空)"
            L.append(f"| {display} | {n} | {pct:.1f}%{flag} |")
        L.append("")

    # ---- 异常值 ----
    L.append("## 3. 异常值扫描\n")
    if anomalies:
        L.append(f"共 **{len(anomalies)}** 条异常：\n")
        for a in anomalies:
            L.append(f"- {a}")
    else:
        L.append("- ✅ 未发现异常值（埋深 / 管径格式 / 时间格式全部合规）")
    L.append("")

    # ---- 归一化提议 ----
    L.append("## 4. 枚举值归一化提议\n")
    if norm_proposals:
        L.append('以下字段检测到"去空格后一致"的变体，建议归并。完整映射已写入 `value_normalization.yaml`，可人工编辑后在后续步骤应用。\n')
        for field, m in norm_proposals.items():
            L.append(f"### `{field}`\n")
            for raw, canon in m.items():
                L.append(f"- `{raw!r}` → `{canon!r}`")
            L.append("")
    else:
        L.append("- ✅ 未发现需要归并的变体")
    L.append("")

    # ---- jsonl 重复度 ----
    L.append("## 5. jsonl 重复度分析\n")
    if not jsonl_stats.get("exists"):
        L.append("- ⚠️ 未找到 `incidents.jsonl`")
    else:
        L.append(f"- 总条数: **{jsonl_stats['total']}**")
        L.append(f"- 唯一指纹数: **{jsonl_stats['unique_fingerprints']}**（基于 question 前 120 字去空白 SHA1）")
        L.append(f"- 重复桶: **{jsonl_stats['duplicate_buckets']}**（桶内 ≥2 条记录）")
        L.append(f"- 重复记录总数: **{jsonl_stats['duplicate_records']}**（桶内记录累加）")
        L.append(f"- 重复率: **{jsonl_stats['dup_rate'] * 100:.1f}%**")
        L.append("")
        L.append("> 对 RAG 召回与 few-shot 池影响有限；对 SFT 微调需要在 6.0.5.3 分层抽样时按语义分组去重。")
    L.append("")

    return "\n".join(L) + "\n"


def dump_yaml(proposals: dict[str, dict[str, str]], path: Path) -> None:
    lines: list[str] = []
    lines.append("# 枚举值归一化映射（自动生成，人工可编辑后再应用）")
    lines.append("# 用途：在 IncidentCase 加回 Literal 强校验之前，把同义变体合并到规范形式")
    lines.append("# 格式：<field_path>:")
    lines.append("#        raw_value: canonical_value")
    lines.append("")
    for field, m in proposals.items():
        lines.append(f"{field}:")
        for raw, canon in m.items():
            # YAML 中文友好：直接用双引号
            lines.append(f'  "{raw}": "{canon}"')
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


# ---- 主流程 ----
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default=str(DEFAULT_CASES))
    ap.add_argument("--jsonl", default=str(DEFAULT_JSONL))
    ap.add_argument("--report", default=str(DEFAULT_REPORT))
    ap.add_argument("--normalize", default=str(DEFAULT_NORM))
    ap.add_argument("--enum-dist", default=str(DEFAULT_ENUM_DIST))
    args = ap.parse_args()

    cases_path = Path(args.cases)
    if not cases_path.exists():
        print(f"cases.json 不存在: {cases_path}，请先运行 parse_incidents_xlsx.py", file=sys.stderr)
        return 2

    print(f"[1/5] 加载 {cases_path}")
    cases: list[dict] = json.loads(cases_path.read_text(encoding="utf-8"))
    print(f"      {len(cases)} 条案例")

    print("[2/5] 字段完整度 & 枚举分布")
    totals: Counter[str] = Counter()
    non_null: Counter[str] = Counter()
    enum_dist: dict[str, Counter] = {f: Counter() for f in ENUM_FIELDS}
    for c in cases:
        for path, leaf in walk_all_leaves(c):
            totals[path] += 1
            if leaf not in (None, ""):
                non_null[path] += 1
        for f in ENUM_FIELDS:
            v = walk_field(c, f)
            if v not in (None, ""):
                enum_dist[f][str(v)] += 1
    completeness = {p: non_null[p] / totals[p] for p in totals}

    print("[3/5] 异常值扫描")
    anomalies = scan_anomalies(cases)
    print(f"      {len(anomalies)} 条异常")

    print("[4/5] jsonl 重复度")
    jsonl_stats = audit_jsonl_duplicates(Path(args.jsonl))
    if jsonl_stats.get("exists"):
        print(f"      总 {jsonl_stats['total']}，重复 {jsonl_stats['duplicate_records']} "
              f"({jsonl_stats['dup_rate']*100:.1f}%)")

    print("[5/5] 生成归一化提议 + 写报告")
    proposals = propose_normalization(enum_dist)
    report = build_report(cases, enum_dist, completeness, anomalies, jsonl_stats, proposals)
    Path(args.report).write_text(report, encoding="utf-8")
    dump_yaml(proposals, Path(args.normalize))
    # 导出 enum 分布 JSON 供后续脚本消费
    Path(args.enum_dist).write_text(
        json.dumps({f: dict(c) for f, c in enum_dist.items()}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"      报告: {args.report}")
    print(f"      归一化: {args.normalize}")
    print(f"      枚举分布: {args.enum_dist}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
