"""
FastAPI Main — Entry point cho Legal RAG backend.

Chạy:
    uv run uvicorn backend.app.main:app --reload --port 8000
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup và shutdown logic."""
    logger.info(f"Starting {settings.app_name} v{settings.app_version}")
    yield
    logger.info("Shutting down...")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Hệ thống hỏi đáp pháp luật Việt Nam bằng AI",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    """Health check endpoint."""
    from qdrant_client import QdrantClient

    # Check Qdrant
    try:
        client = QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)
        collections = client.get_collections().collections
        qdrant_ok = True
        docs_indexed = 0
        for c in collections:
            if c.name == settings.qdrant_collection:
                info = client.get_collection(c.name)
                docs_indexed = info.points_count
    except Exception:
        qdrant_ok = False
        docs_indexed = 0

    return {
        "status": "ok",
        "version": settings.app_version,
        "docs_indexed": docs_indexed,
        "qdrant": "connected" if qdrant_ok else "disconnected",
    }


# Register routers
from .api.admin import router as admin_router
app.include_router(admin_router)
