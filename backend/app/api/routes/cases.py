"""Case data field options endpoint (for frontend dropdown suggestions).

Reads enum_distributions.json from Phase 6.0.5.2 data audit.
"""

import json
from pathlib import Path

from fastapi import APIRouter

router = APIRouter()

_OPTIONS_PATH = (
    Path(__file__).resolve().parents[3]
    / "data/cases/processed/enum_distributions.json"
)

_cached_options: dict | None = None


def _load_options() -> dict:
    global _cached_options
    if _cached_options is not None:
        return _cached_options
    if _OPTIONS_PATH.exists():
        _cached_options = json.loads(_OPTIONS_PATH.read_text(encoding="utf-8"))
    else:
        _cached_options = {}
    return _cached_options


# Flattened field map: frontend field key → JSON path
_FIELD_MAP = {
    "event_type": "event_type",
    "material": "scene_confirm.pipeline.material",
    "pressure_class": "scene_confirm.pipeline.pressure_class",
    "failure_mode": "repair.failure_point.failure_mode",
    "direct_cause": "repair.failure_point.direct_cause",
    "indirect_cause": "repair.failure_point.indirect_cause",
    "repair_method": "repair.repair_action.repair_method",
    "emergency_level": "alarm.emergency_level",
    "laying_environment": "scene_confirm.pipeline.laying_environment",
}


@router.get("/cases/field-options")
async def get_field_options():
    """Return top-N common values for each report-form field."""
    options = _load_options()
    result: dict[str, list[dict]] = {}

    for frontend_key, json_path in _FIELD_MAP.items():
        dist: dict[str, int] = options.get(json_path, {})
        # Sort by count desc, take top 10
        sorted_items = sorted(dist.items(), key=lambda x: -x[1])[:10]
        result[frontend_key] = [
            {"value": k, "count": v} for k, v in sorted_items
        ]

    # Severity options (not from data, fixed)
    result["severity"] = [
        {"value": "pinhole", "label": "针孔泄漏 (pinhole)", "count": 0},
        {"value": "crack", "label": "裂缝泄漏 (crack)", "count": 0},
        {"value": "rupture", "label": "管道破裂 (rupture)", "count": 0},
    ]

    return result
