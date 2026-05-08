"""Case memory store (Phase 6.4 L2 案例记忆).

Hybrid similarity retrieval:
  1. Structured-field weighted matching (倒排索引, exact)
  2. ChromaDB semantic search (bge embedding, fuzzy)
  → RRF fusion → top-k results
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import structlog

from app.cases.loader import load_cases
from app.cases.schema import IncidentCase

log = structlog.get_logger()

# Fields that contribute to structured similarity scoring (权重)
_FIELD_WEIGHTS: dict[str, float] = {
    "event_type": 3.0,
    "failure_mode": 2.5,
    "direct_cause": 2.5,
    "indirect_cause": 2.0,
    "pressure_class": 2.0,
    "pipeline_material": 1.5,
    "severity": 1.5,
    "leak_type": 1.0,
}

# Weight of semantic score vs structured score in RRF fusion
# 0 = structured only, 1 = semantic only
_SEMANTIC_WEIGHT = 0.5


class CaseStore:
    """Hybrid case index: structured-field matching + ChromaDB semantic search."""

    def __init__(self) -> None:
        self._cases: dict[str, IncidentCase] = {}
        self._index: dict[str, list[str]] = {}  # field_value → incident_ids
        self._summaries: dict[str, str] = {}    # incident_id → summary text (for embedding)
        self._chroma_collection = None           # ChromaDB "cases" collection
        self._ready = False

    # ── Build ──

    def ingest(self) -> int:
        """Load 250 cases + build inverted index + ChromaDB semantic collection."""
        try:
            raw = load_cases(prefer_redacted=True)
        except FileNotFoundError:
            log.warning("case files not found, skipping case store init")
            return 0

        for case in raw:
            self._cases[case.incident_id] = case
            # Index key fields for structured matching
            self._index_value(case.incident_id, case.event_type)
            if case.scene_confirm.pipeline:
                self._index_value(case.incident_id, case.scene_confirm.pipeline.pressure_class)
                self._index_value(case.incident_id, case.scene_confirm.pipeline.material)
            if case.repair.failure_point:
                self._index_value(case.incident_id, case.repair.failure_point.failure_mode)
                self._index_value(case.incident_id, case.repair.failure_point.direct_cause)
                self._index_value(case.incident_id, case.repair.failure_point.indirect_cause)
            # Build summary text for semantic embedding
            self._summaries[case.incident_id] = _build_summary(case)

        # Build ChromaDB semantic collection
        self._chroma_collection = _build_chroma_collection(self._summaries)

        self._ready = True
        log.info("case_store_ready", count=len(self._cases), semantic=True)
        return len(self._cases)

    def _index_value(self, incident_id: str, value: str | None) -> None:
        if not value:
            return
        key = value.strip()
        if key:
            self._index.setdefault(key, []).append(incident_id)

    # ── Query ──

    def query(self, context: dict[str, Any], query_text: str = "", top_k: int = 3) -> list[dict[str, Any]]:
        """Hybrid search: structured-field match + semantic embedding → RRF fusion.

        ``context``: {event_type, failure_mode, pressure_class, ...}
        ``query_text``: raw user message for semantic search
        """
        if not self._ready:
            return []

        # ── Structured-field scoring ──
        struct_scores: dict[str, float] = {}
        for field, weight in _FIELD_WEIGHTS.items():
            query_value = _normalize(context.get(field, ""))
            if not query_value:
                continue
            for cid in self._index.get(query_value, []):
                struct_scores[cid] = struct_scores.get(cid, 0.0) + weight

        # ── Semantic scoring via ChromaDB ──
        semantic_scores: dict[str, float] = {}
        if query_text and self._chroma_collection is not None:
            try:
                results = self._chroma_collection.query(
                    query_texts=[query_text],
                    n_results=min(10, self._chroma_collection.count()),
                )
                if results and results["ids"] and results["ids"][0]:
                    for cid, distance in zip(results["ids"][0], results["distances"][0]):
                        # ChromaDB returns cosine distance (0=identical, 2=opposite)
                        # Convert to similarity score: 1.0 → 0.0
                        sim = max(0.0, 1.0 - distance / 2.0)
                        semantic_scores[cid] = sim * 10.0  # scale to match structured range
            except Exception as exc:
                log.warning("case_semantic_search_failed", error=str(exc))

        # ── RRF fusion ──
        fused: dict[str, float] = {}
        all_ids = set(struct_scores.keys()) | set(semantic_scores.keys())
        for cid in all_ids:
            struct = struct_scores.get(cid, 0.0) * (1.0 - _SEMANTIC_WEIGHT)
            sem = semantic_scores.get(cid, 0.0) * _SEMANTIC_WEIGHT
            fused[cid] = struct + sem

        ranked = sorted(fused.items(), key=lambda x: -x[1])[:top_k]

        results: list[dict[str, Any]] = []
        for cid, score in ranked:
            case = self._cases.get(cid)
            if case is None:
                continue
            results.append(_case_to_result(case, score))
        return results

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def count(self) -> int:
        return len(self._cases)


# ── Summary builder ───────────────────────────────────────────────────

def _build_summary(case: IncidentCase) -> str:
    """Build a natural-language summary string for semantic embedding."""
    parts = [f"事件类型: {case.event_type}", f"位置: {case.location}"]
    if case.scene_confirm.pipeline:
        p = case.scene_confirm.pipeline
        if p.material:
            parts.append(f"管材: {p.material}")
        if p.pressure_class:
            parts.append(f"压力等级: {p.pressure_class}")
    if case.repair.failure_point:
        fp = case.repair.failure_point
        if fp.failure_mode:
            parts.append(f"失效模式: {fp.failure_mode}")
        if fp.direct_cause:
            parts.append(f"直接原因: {fp.direct_cause}")
        if fp.indirect_cause:
            parts.append(f"间接原因: {fp.indirect_cause}")
    if case.repair.repair_action and case.repair.repair_action.repair_method:
        parts.append(f"维修方式: {case.repair.repair_action.repair_method}")
    if case.think_trace:
        parts.append(f"处置思路: {case.think_trace[:200]}")
    if case.answer:
        parts.append(f"处置方案: {case.answer[:300]}")
    return "；".join(parts)


# ── ChromaDB collection builder ───────────────────────────────────────

def _build_chroma_collection(summaries: dict[str, str]):
    """Build or refresh the 'cases' ChromaDB collection with semantic embeddings.

    Returns the collection object, or None on failure.
    """
    try:
        import chromadb
        from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
    except ImportError:
        log.warning("chromadb_not_installed", hint="pip install chromadb sentence-transformers")
        return None

    from app.config import get_settings
    settings = get_settings()

    ef = SentenceTransformerEmbeddingFunction(model_name=settings.embedding_model)
    client = chromadb.PersistentClient(path=settings.chroma_persist_dir)

    # Remove old collection if exists
    try:
        client.delete_collection("cases")
    except Exception:
        pass

    collection = client.create_collection(
        name="cases",
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"},
    )

    ids = list(summaries.keys())
    texts = list(summaries.values())
    batch_size = 100
    for i in range(0, len(ids), batch_size):
        batch_ids = ids[i : i + batch_size]
        batch_texts = texts[i : i + batch_size]
        collection.add(ids=batch_ids, documents=batch_texts)

    log.info("cases_chroma_built", count=len(ids))
    return collection


# ── Helpers ───────────────────────────────────────────────────────────

def _normalize(v: Any) -> str:
    s = str(v).strip().lower()
    for ch in "()（） ":
        s = s.replace(ch, "")
    return s


def _case_to_result(case: IncidentCase, score: float) -> dict[str, Any]:
    """Serialize a case to a compact dict for planner injection."""
    return {
        "incident_id": case.incident_id,
        "event_type": case.event_type,
        "location": case.location,
        "pipeline_material": (case.scene_confirm.pipeline.material if case.scene_confirm.pipeline else None),
        "pressure_class": (case.scene_confirm.pipeline.pressure_class if case.scene_confirm.pipeline else None),
        "failure_mode": (case.repair.failure_point.failure_mode if case.repair.failure_point else None),
        "repair_method": (case.repair.repair_action.repair_method if case.repair.repair_action else None),
        "recovery_time": case.recovery.recovery_time,
        "think_trace": (case.think_trace or "")[:500],
        "answer": (case.answer or "")[:600],
        "score": round(score, 1),
    }


# ── Module-level singleton ──

@lru_cache(maxsize=1)
def get_case_store() -> CaseStore:
    store = CaseStore()
    store.ingest()
    return store
