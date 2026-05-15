"""
Config — Load settings từ .env.

Usage:
    from backend.app.config import settings
    print(settings.database_url)
"""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """App configuration loaded from environment variables."""

    # === App ===
    app_name: str = "Legal RAG"
    app_version: str = "0.2.0"
    debug: bool = False

    # === Database ===
    database_url: str = "postgresql+asyncpg://legal_rag:legal_rag_dev@localhost:5432/legal_rag"

    # === Qdrant ===
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_collection: str = "legal_docs"

    # === Embedding ===
    embedding_model: str = "intfloat/multilingual-e5-large"
    embedding_dim: int = 1024
    embedding_batch_size: int = 64

    # === Claude API ===
    anthropic_api_key: str = ""

    # === Crawl ===
    raw_html_dir: str = "raw_html"
    crawl_db_dir: str = "crawl_db"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
