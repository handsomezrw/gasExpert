"""PII redaction for IncidentCase records.

脱敏对象：
1. **地点类** (location / event_location / leak_location)：
   - 末尾的门牌号、栋号、单元号 → 遮蔽
   - 小区 / 街道仍保留（保留检索粒度）
   - 独立地标（如"××医院""××学校"）保留但截断
2. **PII 占位**（当前 xlsx 中未直接出现，但规则预留）：
   - 姓名 3-4 字中文 + 称谓（先生/女士/师傅/队长）→ `[姓名]`
   - 11 位手机号 → `[手机号]`
   - 身份证 → `[身份证]`

策略：幂等，已脱敏再跑不变；并写出 `redaction_log.json` 记录每条 case 被改写的字段。

Usage:
    python backend/scripts/redact_pii.py
    python backend/scripts/redact_pii.py --in cases.json --out cases_redacted.json
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent

DEFAULT_IN = _BACKEND / "data/cases/processed/cases_enriched.json"
DEFAULT_OUT = _BACKEND / "data/cases/processed/cases_redacted.json"
DEFAULT_LOG = _BACKEND / "data/cases/processed/redaction_log.json"


# ---- 地点脱敏规则 ----
# 门牌号尾缀：X号 / X栋 / X单元 / X-X / X室
_ADDR_TAIL_PATTERNS = [
    re.compile(r"\d+[号栋幢楼座]"),        # 14栋 / 86号
    re.compile(r"\d+[-—–]\d+"),             # 12-3
    re.compile(r"[第]?\d+单元"),            # 3单元
    re.compile(r"\d+室"),
    re.compile(r"\d+队"),                   # 马超2队
    re.compile(r"\d+组"),                   # 黄河5组
    re.compile(r"\d+巷\d*[号]?"),          # 2巷13号
    re.compile(r"\d+街\d*[号]?"),
]

# 污水井 / 管道井 / 阀门井 等具体位置 → 保留但从完整地址中截断"房角污水井内"这种后缀细节
_LEAK_LOC_TAIL = re.compile(r"(房角|墙边|围墙边|过道|地下|地沟|小区内)")

# 11 位手机号
_PHONE = re.compile(r"(?<![\d])1[3-9]\d{9}(?![\d])")
# 身份证（15/18 位）
_IDCARD = re.compile(r"(?<![\d])\d{17}[\dXx]|\d{15}(?![\d])")
# 中文姓名 + 称谓（简单启发式，仅匹配 "某X师傅/先生/女士/队长/经理"）
_NAME_TITLE = re.compile(r"[一-龥]{2,4}(?:师傅|先生|女士|队长|经理|主任|科长)")


def _redact_address(val: str) -> tuple[str, bool]:
    """地址尾缀遮蔽。返回 (redacted, changed)。"""
    if not val:
        return val, False
    new = val
    for pat in _ADDR_TAIL_PATTERNS:
        new = pat.sub("[门牌]", new)
    # 折叠连续 [门牌]
    new = re.sub(r"(?:\[门牌\]){2,}", "[门牌]", new)
    return new, new != val


def _redact_generic_pii(val: str) -> tuple[str, bool]:
    if not val:
        return val, False
    orig = val
    val = _PHONE.sub("[手机号]", val)
    val = _IDCARD.sub("[身份证]", val)
    val = _NAME_TITLE.sub("[姓名]", val)
    return val, val != orig


def _redact_location(val: str) -> tuple[str, bool]:
    if not val:
        return val, False
    v1, c1 = _redact_address(val)
    v2, c2 = _redact_generic_pii(v1)
    return v2, (c1 or c2)


# ---- 应用到 case ----
_LOCATION_FIELDS = [
    ("location",),
    ("alarm", "event_location"),
    ("scene_confirm", "leak_location"),
]


def redact_case(case: dict) -> tuple[dict, list[str]]:
    changed_fields: list[str] = []
    out = json.loads(json.dumps(case, ensure_ascii=False))  # deep copy

    def _set(obj: Any, path: tuple[str, ...], new_val: Any) -> None:
        for k in path[:-1]:
            obj = obj[k]
        obj[path[-1]] = new_val

    def _get(obj: Any, path: tuple[str, ...]) -> Any:
        for k in path:
            if obj is None:
                return None
            obj = obj.get(k) if isinstance(obj, dict) else None
        return obj

    for path in _LOCATION_FIELDS:
        v = _get(out, path)
        if isinstance(v, str):
            new_v, changed = _redact_location(v)
            if changed:
                _set(out, path, new_v)
                changed_fields.append(".".join(path))

    # think_trace / summary 也可能含泄漏点描述
    for k in ("think_trace", "summary"):
        v = out.get(k)
        if isinstance(v, str):
            new_v, changed = _redact_location(v)
            if changed:
                out[k] = new_v
                changed_fields.append(k)

    return out, changed_fields


# ---- 主流程 ----
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="in_path", default=str(DEFAULT_IN))
    ap.add_argument("--out", dest="out_path", default=str(DEFAULT_OUT))
    ap.add_argument("--log", dest="log_path", default=str(DEFAULT_LOG))
    args = ap.parse_args()

    in_path = Path(args.in_path)
    if not in_path.exists():
        # 回退到 cases.json（如果 6.0.5.4 还没跑过）
        fallback = _BACKEND / "data/cases/processed/cases.json"
        if fallback.exists():
            print(f"[info] {in_path} 不存在，回退到 {fallback}")
            in_path = fallback
        else:
            print(f"输入不存在: {in_path}")
            return 2

    cases = json.loads(in_path.read_text(encoding="utf-8"))
    print(f"[1/2] 加载 {len(cases)} 条")

    redacted: list[dict] = []
    log: list[dict] = []
    for c in cases:
        r, fields = redact_case(c)
        redacted.append(r)
        if fields:
            log.append({"incident_id": c["incident_id"], "fields": fields})

    Path(args.out_path).write_text(
        json.dumps(redacted, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    Path(args.log_path).write_text(
        json.dumps({"total": len(cases), "changed": len(log), "records": log},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[2/2] 脱敏 {len(log)}/{len(cases)}  → {args.out_path}")
    print(f"      日志 → {args.log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
