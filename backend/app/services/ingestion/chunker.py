"""
Chunker — Chia ParsedLegalDocument thành chunks cho embedding.

Chiến lược chunking cho pháp luật VN:
1. Mỗi Khoản = 1 chunk (đơn vị pháp lý nhỏ nhất có ý nghĩa)
2. Khoản dài > MAX_CHUNK_CHARS → sliding window (overlap)
3. Điều không có khoản → chunk cả điều
4. Mỗi chunk kèm full_context breadcrumb để embed tốt hơn

Ví dụ full_context:
    "[Bộ luật Lao động 2019 | Chương VI: Tiền lương | Điều 90: Tiền lương | Khoản 1]
    Tiền lương là số tiền mà người sử dụng lao động..."

Chạy: xem index_job.py
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

from crawler.parsers.tvpl_parser import ParsedLegalDocument, ParsedArticle

logger = logging.getLogger(__name__)

# Cấu hình chunking
MAX_CHUNK_CHARS = 2000     # Khoản > 2000 chars → sliding window
OVERLAP_CHARS = 200        # Overlap giữa các window
MIN_CHUNK_CHARS = 50       # Bỏ chunks quá ngắn


@dataclass
class Chunk:
    """
    1 chunk sẵn sàng embed.

    Attributes:
        text: Nội dung khoản/điều (raw text)
        full_context: Breadcrumb + text (dùng để embed)
        metadata: Dict metadata cho Qdrant payload
        char_count: Số ký tự
    """
    text: str
    full_context: str
    metadata: dict = field(default_factory=dict)
    char_count: int = 0

    def __post_init__(self):
        self.char_count = len(self.text)


def create_chunks(doc: ParsedLegalDocument) -> list[Chunk]:
    """
    Chia 1 ParsedLegalDocument thành danh sách Chunk.

    Strategy:
    1. Duyệt qua từng article
    2. Tìm chapter chứa article (dựa trên vị trí)
    3. Chia mỗi clause thành 1 chunk
    4. Khoản dài → sliding window

    Args:
        doc: ParsedLegalDocument từ parser

    Returns:
        list[Chunk] sẵn sàng để embed
    """
    chunks: list[Chunk] = []

    # Build chapter lookup: article_number → chapter info
    chapter_map = _build_chapter_map(doc)

    for article in doc.articles:
        chapter_info = chapter_map.get(article.article_number, {})

        if not article.clauses:
            # Điều không có khoản → chunk cả điều
            chunk = _create_article_chunk(doc, article, chapter_info)
            if chunk.char_count >= MIN_CHUNK_CHARS:
                chunks.append(chunk)
            continue

        for clause in article.clauses:
            clause_text = clause.get("text", "").strip()
            if not clause_text or len(clause_text) < MIN_CHUNK_CHARS:
                continue

            clause_num = clause.get("number")

            if len(clause_text) > MAX_CHUNK_CHARS:
                # Khoản quá dài → sliding window
                windows = _sliding_window(clause_text, MAX_CHUNK_CHARS, OVERLAP_CHARS)
                for i, window_text in enumerate(windows):
                    chunk = _make_chunk(
                        doc, article, chapter_info,
                        clause_num=clause_num,
                        text=window_text,
                        chunk_type="window",
                        window_index=i,
                    )
                    chunks.append(chunk)
            else:
                # Khoản bình thường → 1 chunk
                chunk = _make_chunk(
                    doc, article, chapter_info,
                    clause_num=clause_num,
                    text=clause_text,
                    chunk_type="clause",
                )
                chunks.append(chunk)

    logger.info(
        f"[Chunker] {doc.title[:50]} → {len(chunks)} chunks "
        f"(from {doc.total_articles} articles)"
    )
    return chunks


def _build_chapter_map(doc: ParsedLegalDocument) -> dict:
    """
    Map article_number → chapter info.

    Vì parser không link article vào chapter, ta ước lượng
    dựa trên thứ tự articles và chapters trong text.
    """
    if not doc.chapters:
        return {}

    # Simple heuristic: gán chapter dựa trên vị trí articles
    chapter_map = {}
    current_chapter = None

    # Duyệt chapters theo thứ tự
    for i, chapter in enumerate(doc.chapters):
        current_chapter = {
            "number": chapter.get("number", ""),
            "title": chapter.get("title", ""),
        }

        # Tất cả articles sau chapter này và trước chapter tiếp → thuộc chapter này
        # Đây là heuristic đơn giản, đủ cho MVP
        for article in doc.articles:
            if article.article_number not in chapter_map:
                chapter_map[article.article_number] = current_chapter

    return chapter_map


def _create_article_chunk(
    doc: ParsedLegalDocument,
    article: ParsedArticle,
    chapter_info: dict,
) -> Chunk:
    """Tạo chunk cho điều không có khoản."""
    return _make_chunk(
        doc, article, chapter_info,
        clause_num=None,
        text=article.raw_text,
        chunk_type="article",
    )


def _make_chunk(
    doc: ParsedLegalDocument,
    article: ParsedArticle,
    chapter_info: dict,
    clause_num: Optional[int],
    text: str,
    chunk_type: str = "clause",
    window_index: int = 0,
) -> Chunk:
    """
    Tạo 1 Chunk với đầy đủ context breadcrumb và metadata.
    """
    # Build breadcrumb
    parts = [doc.title]
    if chapter_info:
        ch_num = chapter_info.get("number", "")
        ch_title = chapter_info.get("title", "")
        if ch_num:
            parts.append(f"Chương {ch_num}: {ch_title}")

    parts.append(f"Điều {article.article_number}: {article.article_title}")

    if clause_num is not None:
        parts.append(f"Khoản {clause_num}")

    breadcrumb = " | ".join(parts)
    full_context = f"[{breadcrumb}]\n{text}"

    # Metadata cho Qdrant payload
    metadata = {
        "source_url": doc.source_url,
        "source_site": "thuvienphapluat.vn",
        "van_ban": doc.title,
        "doc_number": doc.doc_number,
        "doc_type": doc.doc_type,
        "issue_date": doc.issue_date,
        "effective_date": doc.effective_date,
        "status": doc.status,
        "issuer": doc.issuer,
        "chuong_so": chapter_info.get("number", ""),
        "chuong_ten": chapter_info.get("title", ""),
        "dieu_so": article.article_number,
        "dieu_ten": article.article_title,
        "khoan_so": clause_num,
        "chunk_type": chunk_type,
        "char_count": len(text),
    }

    return Chunk(
        text=text,
        full_context=full_context,
        metadata=metadata,
    )


def _sliding_window(text: str, max_chars: int, overlap: int) -> list[str]:
    """
    Chia text dài thành các window có overlap.

    Args:
        text: Text cần chia
        max_chars: Kích thước tối đa mỗi window
        overlap: Số chars overlap giữa các window

    Returns:
        list[str] — danh sách window texts
    """
    if len(text) <= max_chars:
        return [text]

    windows = []
    start = 0
    while start < len(text):
        end = start + max_chars
        window = text[start:end]

        # Cố gắng cắt ở cuối câu (dấu .)
        if end < len(text):
            last_period = window.rfind(".")
            if last_period > max_chars * 0.5:  # Chỉ cắt nếu dấu . ở nửa sau
                window = window[:last_period + 1]
                end = start + last_period + 1

        windows.append(window.strip())

        # Di chuyển start (trừ overlap)
        start = end - overlap
        if start >= len(text):
            break

    return windows
