"""
Admin API — Endpoints quản lý hệ thống.

Endpoints:
    GET  /admin/stats          — Thống kê tổng quan
    GET  /admin/documents      — Danh sách văn bản đã crawl
    POST /admin/index/trigger  — Trigger index job
"""

import json
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Query
from pydantic import BaseModel

from ..config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["Admin"])


class StatsResponse(BaseModel):
    total_documents: int = 0
    total_chunks: int = 0
    qdrant_points: int = 0
    last_crawl: str = ""
    raw_html_files: int = 0


class DocumentInfo(BaseModel):
    url_hash: str
    url: str
    crawled_at: str = ""
    status: str = ""


class IndexResult(BaseModel):
    status: str
    documents: int = 0
    chunks: int = 0
    points_upserted: int = 0


@router.get("/stats", response_model=StatsResponse)
async def get_stats():
    """Thống kê tổng quan hệ thống."""
    stats = StatsResponse()

    # Đếm raw HTML files
    html_dir = Path(settings.raw_html_dir)
    if html_dir.exists():
        stats.raw_html_files = len(list(html_dir.glob("*.html")))

    # Đếm documents trong crawl_db
    db_dir = Path(settings.crawl_db_dir)
    index_file = db_dir / "crawl_index.json"
    if index_file.exists():
        with open(index_file, "r", encoding="utf-8") as f:
            index = json.load(f)
        stats.total_documents = len(index)

        # Last crawl time
        if index:
            last_entry = list(index.values())[-1]
            stats.last_crawl = last_entry.get("crawled_at", "")

    # Qdrant stats
    try:
        from qdrant_client import QdrantClient
        client = QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)
        info = client.get_collection(settings.qdrant_collection)
        stats.qdrant_points = info.points_count
        stats.total_chunks = info.points_count
    except Exception:
        pass

    return stats


@router.get("/documents", response_model=list[DocumentInfo])
async def list_documents(
    limit: int = Query(default=50, le=500),
    offset: int = Query(default=0, ge=0),
):
    """Danh sách văn bản đã crawl."""
    db_dir = Path(settings.crawl_db_dir)
    index_file = db_dir / "crawl_index.json"

    if not index_file.exists():
        return []

    with open(index_file, "r", encoding="utf-8") as f:
        index = json.load(f)

    docs = []
    items = list(index.items())[offset:offset + limit]
    for url_hash, meta in items:
        docs.append(DocumentInfo(
            url_hash=url_hash,
            url=meta.get("url", ""),
            crawled_at=meta.get("crawled_at", ""),
            status=meta.get("status", "crawled"),
        ))

    return docs


@router.post("/index/trigger", response_model=IndexResult)
async def trigger_index(
    background_tasks: BackgroundTasks,
    max_docs: Optional[int] = Query(default=None, description="Số docs tối đa"),
):
    """
    Trigger index job — chạy background.

    Pipeline: Crawled HTML → Parse → Chunk → Embed → Qdrant
    """
    background_tasks.add_task(_run_index, max_docs)
    return IndexResult(status="started")


async def _run_index(max_docs: Optional[int] = None):
    """Background task chạy index job."""
    try:
        from ..services.ingestion.index_job import index_from_crawl_db
        result = await index_from_crawl_db(
            crawl_db_dir=settings.crawl_db_dir,
            raw_html_dir=settings.raw_html_dir,
            max_docs=max_docs,
        )
        logger.info(f"[Admin] Index job completed: {result}")
    except Exception as e:
        logger.error(f"[Admin] Index job failed: {e}")
