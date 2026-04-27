"""Stratified sampling: split 250 IncidentCase records into train/val/regression + few-shot pool.

策略：
- 按 (event_type, pressure_class, emergency_level) 做联合 stratum
- 小于 3 条的 stratum 合并到 "长尾" 桶，确保每个桶至少有 1 条能进入回归集
- 每个 stratum 按 7 : 1.5 : 1.5 切到 train / val / regression
- **回归集保证**: 每个独立 failure_mode 至少有 1 条样本
- few-shot 池: 从 train 中优选字段完整度最高、话术典型的 12-15 条

输出：
- `processed/train.jsonl`       ≈175 条
- `processed/val.jsonl`         ≈37 条
- `processed/regression.jsonl`  ≈38 条 + failure_mode 补全
- `processed/few_shot_pool.jsonl` 12-15 条
- `processed/split_manifest.json` 全局映射 incident_id → split

Usage:
    python backend/scripts/stratified_split.py --seed 42
"""
from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent

DEFAULT_CASES = _BACKEND / "data/cases/processed/cases.json"
OUT_DIR = _BACKEND / "data/cases/processed"


def _stratum_key(case: dict) -> tuple[str, str, str]:
    pipe = (case.get("scene_confirm") or {}).get("pipeline") or {}
    return (
        case.get("event_type") or "未知",
        pipe.get("pressure_class") or "未知",
        (case.get("scene_confirm") or {}).get("emergency_level") or "未知",
    )


def _failure_mode(case: dict) -> str | None:
    fp = (case.get("repair") or {}).get("failure_point") or {}
    return fp.get("failure_mode")


def _completeness_score(case: dict) -> int:
    """字段完整度打分，用于 few-shot 优选。"""
    score = 0
    for path in [
        ("alarm", "alarm_time"),
        ("dispatch", "arrival_time"),
        ("scene_confirm", "leak_location"),
        ("scene_confirm", "pipeline"),
        ("repair", "failure_point"),
        ("repair", "repair_action"),
        ("recovery", "recovery_time"),
    ]:
        node = case
        for k in path:
            node = (node or {}).get(k) if isinstance(node, dict) else None
        if node not in (None, ""):
            score += 1
    # 奖励有完整管道规格
    pipe = (case.get("scene_confirm") or {}).get("pipeline") or {}
    if pipe.get("material") and pipe.get("pressure_class") and pipe.get("burial_depth_m") is not None:
        score += 2
    return score


def stratify(cases: list[dict], seed: int) -> dict[str, list[dict]]:
    rng = random.Random(seed)

    # 构建 stratum
    strata: dict[tuple, list[dict]] = defaultdict(list)
    for c in cases:
        strata[_stratum_key(c)].append(c)

    # 小于 3 条的合并到长尾桶
    large_strata = {k: v for k, v in strata.items() if len(v) >= 3}
    tail = [c for k, v in strata.items() if len(v) < 3 for c in v]
    if tail:
        large_strata[("_TAIL", "_TAIL", "_TAIL")] = tail

    splits: dict[str, list[dict]] = {"train": [], "val": [], "regression": []}
    for k, bucket in large_strata.items():
        bucket = bucket[:]
        rng.shuffle(bucket)
        n = len(bucket)
        n_val = max(1, int(round(n * 0.15)))
        n_reg = max(1, int(round(n * 0.15)))
        # 保证 train 至少 1 条
        n_train = max(1, n - n_val - n_reg)
        # 如果总和超过 n，把多的砍掉
        while n_train + n_val + n_reg > n:
            if n_reg > 1:
                n_reg -= 1
            elif n_val > 1:
                n_val -= 1
            else:
                n_train -= 1
        splits["val"].extend(bucket[:n_val])
        splits["regression"].extend(bucket[n_val:n_val + n_reg])
        splits["train"].extend(bucket[n_val + n_reg:])

    # 回归集 failure_mode 覆盖保证
    regression_ids = {c["incident_id"] for c in splits["regression"]}
    reg_failure_modes = {_failure_mode(c) for c in splits["regression"] if _failure_mode(c)}
    all_failure_modes = {_failure_mode(c) for c in cases if _failure_mode(c)}
    missing = all_failure_modes - reg_failure_modes
    # 把 train 中首个对应 failure_mode 样本移到 regression
    for fm in missing:
        for i, c in enumerate(splits["train"]):
            if _failure_mode(c) == fm:
                splits["regression"].append(splits["train"].pop(i))
                break

    return splits


def pick_few_shot(train: list[dict], n: int = 12) -> list[dict]:
    """按完整度 + 事件类型多样性挑选 few-shot 示例。"""
    # 按完整度降序
    sorted_train = sorted(train, key=lambda c: (-_completeness_score(c),
                                                 c["incident_id"]))
    picked: list[dict] = []
    seen_event_types: set[str] = set()
    # 第一轮：每个事件类型最多 1 条
    for c in sorted_train:
        et = c.get("event_type")
        if et in seen_event_types:
            continue
        picked.append(c)
        seen_event_types.add(et)
        if len(picked) >= n:
            break
    # 第二轮：补齐到 n 条
    if len(picked) < n:
        for c in sorted_train:
            if c in picked:
                continue
            picked.append(c)
            if len(picked) >= n:
                break
    return picked


def write_jsonl(path: Path, items: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for obj in items:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default=str(DEFAULT_CASES))
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--few-shot-n", type=int, default=12)
    args = ap.parse_args()

    cases: list[dict] = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    print(f"[1/4] 加载 {len(cases)} 条案例")

    print(f"[2/4] 分层切分 (seed={args.seed})")
    splits = stratify(cases, args.seed)
    for name, items in splits.items():
        print(f"      {name:11} {len(items)} 条")

    print(f"[3/4] 挑选 few-shot (目标 {args.few_shot_n} 条)")
    few_shot = pick_few_shot(splits["train"], args.few_shot_n)
    event_types = Counter(c["event_type"] for c in few_shot)
    print(f"      few-shot 覆盖 {len(event_types)} 个事件类型")

    print("[4/4] 写文件")
    write_jsonl(OUT_DIR / "train.jsonl", splits["train"])
    write_jsonl(OUT_DIR / "val.jsonl", splits["val"])
    write_jsonl(OUT_DIR / "regression.jsonl", splits["regression"])
    write_jsonl(OUT_DIR / "few_shot_pool.jsonl", few_shot)

    manifest = {
        "seed": args.seed,
        "total": len(cases),
        "counts": {k: len(v) for k, v in splits.items()},
        "few_shot_count": len(few_shot),
        "splits": {
            c["incident_id"]: split
            for split, items in splits.items()
            for c in items
        },
        "few_shot_ids": [c["incident_id"] for c in few_shot],
        "failure_mode_coverage": {
            "total_modes": len({_failure_mode(c) for c in cases if _failure_mode(c)}),
            "regression_modes": len({_failure_mode(c) for c in splits["regression"]
                                     if _failure_mode(c)}),
        },
    }
    (OUT_DIR / "split_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"      {OUT_DIR / 'split_manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
