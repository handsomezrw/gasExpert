"""Cold-start data loader for the Phase 9 case store.

接口契约：所有下游消费者（案例召回、few-shot 注入、微调脚本）都通过这里加载数据，
不直接读 JSON 文件。这样当 Phase 9 换真正的存储（Postgres + Chroma）时只改这里。

当前实现：
- 从 `data/cases/processed/` 读取已规整好的 JSON / JSONL
- 案例默认使用脱敏版本 (`cases_redacted.json`)，回退到 `cases_enriched.json` / `cases.json`
- 向量使用 `case_summary_vectors.json`（6.0.5.4 产出的 feature-hash 占位，Phase 9 替换为 bge）

调用方示例：
    from app.cases.loader import load_cases, load_few_shot_pool, get_vector

    cases = load_cases()               # list[IncidentCase]
    few_shot = load_few_shot_pool()    # list[IncidentCase]
    vec = get_vector("INC0001")        # list[float] | None
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Literal

from app.cases.schema import IncidentCase

log = logging.getLogger(__name__)

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_PROCESSED = _BACKEND_ROOT / "data/cases/processed"

SplitName = Literal["train", "val", "regression"]


# ---- 文件定位（按优先级回退） ----
def _resolve_cases_file(prefer_redacted: bool = True) -> Path:
    candidates: list[Path] = []
    if prefer_redacted:
        candidates.append(_PROCESSED / "cases_redacted.json")
    candidates.extend([
        _PROCESSED / "cases_enriched.json",
        _PROCESSED / "cases.json",
    ])
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(
        f"未找到案例文件，请先运行 6.0.5.1 解析脚本。尝试过: {[str(p) for p in candidates]}"
    )


# ---- 对外 API ----
@lru_cache(maxsize=1)
def load_cases(prefer_redacted: bool = True) -> list[IncidentCase]:
    """Load all incident cases as validated Pydantic models (cached)."""
    path = _resolve_cases_file(prefer_redacted)
    raw = json.loads(path.read_text(encoding="utf-8"))
    log.info("loaded %d cases from %s", len(raw), path.name)
    return [IncidentCase.model_validate(r) for r in raw]


def iter_cases(prefer_redacted: bool = True) -> Iterable[IncidentCase]:
    yield from load_cases(prefer_redacted)


def get_case(incident_id: str, prefer_redacted: bool = True) -> IncidentCase | None:
    for c in load_cases(prefer_redacted):
        if c.incident_id == incident_id:
            return c
    return None


@lru_cache(maxsize=1)
def load_few_shot_pool() -> list[IncidentCase]:
    """Load curated few-shot examples for planner prompt injection."""
    path = _PROCESSED / "few_shot_pool.jsonl"
    if not path.exists():
        log.warning("few_shot_pool.jsonl not found, returning empty list")
        return []
    out: list[IncidentCase] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(IncidentCase.model_validate_json(line))
    return out


@lru_cache(maxsize=1)
def load_split_ids() -> dict[str, SplitName]:
    """incident_id → split name, derived from split_manifest.json."""
    manifest_path = _PROCESSED / "split_manifest.json"
    if not manifest_path.exists():
        return {}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return manifest.get("splits", {})


def load_split(split: SplitName) -> list[IncidentCase]:
    """Load train/val/regression split as IncidentCase list."""
    path = _PROCESSED / f"{split}.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"split file missing: {path}")
    out: list[IncidentCase] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(IncidentCase.model_validate_json(line))
    return out


@lru_cache(maxsize=1)
def load_vectors() -> dict[str, list[float]]:
    """incident_id → summary vector (feature-hash, Phase 9 将换为 bge)."""
    path = _PROCESSED / "case_summary_vectors.json"
    if not path.exists():
        log.warning("case_summary_vectors.json not found")
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def get_vector(incident_id: str) -> list[float] | None:
    return load_vectors().get(incident_id)


# ---- Phase 9 占位：案例库接入钩子 ----
def ingest_into_case_store() -> int:  # pragma: no cover
    """冷启动批量入库钩子。Phase 9 实现真正的 Postgres + Chroma 写入。

    现阶段只做 dry-run：验证数据能被 schema 校验通过，返回条数。
    """
    cases = load_cases()
    log.info("[dry-run] would ingest %d cases into case store", len(cases))
    # TODO(Phase 9): 写入 Postgres 表 + 同步向量到 Chroma collection='cases'
    return len(cases)
