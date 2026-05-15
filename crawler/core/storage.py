"""
Storage — Lưu trữ raw HTML và parsed documents.

2 tầng lưu trữ:
1. Disk: raw HTML files (backup, reparse khi cần)
2. PostgreSQL: metadata + parsed data (query, index)

Tại sao lưu raw HTML?
- Parser có thể cải thiện → reparse không cần crawl lại
- Debug: xem HTML gốc khi parse sai
- Backup: không mất dữ liệu nếu DB lỗi
"""

import hashlib
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class CrawlStorage:
    """
    Lưu trữ kết quả crawl — raw HTML vào disk, metadata vào JSON.

    Phiên bản MVP: dùng JSON files thay vì PostgreSQL
    (sẽ migrate sang PostgreSQL khi setup DB ở Tuần 1)

    Usage:
        storage = CrawlStorage(raw_dir="raw_html", db_dir="crawl_db")
        await storage.save_raw_html(url_hash, html, url)
        is_done = await storage.is_crawled(url_hash)
    """

    def __init__(self, raw_dir: str = "raw_html", db_dir: str = "crawl_db"):
        """
        Args:
            raw_dir: Thư mục lưu raw HTML files
            db_dir: Thư mục lưu metadata JSON (MVP, sau chuyển PostgreSQL)
        """
        self.raw_dir = Path(raw_dir)
        self.db_dir = Path(db_dir)
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.db_dir.mkdir(parents=True, exist_ok=True)

        # Index: url_hash → metadata (load từ disk)
        self._index_file = self.db_dir / "crawl_index.json"
        self._index: dict = self._load_index()

    def _load_index(self) -> dict:
        """Load index từ disk. Tạo mới nếu chưa có."""
        if self._index_file.exists():
            return json.loads(self._index_file.read_text(encoding="utf-8"))
        return {}

    def _save_index(self) -> None:
        """Persist index ra disk."""
        self._index_file.write_text(
            json.dumps(self._index, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    async def save_raw_html(self, url_hash: str, html: str, url: str) -> Path:
        """
        Lưu raw HTML vào disk.

        Args:
            url_hash: MD5 hash của URL (dùng làm filename)
            html: Nội dung HTML
            url: URL gốc (lưu metadata)

        Returns:
            Path: Đường dẫn file HTML đã lưu
        """
        filepath = self.raw_dir / f"{url_hash}.html"
        filepath.write_text(html, encoding="utf-8")

        # Cập nhật index
        self._index[url_hash] = {
            "url": url,
            "crawled_at": datetime.now().isoformat(),
            "html_path": str(filepath),
            "parsed": False,
        }
        self._save_index()

        logger.info(f"[Storage] Saved HTML: {filepath.name} ({len(html)} chars)")
        return filepath

    async def is_crawled(self, url_hash: str) -> bool:
        """
        Kiểm tra URL đã crawl chưa.

        Args:
            url_hash: MD5 hash của URL

        Returns:
            True nếu đã crawl
        """
        return url_hash in self._index

    async def save_document(self, doc, url_hash: str) -> None:
        """
        Lưu ParsedLegalDocument vào storage.

        Args:
            doc: ParsedLegalDocument instance
            url_hash: MD5 hash của URL

        Lưu vào JSON file riêng + cập nhật index.
        Sau này sẽ chuyển sang PostgreSQL.
        """
        doc_data = {
            "doc_id": url_hash,
            "source_url": doc.source_url,
            "title": doc.title,
            "doc_number": doc.doc_number,
            "doc_type": doc.doc_type,
            "issuer": doc.issuer,
            "issue_date": doc.issue_date,
            "effective_date": doc.effective_date,
            "status": doc.status,
            "total_articles": doc.total_articles,
            "chapters": doc.chapters,
            "articles": [
                {
                    "number": a.article_number,
                    "title": a.article_title,
                    "clauses": a.clauses,
                }
                for a in doc.articles
            ],
            "saved_at": datetime.now().isoformat(),
        }

        doc_file = self.db_dir / f"{url_hash}.json"
        doc_file.write_text(
            json.dumps(doc_data, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

        # Cập nhật index
        if url_hash in self._index:
            self._index[url_hash]["parsed"] = True
            self._index[url_hash]["title"] = doc.title
            self._index[url_hash]["doc_number"] = doc.doc_number
            self._save_index()

        logger.info(f"[Storage] Saved document: {doc.title} ({doc.total_articles} articles)")

    async def get_uncrawled_urls(self, urls: list[str], limit: int = 100) -> list[str]:
        """
        Lọc ra các URL chưa crawl từ danh sách.

        Args:
            urls: Danh sách URL cần kiểm tra
            limit: Số lượng tối đa trả về

        Returns:
            Danh sách URL chưa crawl
        """
        uncrawled = []
        for url in urls:
            url_hash = hashlib.md5(url.encode()).hexdigest()
            if url_hash not in self._index:
                uncrawled.append(url)
                if len(uncrawled) >= limit:
                    break
        return uncrawled

    @property
    def stats(self) -> dict:
        """Thống kê storage."""
        total = len(self._index)
        parsed = sum(1 for v in self._index.values() if v.get("parsed"))
        return {
            "total_crawled": total,
            "total_parsed": parsed,
            "pending_parse": total - parsed,
        }

    @staticmethod
    def url_to_hash(url: str) -> str:
        """Tạo MD5 hash từ URL — dùng làm unique ID."""
        return hashlib.md5(url.encode()).hexdigest()
