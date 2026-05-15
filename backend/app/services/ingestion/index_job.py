"""
Index Job — Full pipeline: ParsedLegalDocument → Chunk → Embed → Qdrant.

Đây là "trái tim" của ingestion pipeline.

Flow:
1. Đọc documents từ crawl_db/ (hoặc PostgreSQL khi migrate)
2. Parse lại nếu cần
3. Chunk mỗi document → list[Chunk]
4. Embed chunks → vectors
5. Upsert vào Qdrant
6. Lưu chunks vào PostgreSQL (nếu có)

Chạy:
    uv run python -m backend.scripts.index_all
"""

import asyncio
import json
import logging
import uuid
from pathlib import Path
from typing import Optional

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    PointStruct,
    PayloadSchemaType,
)

from .chunker import create_chunks, Chunk
from .embedder import Embedder
from ...config import settings

logger = logging.getLogger(__name__)

# Batch size cho Qdrant upsert
QDRANT_BATCH_SIZE = 100


def get_qdrant_client() -> QdrantClient:
    """Tạo Qdrant client."""
    return QdrantClient(
        host=settings.qdrant_host,
        port=settings.qdrant_port,
    )


def ensure_collection(client: QdrantClient):
    """
    Tạo Qdrant collection nếu chưa có.

    Collection: legal_docs
    - Vector size: 1024 (multilingual-e5-large)
    - Distance: Cosine
    - Payload indexes cho filtering
    """
    collection_name = settings.qdrant_collection
    collections = [c.name for c in client.get_collections().collections]

    if collection_name in collections:
        logger.info(f"[Qdrant] Collection '{collection_name}' already exists")
        return

    logger.info(f"[Qdrant] Creating collection '{collection_name}'")
    client.create_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(
            size=settings.embedding_dim,
            distance=Distance.COSINE,
        ),
    )

    # Tạo payload indexes cho filtering
    for field_name, field_type in [
        ("doc_type", PayloadSchemaType.KEYWORD),
        ("status", PayloadSchemaType.KEYWORD),
        ("van_ban", PayloadSchemaType.KEYWORD),
        ("dieu_so", PayloadSchemaType.INTEGER),
        ("doc_number", PayloadSchemaType.KEYWORD),
        ("issuer", PayloadSchemaType.KEYWORD),
    ]:
        client.create_payload_index(
            collection_name=collection_name,
            field_name=field_name,
            field_schema=field_type,
        )

    logger.info(f"[Qdrant] Collection created with payload indexes")


def upsert_chunks(
    client: QdrantClient,
    chunks: list[Chunk],
    embeddings,
) -> int:
    """
    Upsert chunks + vectors vào Qdrant.

    Args:
        client: QdrantClient
        chunks: list[Chunk]
        embeddings: numpy array (len(chunks), 1024)

    Returns:
        Số points đã upsert
    """
    collection_name = settings.qdrant_collection
    points = []

    for i, (chunk, vector) in enumerate(zip(chunks, embeddings)):
        point_id = str(uuid.uuid4())
        points.append(PointStruct(
            id=point_id,
            vector=vector.tolist(),
            payload={
                "text": chunk.text,
                "full_context": chunk.full_context,
                **chunk.metadata,
            },
        ))

    # Upsert theo batch
    total = 0
    for i in range(0, len(points), QDRANT_BATCH_SIZE):
        batch = points[i:i + QDRANT_BATCH_SIZE]
        client.upsert(
            collection_name=collection_name,
            points=batch,
        )
        total += len(batch)
        logger.info(f"[Qdrant] Upserted {total}/{len(points)} points")

    return total


async def index_from_crawl_db(
    crawl_db_dir: str = "crawl_db",
    raw_html_dir: str = "raw_html",
    max_docs: Optional[int] = None,
):
    """
    Index tất cả documents từ crawl_db (MVP disk-based storage).

    Flow:
    1. Đọc index.json từ crawl_db/
    2. Với mỗi document đã parse: load ParsedLegalDocument
    3. Chunk → Embed → Upsert Qdrant

    Args:
        crawl_db_dir: Thư mục chứa crawl metadata
        raw_html_dir: Thư mục chứa raw HTML
        max_docs: Số documents tối đa (None = tất cả)
    """
    from crawler.parsers.tvpl_parser import TVPLParser

    db_dir = Path(crawl_db_dir)
    html_dir = Path(raw_html_dir)

    # Load index (CrawlStorage dùng crawl_index.json)
    index_file = db_dir / "crawl_index.json"
    if not index_file.exists():
        logger.error(f"[Index] No crawl_index.json found in {db_dir}")
        return

    with open(index_file, "r", encoding="utf-8") as f:
        index = json.load(f)

    logger.info(f"[Index] Found {len(index)} entries in crawl_db")

    # Setup
    qdrant = get_qdrant_client()
    ensure_collection(qdrant)
    embedder = Embedder()
    parser = TVPLParser()

    all_chunks = []
    doc_count = 0

    for url_hash, meta in index.items():
        if max_docs and doc_count >= max_docs:
            break

        html_file = html_dir / f"{url_hash}.html"
        if not html_file.exists():
            logger.warning(f"[Index] HTML not found: {html_file}")
            continue

        url = meta.get("url", "")
        html = html_file.read_text(encoding="utf-8")

        # Parse
        doc = parser.parse(html, url)
        if not doc:
            logger.warning(f"[Index] Parse failed: {url}")
            continue

        # Chunk
        chunks = create_chunks(doc)
        if not chunks:
            logger.warning(f"[Index] No chunks: {url}")
            continue

        all_chunks.extend(chunks)
        doc_count += 1
        logger.info(
            f"[Index] [{doc_count}] {doc.title[:50]} → {len(chunks)} chunks"
        )

    if not all_chunks:
        logger.error("[Index] No chunks to index!")
        return

    logger.info(f"[Index] Total: {doc_count} docs → {len(all_chunks)} chunks")
    logger.info(f"[Index] Embedding {len(all_chunks)} chunks...")

    # Embed tất cả
    embeddings = embedder.embed_chunks(all_chunks)

    # Upsert vào Qdrant
    total = upsert_chunks(qdrant, all_chunks, embeddings)

    # Verify
    collection_info = qdrant.get_collection(settings.qdrant_collection)
    logger.info(
        f"[Index] Done! "
        f"Indexed {total} points. "
        f"Collection total: {collection_info.points_count} points"
    )

    return {
        "documents": doc_count,
        "chunks": len(all_chunks),
        "points_upserted": total,
        "collection_total": collection_info.points_count,
    }
