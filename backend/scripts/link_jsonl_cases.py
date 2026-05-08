"""Link jsonl records ↔ xlsx-derived cases, attach think_trace, emit summary vectors.

匹配策略：
- 从 jsonl 的 question 字段抽取 (event_type, material, steel_dn/pe_de, burial_depth,
  emergency_level, failure_mode) 指纹
- 对每个 case 计算同样的指纹 → 在 jsonl 中找最佳匹配
- 一对多时按 incident_id 顺序分配，避免 think_trace 全堆在头几条

embedding 目前用 **确定性 feature-hash 向量（dim=128）** 占位，Phase 9 再接真正的 bge 模型。
向量基于：event_type / material / pressure / failure_mode / direct_cause / repair_method 的 hash bucket。

产出（写入 `backend/data/cases/processed/`）：
- `cases_enriched.json`       cases + think_trace + summary + summary_vec
- `linking_report.md`         匹配覆盖率统计 + 未匹配样本
- `case_summary_vectors.json` incident_id → 128-dim vector（轻量，方便 git diff）

Usage:
    python backend/scripts/link_jsonl_cases.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent

DEFAULT_CASES = _BACKEND / "data/cases/processed/cases.json"
DEFAULT_JSONL = _BACKEND / "data/cases/raw/incidents.jsonl"
DEFAULT_ENRICHED = _BACKEND / "data/cases/processed/cases_enriched.json"
DEFAULT_REPORT = _BACKEND / "data/cases/processed/linking_report.md"
DEFAULT_VEC = _BACKEND / "data/cases/processed/case_summary_vectors.json"

EMBED_DIM = 128

# ---- 指纹抽取 ----
def _extract_from_question(q: str) -> dict[str, str | None]:
    def _g(pat: str) -> str | None:
        m = re.search(pat, q)
        return m.group(1) if m else None

    return {
        "event_type": _g(r"事件类型是([^\s，。,]+?)[，,.]"),
        "emergency_level": _g(r"预启动应急预案等级是([一二三四]级)"),
        "material": _g(r"管材为?([^\s，。,]+?)[，,]"),
        "pressure_class": _g(r"压力级制为([^\s，。,]+?)[，,]"),
        "steel_dn": _g(r"钢管公称直径为?(DN\d+)"),
        "pe_de": _g(r"PE?管?公称外径为?(De\d+)"),
        "burial_depth": _g(r"管道埋深为?([0-9.]+)米"),
        "failure_mode": _g(r"失效模式为([^\s，。,]+?)[，,.]"),
        "direct_cause": _g(r"直接原因是([^\s，。,]+?)[，,.]"),
    }


def _case_fingerprint(c: dict) -> dict[str, str | None]:
    pipe = (c.get("scene_confirm") or {}).get("pipeline") or {}
    fp = (c.get("repair") or {}).get("failure_point") or {}
    depth = pipe.get("burial_depth_m")
    return {
        "event_type": c.get("event_type"),
        "emergency_level": (c.get("scene_confirm") or {}).get("emergency_level"),
        "material": (pipe.get("material") or "").replace(" ", "") or None,
        "pressure_class": pipe.get("pressure_class"),
        "steel_dn": pipe.get("steel_dn"),
        "pe_de": pipe.get("pe_de"),
        "burial_depth": f"{depth}" if depth is not None else None,
        "failure_mode": fp.get("failure_mode"),
        "direct_cause": fp.get("direct_cause"),
    }


def _match_score(a: dict, b: dict) -> int:
    """分字段打分：精确命中各字段权重累加。"""
    weights = {
        "event_type": 3,
        "failure_mode": 3,
        "material": 2,
        "pressure_class": 2,
        "steel_dn": 2,
        "pe_de": 2,
        "burial_depth": 2,
        "emergency_level": 1,
        "direct_cause": 1,
    }
    score = 0
    for k, w in weights.items():
        av, bv = a.get(k), b.get(k)
        if av and bv:
            # 规整：去空格
            if str(av).replace(" ", "") == str(bv).replace(" ", ""):
                score += w
    return score


# ---- 摘要 + 向量 ----
def build_summary(c: dict) -> str:
    pipe = (c.get("scene_confirm") or {}).get("pipeline") or {}
    fp = (c.get("repair") or {}).get("failure_point") or {}
    ra = (c.get("repair") or {}).get("repair_action") or {}
    parts = [
        f"事件类型={c.get('event_type')}",
        f"管材={pipe.get('material')}",
        f"压力={pipe.get('pressure_class')}",
        f"管径={pipe.get('steel_dn') or pipe.get('pe_de')}",
        f"埋深={pipe.get('burial_depth_m')}m",
        f"失效模式={fp.get('failure_mode')}",
        f"直接原因={fp.get('direct_cause')}",
        f"维修方式={ra.get('repair_method')}",
        f"应急等级={(c.get('scene_confirm') or {}).get('emergency_level')}",
    ]
    return "；".join(p for p in parts if not p.endswith("=None"))


def feature_hash_vector(c: dict, dim: int = EMBED_DIM) -> list[float]:
    """确定性 feature-hash 向量（占位，Phase 9 换 bge）。"""
    vec = [0.0] * dim
    pipe = (c.get("scene_confirm") or {}).get("pipeline") or {}
    fp = (c.get("repair") or {}).get("failure_point") or {}
    ra = (c.get("repair") or {}).get("repair_action") or {}
    tokens = [
        ("et", c.get("event_type")),
        ("mat", pipe.get("material")),
        ("pc", pipe.get("pressure_class")),
        ("dn", pipe.get("steel_dn") or pipe.get("pe_de")),
        ("env", pipe.get("laying_environment")),
        ("fm", fp.get("failure_mode")),
        ("dc", fp.get("direct_cause")),
        ("ic", fp.get("indirect_cause")),
        ("rm", ra.get("repair_method")),
        ("el", (c.get("scene_confirm") or {}).get("emergency_level")),
    ]
    for prefix, val in tokens:
        if not val:
            continue
        h = hashlib.md5(f"{prefix}:{val}".encode("utf-8")).digest()
        bucket = int.from_bytes(h[:4], "big") % dim
        sign = 1.0 if h[4] % 2 == 0 else -1.0
        vec[bucket] += sign
    # L2 normalize
    norm = sum(x * x for x in vec) ** 0.5
    if norm > 0:
        vec = [x / norm for x in vec]
    return vec


# ---- 匹配主流程 ----
def link(
    cases: list[dict],
    jsonl_records: list[dict],
) -> tuple[list[dict], dict[str, Any]]:
    jsonl_fps = [_extract_from_question(r.get("question", "")) for r in jsonl_records]

    # 按指纹把 jsonl records 建索引（exact key: (et, fm, mat, pc, dn)）
    key_index: dict[tuple, list[int]] = defaultdict(list)
    for i, fp in enumerate(jsonl_fps):
        key = (fp.get("event_type"), fp.get("failure_mode"),
               (fp.get("material") or "").replace(" ", ""),
               fp.get("pressure_class"),
               fp.get("steel_dn") or fp.get("pe_de"))
        key_index[key].append(i)

    used_idx: set[int] = set()
    link_log: list[dict] = []

    enriched: list[dict] = []
    for c in cases:
        cfp = _case_fingerprint(c)
        key = (cfp.get("event_type"), cfp.get("failure_mode"),
               (cfp.get("material") or "").replace(" ", ""),
               cfp.get("pressure_class"),
               cfp.get("steel_dn") or cfp.get("pe_de"))
        candidates = [i for i in key_index.get(key, []) if i not in used_idx]
        # 如果 key 匹配失败，再做全表打分 top-k
        if not candidates:
            # 打分所有未用过的
            scored = []
            for i, jfp in enumerate(jsonl_fps):
                if i in used_idx:
                    continue
                s = _match_score(cfp, jfp)
                if s >= 6:
                    scored.append((s, i))
            scored.sort(reverse=True)
            candidates = [i for _, i in scored[:1]]

        think = None
        answer = None
        matched_idx = None
        if candidates:
            matched_idx = candidates[0]
            used_idx.add(matched_idx)
            think = jsonl_records[matched_idx].get("think")
            answer = jsonl_records[matched_idx].get("answer")

        c2 = dict(c)
        c2["think_trace"] = think
        c2["answer"] = answer
        c2["summary"] = build_summary(c2)
        c2["summary_vec"] = feature_hash_vector(c2)
        enriched.append(c2)

        link_log.append({
            "incident_id": c["incident_id"],
            "matched": matched_idx is not None,
            "jsonl_index": matched_idx,
        })

    stats = {
        "total_cases": len(cases),
        "total_jsonl": len(jsonl_records),
        "linked": sum(1 for x in link_log if x["matched"]),
        "unlinked_cases": [x["incident_id"] for x in link_log if not x["matched"]],
        "unused_jsonl": len(jsonl_records) - len(used_idx),
    }
    return enriched, stats


def build_report(stats: dict[str, Any], enriched: list[dict]) -> str:
    L: list[str] = []
    L.append("# jsonl ↔ xlsx 关联报告（6.0.5.4）\n")
    L.append(f"- cases 总数: **{stats['total_cases']}**")
    L.append(f"- jsonl 总数: **{stats['total_jsonl']}**")
    L.append(f"- 成功关联: **{stats['linked']}** ({stats['linked']/stats['total_cases']*100:.1f}%)")
    L.append(f"- 未关联案例: **{len(stats['unlinked_cases'])}**")
    L.append(f"- 未使用 jsonl 记录: **{stats['unused_jsonl']}**")
    L.append("")

    # 事件类型覆盖率
    L.append("## 按事件类型关联率\n")
    by_et_total: Counter[str] = Counter()
    by_et_linked: Counter[str] = Counter()
    for c in enriched:
        et = c.get("event_type") or "未知"
        by_et_total[et] += 1
        if c.get("think_trace"):
            by_et_linked[et] += 1
    L.append("| 事件类型 | 总数 | 已关联 | 关联率 |")
    L.append("|---|---|---|---|")
    for et, n in by_et_total.most_common():
        l = by_et_linked[et]
        L.append(f"| {et} | {n} | {l} | {l/n*100:.1f}% |")
    L.append("")

    # 未关联样本
    if stats["unlinked_cases"]:
        L.append("## 未关联的 case（前 20）\n")
        for cid in stats["unlinked_cases"][:20]:
            L.append(f"- {cid}")
        if len(stats["unlinked_cases"]) > 20:
            L.append(f"- ...（省略 {len(stats['unlinked_cases']) - 20} 条）")
        L.append("")
        L.append("> 未关联通常是 jsonl 合成样本与 xlsx 事实参数不完全对齐（如 jsonl 注入了伪造的伤亡/财产损失描述）。这些 case 在 Phase 9 案例库中仍可独立使用，只是缺少 CoT 推理链。")

    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default=str(DEFAULT_CASES))
    ap.add_argument("--jsonl", default=str(DEFAULT_JSONL))
    ap.add_argument("--enriched", default=str(DEFAULT_ENRICHED))
    ap.add_argument("--report", default=str(DEFAULT_REPORT))
    ap.add_argument("--vec", default=str(DEFAULT_VEC))
    args = ap.parse_args()

    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    jsonl_records = []
    with Path(args.jsonl).open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                jsonl_records.append(json.loads(line))
    print(f"[1/3] {len(cases)} cases + {len(jsonl_records)} jsonl")

    enriched, stats = link(cases, jsonl_records)
    print(f"[2/3] 关联 {stats['linked']}/{stats['total_cases']}")

    Path(args.enriched).write_text(
        json.dumps(enriched, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    Path(args.report).write_text(build_report(stats, enriched), encoding="utf-8")
    # 向量单独导出（enriched 里也有，但单独一份方便后续独立消费）
    vecs = {c["incident_id"]: c["summary_vec"] for c in enriched}
    Path(args.vec).write_text(json.dumps(vecs, ensure_ascii=False), encoding="utf-8")
    print(f"[3/3] 写入 {args.enriched} / {args.report} / {args.vec}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
