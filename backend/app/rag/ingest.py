"""Document ingestion pipeline — PDF/TXT -> chunks -> ChromaDB + BM25 index.

Usage:
    cd backend
    .venv\\Scripts\\python -m app.rag.ingest                       # ingest data/docs/
    .venv\\Scripts\\python -m app.rag.ingest --docs-dir ./my_docs   # custom dir
    .venv\\Scripts\\python -m app.rag.ingest --create-sample        # create sample doc for testing
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import structlog

from app.config import get_settings

logger = structlog.get_logger()

# ── Regex patterns for Chinese regulation documents ───────────────────

_CHAPTER_RE = re.compile(
    r"(?:^|\n)"
    r"(第[一二三四五六七八九十百零\d]+[章节篇]"
    r"|附录\s*[A-Z]"
    r"|\d+(?:\.\d+){0,2}\s)"
)
_CLAUSE_RE = re.compile(r"(?:^|\n)(\d+\.\d+(?:\.\d+)?\s)")


# ── Text extraction ──────────────────────────────────────────────────

def extract_text(file_path: Path) -> list[dict]:
    """Extract text from a PDF or TXT file. Returns list of {page, text}."""
    suffix = file_path.suffix.lower()

    if suffix == ".pdf":
        return _extract_pdf(file_path)
    if suffix in (".txt", ".md"):
        text = file_path.read_text(encoding="utf-8")
        return [{"page": 1, "text": text}]

    logger.warning("unsupported_file_type", path=str(file_path), suffix=suffix)
    return []


def _extract_pdf(file_path: Path) -> list[dict]:
    try:
        import fitz  # pymupdf
    except ImportError:
        logger.error("pymupdf_not_installed", hint="pip install pymupdf")
        return []

    pages = []
    with fitz.open(str(file_path)) as doc:
        for i, page in enumerate(doc):
            text = page.get_text("text")
            if text.strip():
                pages.append({"page": i + 1, "text": text})
    return pages


# ── Chunking ─────────────────────────────────────────────────────────

def chunk_document(
    pages: list[dict],
    source: str,
    max_size: int = 500,
    overlap: int = 100,
) -> list[dict]:
    """Split extracted pages into retrieval-friendly chunks.

    Strategy:
    1. Merge all pages into continuous text (preserving page boundaries)
    2. Split by regulation clause patterns (X.X.X)
    3. Merge small fragments, split oversized ones with overlap
    4. Attach metadata (source, page range, section heading)
    """
    full_text = ""
    page_boundaries: list[tuple[int, int]] = []  # (char_offset, page_num)
    for p in pages:
        page_boundaries.append((len(full_text), p["page"]))
        full_text += p["text"] + "\n"

    raw_sections = _split_by_clauses(full_text)

    chunks: list[dict] = []
    chunk_seq = 0  # monotonic — avoids DuplicateID when frag[:100]+page collide (common in GB tables)
    for section_text in raw_sections:
        text = section_text.strip()
        if not text:
            continue

        if len(text) <= max_size:
            fragments = [text]
        else:
            fragments = _split_with_overlap(text, max_size, overlap)

        for frag in fragments:
            offset = full_text.find(frag[:80])
            page = _resolve_page(offset, page_boundaries) if offset >= 0 else 0
            heading = _extract_heading(frag)

            chunk_id = hashlib.md5(
                f"{source}:{chunk_seq}:{page}:{frag}".encode()
            ).hexdigest()[:12]
            chunk_seq += 1

            chunks.append({
                "id": f"chunk_{chunk_id}",
                "text": frag,
                "source": source,
                "page": page,
                "heading": heading,
            })

    merged = _merge_small_chunks(chunks, min_size=80, max_size=max_size)
    return merged


def _split_by_clauses(text: str) -> list[str]:
    """Split text by regulation clause numbers (e.g. 3.2.1)."""
    parts = _CLAUSE_RE.split(text)
    if len(parts) <= 1:
        parts = _CHAPTER_RE.split(text)
    if len(parts) <= 1:
        return [text]

    sections = []
    i = 0
    while i < len(parts):
        if _CLAUSE_RE.match(parts[i]) or _CHAPTER_RE.match(parts[i]):
            section = parts[i]
            if i + 1 < len(parts):
                section += parts[i + 1]
                i += 2
            else:
                i += 1
            sections.append(section)
        else:
            if parts[i].strip():
                sections.append(parts[i])
            i += 1
    return sections


def _split_with_overlap(text: str, max_size: int, overlap: int) -> list[str]:
    """Split long text into overlapping chunks by sentence boundaries."""
    sentences = re.split(r"(?<=[。！？\n])", text)
    fragments: list[str] = []
    current = ""

    for sent in sentences:
        if len(current) + len(sent) > max_size and current:
            fragments.append(current.strip())
            keep = max(0, len(current) - overlap)
            current = current[keep:] + sent
        else:
            current += sent

    if current.strip():
        fragments.append(current.strip())
    return fragments


def _merge_small_chunks(
    chunks: list[dict], min_size: int, max_size: int
) -> list[dict]:
    """Merge adjacent chunks that are too small."""
    if not chunks:
        return []

    merged: list[dict] = [chunks[0]]
    for chunk in chunks[1:]:
        prev = merged[-1]
        if len(prev["text"]) < min_size and len(prev["text"]) + len(chunk["text"]) <= max_size:
            prev["text"] += "\n" + chunk["text"]
            if chunk.get("heading") and not prev.get("heading"):
                prev["heading"] = chunk["heading"]
        else:
            merged.append(chunk)
    return merged


def _resolve_page(offset: int, boundaries: list[tuple[int, int]]) -> int:
    page = 0
    for char_off, page_num in boundaries:
        if char_off <= offset:
            page = page_num
        else:
            break
    return page


def _extract_heading(text: str) -> str:
    """Try to extract a section heading from the beginning of a chunk."""
    first_line = text.split("\n")[0].strip()[:80]
    if _CLAUSE_RE.match(first_line) or _CHAPTER_RE.match(first_line):
        return first_line
    return ""


# ── Index building ───────────────────────────────────────────────────

def build_chroma_collection(chunks: list[dict], settings=None):
    """Build or update ChromaDB collection from chunks."""
    try:
        import chromadb
        from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
    except ImportError:
        logger.error("chromadb_or_st_not_installed", hint="pip install -r requirements-rag.txt")
        raise

    if settings is None:
        settings = get_settings()

    ef = SentenceTransformerEmbeddingFunction(
        model_name=settings.embedding_model,
    )

    client = chromadb.PersistentClient(path=settings.chroma_persist_dir)

    try:
        client.delete_collection(settings.rag_collection_name)
    except Exception:
        pass

    collection = client.create_collection(
        name=settings.rag_collection_name,
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"},
    )

    batch_size = 100
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        collection.add(
            ids=[c["id"] for c in batch],
            documents=[c["text"] for c in batch],
            metadatas=[
                {"source": c["source"], "page": c["page"], "heading": c["heading"]}
                for c in batch
            ],
        )
    logger.info("chroma_collection_built", count=len(chunks), name=settings.rag_collection_name)
    return collection


def save_bm25_chunks(chunks: list[dict], settings=None):
    """Save chunks to JSON for BM25 index reconstruction at startup."""
    if settings is None:
        settings = get_settings()

    path = Path(settings.rag_chunks_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    data = [
        {"id": c["id"], "text": c["text"], "source": c["source"],
         "page": c["page"], "heading": c["heading"]}
        for c in chunks
    ]
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("bm25_chunks_saved", path=str(path), count=len(data))


# ── Main ingestion entry point ───────────────────────────────────────

def ingest_documents(docs_dir: str = "./data/docs"):
    """Parse all PDF/TXT documents in a directory and build retrieval indices."""
    settings = get_settings()
    docs_path = Path(docs_dir)

    if not docs_path.exists():
        docs_path.mkdir(parents=True, exist_ok=True)
        logger.warning("docs_dir_created_empty", path=str(docs_path))
        print(f"[ingest] Created empty docs directory: {docs_path}")
        print("[ingest] Place PDF or TXT files there, then run again.")
        return

    files = list(docs_path.glob("*.pdf")) + list(docs_path.glob("*.txt")) + list(docs_path.glob("*.md"))
    if not files:
        print(f"[ingest] No PDF/TXT/MD files found in {docs_path}")
        print("[ingest] Place documents there, then run again.")
        return

    print(f"[ingest] Found {len(files)} document(s) in {docs_path}")

    all_chunks: list[dict] = []
    for f in files:
        print(f"  - Processing: {f.name}")
        pages = extract_text(f)
        if not pages:
            print(f"    WARNING: No text extracted from {f.name}")
            continue

        total_chars = sum(len(p["text"]) for p in pages)
        chunks = chunk_document(
            pages,
            source=f.name,
            max_size=settings.rag_chunk_size,
            overlap=settings.rag_chunk_overlap,
        )
        print(f"    Pages: {len(pages)}, Chars: {total_chars}, Chunks: {len(chunks)}")
        all_chunks.extend(chunks)

    if not all_chunks:
        print("[ingest] No chunks produced. Check document contents.")
        return

    print(f"\n[ingest] Total chunks: {len(all_chunks)}")
    print("[ingest] Building ChromaDB collection (downloading embedding model on first run)...")
    build_chroma_collection(all_chunks, settings)

    print("[ingest] Saving BM25 chunks JSON...")
    save_bm25_chunks(all_chunks, settings)

    print(f"\n[ingest] Done! Indices saved to:")
    print(f"  - ChromaDB: {settings.chroma_persist_dir}")
    print(f"  - BM25 JSON: {settings.rag_chunks_path}")


# ── Sample document generator ────────────────────────────────────────

SAMPLE_REGULATION = """\
城镇燃气设施运行、维护和抢修安全技术规程（节选）

第1章 总则

1.0.1 为规范城镇燃气设施的运行、维护和抢修安全管理，保障燃气供应安全和公共安全，制定本规程。

1.0.2 本规程适用于城镇燃气设施的运行管理、维护保养和事故抢修。

1.0.3 城镇燃气设施的运行、维护和抢修应遵循"安全第一、预防为主、综合治理"的方针。

第2章 基本规定

2.1 一般规定

2.1.1 燃气经营企业应建立健全安全生产责任制度，明确各级各岗位的安全生产职责。

2.1.2 燃气设施的运行、维护和抢修作业人员应经过专业培训，取得相应的资格证书后方可上岗。

2.1.3 燃气设施运行单位应建立设施运行台账，记录设施基本信息、运行状况、维护记录和检测数据。

2.2 应急管理

2.2.1 燃气经营企业应编制燃气事故应急预案，并定期组织演练。应急预案应包括：应急组织机构、应急响应程序、应急资源保障、善后处理等内容。

2.2.2 燃气经营企业应建立24小时值班和报警制度，设立抢修值班电话，确保报警信息畅通。

2.2.3 燃气经营企业应配备必要的抢修设备、器材和交通工具，并定期检查和维护，确保处于良好状态。

第3章 管道燃气设施运行

3.1 管道运行管理

3.1.1 新建、改建、扩建的燃气管道设施投入使用前，应按照相关标准进行验收。验收合格后方可投入运行。

3.1.2 燃气管道运行应保持设计工作压力范围内的正常供气，压力偏差不应超过设计压力的±10%。

3.1.3 燃气管道运行压力分级应符合下列规定：
（1）低压管道：压力不大于0.01MPa；
（2）中压B管道：压力大于0.01MPa，不大于0.2MPa；
（3）中压A管道：压力大于0.2MPa，不大于0.4MPa；
（4）次高压B管道：压力大于0.4MPa，不大于0.8MPa；
（5）次高压A管道：压力大于0.8MPa，不大于1.6MPa；
（6）高压B管道：压力大于1.6MPa，不大于2.5MPa；
（7）高压A管道：压力大于2.5MPa，不大于4.0MPa。

3.2 管道巡线检查

3.2.1 燃气管道应定期进行巡线检查。巡线周期应符合下列规定：
（1）高压和次高压管道：每日巡检一次；
（2）中压管道：城区每周不少于一次，郊区每月不少于两次；
（3）低压管道：每月不少于一次。

3.2.2 巡线检查内容应包括：管道沿线地面有无异常变化、有无燃气泄漏迹象、管道标识和警示标志是否完好、管道附属设施是否正常。

第4章 抢修作业

4.1 一般规定

4.1.1 接到燃气泄漏报警后，抢修人员应在30分钟内到达现场。

4.1.2 到达现场后，应首先进行现场安全评估，包括：泄漏范围、可燃气体浓度、周围环境（人口密度、建筑物分布、地下管线等）。

4.1.3 抢修现场应设置警戒区域。警戒区域的设置应根据泄漏量、风向、地形等因素确定，并应留有安全裕度。

4.2 泄漏处置

4.2.1 发现燃气泄漏后，应立即采取以下措施：
（1）切断泄漏源：关闭泄漏管段上、下游阀门；
（2）消除火源：切断警戒区域内的电源，禁止明火作业；
（3）疏散人员：按照应急预案疏散警戒区域内的人员；
（4）设置警戒：设置警戒线和警示标志，安排专人看守。

4.2.2 管道泄漏的临时处置方法：
（1）管道小型泄漏（针孔状）：可采用管道堵漏卡、管道夹具等进行临时封堵；
（2）管道中型泄漏（裂缝状）：应采用堵漏袋或专用夹具进行封堵；
（3）管道大型泄漏（断裂）：应采用管道封堵器封堵管口，必要时进行放散。

4.2.3 抢修作业中应持续监测可燃气体浓度，当浓度达到爆炸下限（LEL）20%时，应停止作业并扩大警戒范围。

4.3 PE管道抢修

4.3.1 PE管道抢修应使用热熔连接或电熔连接方式。抢修连接前应确保管道内已无燃气或燃气浓度低于爆炸下限。

4.3.2 PE管道热熔操作环境要求：
（1）环境温度应在-5℃~40℃范围内；
（2）风速超过5级时应搭设防风棚；
（3）雨天作业应搭设遮雨设施；
（4）管道端面应清洁干燥，不得有油污、水分。

第5章 安全防护

5.1.1 抢修作业人员应穿戴防静电工作服、绝缘鞋、防护手套等个人防护装备。

5.1.2 在可燃气体浓度超过爆炸下限10%的区域作业时，作业人员应佩戴正压式空气呼吸器。

5.1.3 抢修现场应配备足够数量的灭火器材，包括干粉灭火器和二氧化碳灭火器。

5.1.4 使用电动工具时，应使用防爆型工具。禁止在警戒区域内使用非防爆电气设备。
"""


def create_sample_document(docs_dir: str = "./data/docs"):
    """Create a sample regulation document for testing the ingestion pipeline."""
    path = Path(docs_dir)
    path.mkdir(parents=True, exist_ok=True)
    sample_path = path / "sample_regulation.txt"
    sample_path.write_text(SAMPLE_REGULATION, encoding="utf-8")
    print(f"[ingest] Sample document created: {sample_path}")
    return sample_path


# ── CLI entry point ──────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Ingest documents into RAG indices")
    parser.add_argument("--docs-dir", default="./data/docs", help="Directory containing PDF/TXT documents")
    parser.add_argument("--create-sample", action="store_true", help="Create a sample regulation document for testing")
    args = parser.parse_args()

    if args.create_sample:
        create_sample_document(args.docs_dir)

    ingest_documents(args.docs_dir)


if __name__ == "__main__":
    main()
