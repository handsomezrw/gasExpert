"""Hybrid retriever: vector search + BM25 + RRF fusion + reranker.

Architecture:
    Query ──┬──→ ChromaDB vector search (top-K)  ──┐
            │                                        ├─→ RRF fusion ─→ Reranker ─→ top-N results
            └──→ BM25 keyword search (top-K)    ──┘

Module-level singleton: call ``init_retriever()`` at startup and
``get_retriever()`` in nodes.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import structlog

from app.config import get_settings
from app.rag.reranker import Reranker

logger = structlog.get_logger()

_retriever: HybridRetriever | None = None


# ── Public API ───────────────────────────────────────────────────────

def get_retriever() -> HybridRetriever | None:
    """Return the module-level retriever singleton (``None`` if not initialised)."""
    return _retriever


def init_retriever() -> bool:
    """Initialise the hybrid retriever from persisted indices.

    Returns ``True`` if the retriever is ready, ``False`` otherwise (missing
    indices, missing dependencies, etc.).
    """
    global _retriever
    settings = get_settings()

    chunks_path = Path(settings.rag_chunks_path)
    if not chunks_path.exists():
        logger.info("rag_chunks_not_found", path=str(chunks_path),
                     hint="Run 'python -m app.rag.ingest' first")
        return False

    try:
        import chromadb
        from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
    except ImportError:
        logger.warning("rag_deps_not_installed", hint="pip install -r requirements-rag.txt")
        return False

    try:
        chunks_data: list[dict] = json.loads(chunks_path.read_text(encoding="utf-8"))
        if not chunks_data:
            logger.warning("rag_chunks_empty")
            return False

        ef = SentenceTransformerEmbeddingFunction(model_name=settings.embedding_model)
        client = chromadb.PersistentClient(path=settings.chroma_persist_dir)
        collection = client.get_collection(
            name=settings.rag_collection_name,
            embedding_function=ef,
        )
        logger.info("chroma_loaded", name=settings.rag_collection_name, count=collection.count())

        bm25_index = BM25Index(chunks_data)
        logger.info("bm25_index_built", docs=len(chunks_data))

        reranker = Reranker() if settings.rag_enable_reranker else None

        _retriever = HybridRetriever(
            collection=collection,
            bm25_index=bm25_index,
            reranker=reranker,
            chunks_lookup={c["id"]: c for c in chunks_data},
        )
        logger.info("hybrid_retriever_ready")
        return True

    except Exception as exc:
        logger.error("retriever_init_failed", error=str(exc))
        return False


# ── BM25 Index wrapper ───────────────────────────────────────────────

class BM25Index:
    """Thin wrapper around ``rank_bm25.BM25Okapi`` with jieba tokenisation."""

    def __init__(self, chunks: list[dict]):
        from rank_bm25 import BM25Okapi
        import jieba

        self._chunks = chunks
        self._ids = [c["id"] for c in chunks]

        tokenized = [list(jieba.cut(c["text"])) for c in chunks]
        self._bm25 = BM25Okapi(tokenized)
        self._jieba = jieba

    def search(self, query: str, top_k: int = 20) -> list[str]:
        """Return chunk IDs ranked by BM25 score."""
        tokens = list(self._jieba.cut(query))
        scores = self._bm25.get_scores(tokens)

        ranked = sorted(
            zip(self._ids, scores), key=lambda x: x[1], reverse=True
        )
        return [cid for cid, _ in ranked[:top_k]]


# ── RRF fusion ───────────────────────────────────────────────────────

def rrf_fusion(ranked_lists: list[list[str]], k: int = 60) -> list[str]:
    """Reciprocal Rank Fusion — merge multiple ranked ID lists."""
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, doc_id in enumerate(ranked):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    return [doc_id for doc_id, _ in sorted(scores.items(), key=lambda x: x[1], reverse=True)]


# ── HybridRetriever ──────────────────────────────────────────────────

class HybridRetriever:
    """Two-stage retrieval: parallel vector + BM25, then reranker."""

    def __init__(
        self,
        collection,
        bm25_index: BM25Index,
        reranker: Reranker | None,
        chunks_lookup: dict[str, dict],
    ):
        self._collection = collection
        self._bm25 = bm25_index
        self._reranker = reranker
        self._chunks = chunks_lookup

    async def retrieve(self, query: str, top_k: int | None = None) -> list[dict]:
        """Run the full hybrid retrieval pipeline.

        Returns a list of chunk dicts with keys: id, text, source, page, heading, score.
        """
        settings = get_settings()
        if top_k is None:
            top_k = settings.rag_final_top_k

        loop = asyncio.get_event_loop()

        vector_ids, bm25_ids = await asyncio.gather(
            loop.run_in_executor(None, self._vector_search, query, settings.rag_vector_top_k),
            loop.run_in_executor(None, self._bm25.search, query, settings.rag_bm25_top_k),
        )

        fused_ids = rrf_fusion([vector_ids, bm25_ids])

        candidates = [self._chunks[cid] for cid in fused_ids if cid in self._chunks]

        if not candidates:
            return []

        if self._reranker is not None:
            reranked = await loop.run_in_executor(
                None, self._reranker.rerank, query, candidates, top_k
            )
            return reranked

        return candidates[:top_k]

    def _vector_search(self, query: str, top_k: int) -> list[str]:
        """ChromaDB semantic search → ranked chunk IDs."""
        try:
            results = self._collection.query(
                query_texts=[query],
                n_results=min(top_k, self._collection.count()),
            )
            return results["ids"][0] if results["ids"] else []
        except Exception as exc:
            logger.error("vector_search_error", error=str(exc))
            return []

    def format_docs_for_state(self, docs: list[dict]) -> list[str]:
        """Format retrieved chunks into strings for AgentState.retrieved_docs."""
        formatted = []
        for doc in docs:
            source = doc.get("source", "unknown")
            heading = doc.get("heading", "")
            page = doc.get("page", "?")
            header = f"[来源: {source} | 第{page}页"
            if heading:
                header += f" | {heading}"
            header += "]"
            formatted.append(f"{header}\n{doc['text']}")
        return formatted
