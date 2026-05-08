"""RAG retrieval recall evaluation script.

Usage:
    cd backend
    .venv/Scripts/python scripts/eval_retrieval.py               # basic eval
    .venv/Scripts/python scripts/eval_retrieval.py --llm         # LLM auto-scoring
    .venv/Scripts/python scripts/eval_retrieval.py --query "PE管热熔温度"  # single query

Output:
    - Per-query: retrieved top-5 chunks with metadata
    - Summary: precision@5, relevant count
    - Optional: LLM relevance judgment (requires OPENAI_API_KEY)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Ensure backend is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# ── Test queries (covering common gas emergency regulation topics) ───

TEST_QUERIES = [
    # 抢修作业
    {
        "id": "Q1",
        "query": "燃气管道泄漏后抢修人员应在多少分钟内到达现场",
        "expected_keywords": ["30分钟", "到达", "抢修"],
    },
    {
        "id": "Q2",
        "query": "PE管道抢修应使用什么连接方式",
        "expected_keywords": ["热熔", "电熔", "PE"],
    },
    {
        "id": "Q3",
        "query": "燃气管道针孔状泄漏的临时处置方法是什么",
        "expected_keywords": ["堵漏卡", "夹具", "临时封堵"],
    },
    {
        "id": "Q4",
        "query": "抢修现场可燃气体浓度达到爆炸下限多少时应停止作业",
        "expected_keywords": ["20%", "爆炸下限", "LEL"],
    },
    # 运行管理
    {
        "id": "Q5",
        "query": "中压燃气管道的巡线检查周期是多少",
        "expected_keywords": ["每周", "每月", "巡线", "中压"],
    },
    {
        "id": "Q6",
        "query": "燃气管道运行压力等级如何划分",
        "expected_keywords": ["低压", "中压", "次高压", "高压", "MPa"],
    },
    {
        "id": "Q7",
        "query": "高压和次高压管道每日应巡检几次",
        "expected_keywords": ["每日", "巡检", "一次"],
    },
    # 安全防护
    {
        "id": "Q8",
        "query": "抢修作业人员在可燃气体浓度超标时应佩戴什么防护装备",
        "expected_keywords": ["正压式空气呼吸器", "防静电", "工作服"],
    },
    {
        "id": "Q9",
        "query": "燃气设施运行维护应遵循什么方针",
        "expected_keywords": ["安全第一", "预防为主", "综合治理"],
    },
    {
        "id": "Q10",
        "query": "PE管道热熔操作的环境温度范围是多少",
        "expected_keywords": ["-5℃", "40℃", "环境温度"],
    },
]


@dataclass
class EvalResult:
    query_id: str
    query: str
    expected_keywords: list[str]
    chunks: list[dict] = field(default_factory=list)
    keyword_hits: int = 0
    llm_verdict: str = ""  # "relevant" | "partial" | "irrelevant"


# ── Evaluation logic ──────────────────────────────────────────────────


def keyword_match(chunk_text: str, keywords: list[str]) -> bool:
    """Check if any expected keyword appears in the chunk text."""
    return any(kw in chunk_text for kw in keywords)


async def run_eval(use_llm: bool = False) -> list[EvalResult]:
    """Run retrieval evaluation across all test queries."""
    from app.rag.retriever import get_retriever

    retriever = get_retriever()
    if retriever is None:
        print("[ERROR] Retriever not initialised. Make sure the app has started or run ingest first.")
        return []

    results: list[EvalResult] = []

    for tq in TEST_QUERIES:
        er = EvalResult(
            query_id=tq["id"],
            query=tq["query"],
            expected_keywords=tq["expected_keywords"],
        )

        # Retrieve top-5
        try:
            docs = await retriever.retrieve(tq["query"], top_k=5)
        except Exception as exc:
            print(f"  [ERROR] {tq['id']}: {exc}")
            results.append(er)
            continue

        keyword_hits = 0
        for doc in docs:
            if keyword_match(doc["text"], tq["expected_keywords"]):
                keyword_hits += 1

        er.chunks = docs
        er.keyword_hits = keyword_hits

        # Optional LLM scoring
        if use_llm and docs:
            er.llm_verdict = await _llm_judge(tq["query"], docs)

        results.append(er)

    return results


async def _llm_judge(query: str, docs: list[dict]) -> str:
    """Ask LLM to judge if the retrieved docs are relevant to the query."""
    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        from app.agent.llm import get_llm

        doc_text = "\n\n---\n".join(
            f"[{d['source']} p{d['page']}] {d['text'][:300]}" for d in docs
        )
        prompt = (
            "你是一个检索质量评估专家。判断以下检索结果是否与问题相关。\n\n"
            f"问题：{query}\n\n"
            f"检索结果（top-5）：\n{doc_text}\n\n"
            "请仅输出一个词：relevant（相关）、partial（部分相关）、或 irrelevant（不相关）。"
        )
        llm = get_llm()
        response = await llm.ainvoke([SystemMessage(content=prompt), HumanMessage(content="请判断")])
        text = response.content.strip().lower()
        if "relevant" in text:
            return "relevant"
        elif "partial" in text:
            return "partial"
        elif "irrelevant" in text:
            return "irrelevant"
        return text[:30]
    except Exception as exc:
        return f"error: {exc}"


# ── Single query mode ─────────────────────────────────────────────────


async def single_query(query: str):
    """Run retrieval for a single query and print results."""
    from app.rag.retriever import get_retriever

    retriever = get_retriever()
    if retriever is None:
        print("[ERROR] Retriever not initialised.")
        return

    print(f"\n查询: {query}\n{'=' * 60}")
    docs = await retriever.retrieve(query, top_k=5)

    if not docs:
        print("  无检索结果")
        return

    for i, doc in enumerate(docs, 1):
        print(f"\n--- #{i} [来源: {doc['source']} | 第{doc['page']}页] ---")
        if doc.get("heading"):
            print(f"  章节: {doc['heading']}")
        print(f"  {doc['text'][:300]}")


# ── Report printing ───────────────────────────────────────────────────


def print_report(results: list[EvalResult]):
    """Print human-readable evaluation report."""
    print("\n" + "=" * 70)
    print("RAG 检索召回率评估报告")
    print("=" * 70)

    total_kw_hits = 0
    total_chunks = 0
    relevant_count = 0

    for er in results:
        total_chunks += len(er.chunks)
        total_kw_hits += er.keyword_hits
        rel = "✅" if er.keyword_hits > 0 else "❌"

        print(f"\n{rel} {er.query_id}: {er.query}")
        print(f"   关键词命中: {er.keyword_hits}/{len(er.chunks)}")
        if er.llm_verdict:
            print(f"   LLM 判断: {er.llm_verdict}")

        for i, doc in enumerate(er.chunks, 1):
            kw_match = keyword_match(doc["text"], er.expected_keywords)
            marker = " ★" if kw_match else ""
            print(f"   #{i} [{doc['source']} p{doc['page']}]{marker} {doc['text'][:80].replace(chr(10), ' ')}...")

        if er.keyword_hits > 0:
            relevant_count += 1

    # Summary
    print("\n" + "-" * 70)
    print("总结")
    print("-" * 70)
    n = len(results)
    print(f"  查询总数: {n}")
    print(f"  至少命中 1 个关键字的查询: {relevant_count}/{n} ({relevant_count / n * 100:.0f}%)")
    print(f"  总检索 chunk 数: {total_chunks}")
    print(f"  命中关键字的 chunk 数: {total_kw_hits}")
    if total_chunks > 0:
        print(f"  Precision@5 (关键词): {total_kw_hits / total_chunks * 100:.1f}%")

    if any(er.llm_verdict for er in results):
        llm_rel = sum(1 for er in results if er.llm_verdict == "relevant")
        llm_partial = sum(1 for er in results if er.llm_verdict == "partial")
        print(f"  LLM 评分: {llm_rel} 相关, {llm_partial} 部分相关, {n - llm_rel - llm_partial} 不相关")

    print("\n说明: ★ 表示该 chunk 包含预期关键词。关键词匹配是粗粒度的，仅供快速筛查。")


# ── Main ──────────────────────────────────────────────────────────────


async def main():
    parser = argparse.ArgumentParser(description="RAG retrieval recall evaluation")
    parser.add_argument("--llm", action="store_true", help="Use LLM for relevance judgment")
    parser.add_argument("--query", type=str, help="Run a single query")
    args = parser.parse_args()

    # Init retriever (same way as app startup)
    from app.rag.retriever import init_retriever

    ready = init_retriever()
    if not ready:
        print("[ERROR] Retriever initialisation failed.")
        print("Make sure you have run: python -m app.rag.ingest")
        sys.exit(1)

    if args.query:
        await single_query(args.query)
        return

    print(f"\nRunning evaluation on {len(TEST_QUERIES)} test queries...")
    if args.llm:
        print("LLM scoring enabled (may be slow and consume API credits)")
    results = await run_eval(use_llm=args.llm)
    print_report(results)


if __name__ == "__main__":
    asyncio.run(main())
