"""
ORM Models — SQLAlchemy models cho Legal RAG.

Tables:
    - legal_documents: Metadata văn bản pháp luật
    - document_chunks: Chunks đã chia từ văn bản
    - crawled_urls: Tracking URL đã crawl
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Integer,
    String,
    Text,
    JSON,
    ForeignKey,
    Index,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from ..database import Base


class LegalDocument(Base):
    """
    Metadata 1 văn bản pháp luật.

    Được tạo sau khi crawler parse HTML thành công.
    """
    __tablename__ = "legal_documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source_id: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    source_url: Mapped[str] = mapped_column(String(500))
    source_site: Mapped[str] = mapped_column(String(100), default="thuvienphapluat.vn")

    # Metadata văn bản
    title: Mapped[str] = mapped_column(String(500))
    doc_number: Mapped[str] = mapped_column(String(100), index=True)
    doc_type: Mapped[str] = mapped_column(String(50), index=True)
    issuer: Mapped[str] = mapped_column(String(200), default="")
    issue_date: Mapped[str] = mapped_column(String(20), default="")
    effective_date: Mapped[str] = mapped_column(String(20), default="")
    status: Mapped[str] = mapped_column(String(50), default="unknown", index=True)

    # Thống kê
    total_chapters: Mapped[int] = mapped_column(Integer, default=0)
    total_articles: Mapped[int] = mapped_column(Integer, default=0)
    total_chunks: Mapped[int] = mapped_column(Integer, default=0)

    # Trạng thái pipeline
    is_indexed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # Raw data (JSON) — chapters/articles structure cho re-processing
    raw_structure: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Relationships
    chunks: Mapped[list["DocumentChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_legal_docs_type_status", "doc_type", "status"),
    )

    def __repr__(self) -> str:
        return f"<LegalDocument {self.doc_number} '{self.title[:50]}'>"


class DocumentChunk(Base):
    """
    1 chunk từ văn bản pháp luật.

    Mỗi chunk = 1 khoản (hoặc 1 sliding window nếu khoản quá dài).
    Lưu cùng context breadcrumb để embed tốt hơn.
    """
    __tablename__ = "document_chunks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("legal_documents.id", ondelete="CASCADE"),
        index=True,
    )

    # Content
    text: Mapped[str] = mapped_column(Text)
    full_context: Mapped[str] = mapped_column(Text)  # Breadcrumb + text
    char_count: Mapped[int] = mapped_column(Integer)

    # Vị trí trong cấu trúc VB
    chapter_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    chapter_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    article_number: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    article_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    clause_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_type: Mapped[str] = mapped_column(String(20), default="clause")  # clause, article, window

    # Metadata JSON cho Qdrant payload
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)

    # Qdrant point ID (UUID string)
    qdrant_id: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    # Relationships
    document: Mapped["LegalDocument"] = relationship(back_populates="chunks")

    __table_args__ = (
        Index("ix_chunks_article", "document_id", "article_number"),
    )

    def __repr__(self) -> str:
        return f"<Chunk Điều {self.article_number} Khoản {self.clause_number}>"


class CrawledURL(Base):
    """
    Tracking URL đã crawl — dedup và retry.
    """
    __tablename__ = "crawled_urls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    url_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    url: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending, success, failed
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    crawled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )


class Conversation(Base):
    """Chat conversation — cho RAG chatbot."""
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    title: Mapped[str] = mapped_column(String(200), default="Hỏi đáp pháp luật")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan",
        order_by="Message.created_at",
    )


class Message(Base):
    """1 message trong conversation."""
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        index=True,
    )
    role: Mapped[str] = mapped_column(String(20))  # user, assistant
    content: Mapped[str] = mapped_column(Text)
    sources: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # Citations
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    conversation: Mapped["Conversation"] = relationship(back_populates="messages")
