"""Cross-encoder reranker — uses sentence-transformers CrossEncoder.

Falls back to pass-through if the model cannot be loaded.
"""

from __future__ import annotations

import structlog

from app.config import get_settings

logger = structlog.get_logger()


class Reranker:
    """Score-based document reranker using a cross-encoder model.

    Model is loaded lazily on first ``rerank()`` call to avoid startup cost
    when RAG is not used.  If the model fails to load, the reranker degrades
    to a pass-through that returns documents in their original order.
    """

    def __init__(self, model_name: str | None = None):
        settings = get_settings()
        self.model_name = model_name or settings.reranker_model
        self._model = None
        self._load_failed = False

    def _load_model(self):
        if self._load_failed:
            return
        try:
            from sentence_transformers import CrossEncoder

            logger.info("reranker_loading", model=self.model_name)
            self._model = CrossEncoder(self.model_name)
            logger.info("reranker_loaded", model=self.model_name)
        except ImportError:
            logger.warning("sentence_transformers_not_installed",
                           hint="pip install sentence-transformers")
            self._load_failed = True
        except Exception as exc:
            logger.error("reranker_load_failed", error=str(exc))
            self._load_failed = True

    def rerank(
        self,
        query: str,
        documents: list[dict],
        top_k: int = 5,
    ) -> list[dict]:
        """Rerank documents by relevance to *query*.

        Args:
            query: The user query.
            documents: List of chunk dicts, each must have a ``"text"`` key.
            top_k: Number of top results to return.

        Returns:
            Reranked list of chunk dicts (most relevant first), length <= top_k.
        """
        if not documents:
            return []

        if self._model is None:
            self._load_model()

        if self._model is None:
            logger.info("reranker_fallback_passthrough")
            return documents[:top_k]

        pairs = [(query, doc["text"]) for doc in documents]

        try:
            scores = self._model.predict(pairs)
            scored = list(zip(documents, scores))
            scored.sort(key=lambda x: x[1], reverse=True)
            return [doc for doc, _ in scored[:top_k]]
        except Exception as exc:
            logger.error("reranker_score_error", error=str(exc))
            return documents[:top_k]
