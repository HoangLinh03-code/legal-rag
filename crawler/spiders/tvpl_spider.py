"""
TVPL Spider — Crawl văn bản pháp luật từ thuvienphapluat.vn.

Strategy:
1. discover_urls() — Lấy danh sách URL từ trang listing/sitemap
2. crawl_document() — Fetch + parse + save 1 văn bản
3. run() — Main loop: discover → crawl sequential (1 request/lần với TVPL)

Anti-ban: httpx trước, fallback Playwright nếu bị Cloudflare.
"""

import asyncio
import json
import hashlib
import logging
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup

from ..core.http_client import StealthHTTPClient
from ..core.playwright_client import PlaywrightStealthClient
from ..parsers.tvpl_parser import TVPLParser
from ..core.storage import CrawlStorage

logger = logging.getLogger(__name__)


class TVPLSpider:
    """
    Spider crawl toàn bộ thuvienphapluat.vn.

    Usage:
        storage = CrawlStorage()
        spider = TVPLSpider(storage)
        await spider.run(doc_types=["bo-luat", "luat"], max_docs=100)
    """

    BASE_URL = "https://thuvienphapluat.vn"

    # Loại văn bản ưu tiên crawl
    PRIORITY_TYPES = ["bo-luat", "luat", "nghi-dinh"]

    def __init__(self, storage: CrawlStorage, use_proxy: bool = False):
        """
        Args:
            storage: CrawlStorage instance để lưu kết quả
            use_proxy: True = dùng proxy pool (cần config)
        """
        self.storage = storage
        self.use_proxy = use_proxy
        self.parser = TVPLParser()
        self.http_client = StealthHTTPClient("thuvienphapluat.vn")
        self._failed_urls: list[str] = []
        self._stats = {"success": 0, "failed": 0, "skipped": 0}

    async def discover_urls(self, doc_type: str, max_pages: int = 100) -> list[str]:
        """
        Khám phá URL văn bản từ trang danh sách (listing page).

        Args:
            doc_type: Loại VB (VD: "bo-luat", "luat", "nghi-dinh")
            max_pages: Số trang listing tối đa

        Returns:
            Danh sách URL văn bản (deduplicated)
        """
        urls = []
        list_url = f"{self.BASE_URL}/van-ban/{doc_type}.aspx"

        for page in range(1, max_pages + 1):
            page_url = f"{list_url}?page={page}"
            try:
                response = await self.http_client.get(page_url)
                if response.status_code != 200:
                    logger.warning(f"Listing page {page} returned {response.status_code}")
                    break

                soup = BeautifulSoup(response.text, "html.parser")

                # Extract links đến từng văn bản
                # QUAN TRỌNG: Selector cần verify bằng DevTools
                links = soup.select("a.title, .list-vb a[href*='/van-ban/']")
                if not links:
                    break  # Hết trang

                for link in links:
                    href = link.get("href", "")
                    if href and ".aspx" in href:
                        full_url = href if href.startswith("http") else self.BASE_URL + href
                        urls.append(full_url)

                logger.info(f"[Discover] Page {page}: found {len(links)} links")

            except Exception as e:
                logger.error(f"[Discover] Error on page {page}: {e}")
                break

        return list(set(urls))  # Deduplicate

    async def crawl_document(self, url: str) -> bool:
        """
        Crawl 1 văn bản: fetch HTML → parse → save.

        Flow:
        1. Kiểm tra đã crawl chưa (skip nếu đã có)
        2. Fetch bằng httpx
        3. Nếu bị Cloudflare → fallback Playwright
        4. Parse HTML → ParsedLegalDocument
        5. Lưu vào storage

        Args:
            url: URL văn bản trên TVPL

        Returns:
            True nếu crawl thành công hoặc đã crawl trước đó
        """
        url_hash = hashlib.md5(url.encode()).hexdigest()

        # Skip nếu đã crawl
        if await self.storage.is_crawled(url_hash):
            self._stats["skipped"] += 1
            return True

        try:
            # Bước 1: Fetch bằng httpx (nhanh hơn)
            response = await self.http_client.get(url)
            html = response.text

            # Bước 2: Kiểm tra Cloudflare
            if "Just a moment" in html or "cf-browser-verification" in html:
                logger.info(f"[Spider] Cloudflare detected, switching to Playwright: {url}")
                html = await self._crawl_with_playwright(url)

            # Bước 3: Lưu raw HTML
            await self.storage.save_raw_html(url_hash, html, url)

            # Bước 4: Parse
            doc = self.parser.parse(html, url)
            if not doc:
                logger.warning(f"[Spider] Failed to parse: {url}")
                self._stats["failed"] += 1
                return False

            # Bước 5: Lưu document
            await self.storage.save_document(doc, url_hash)

            self._stats["success"] += 1
            logger.info(f"[Spider] ✓ {doc.title} ({doc.doc_number}) — {doc.total_articles} articles")
            return True

        except Exception as e:
            logger.error(f"[Spider] ✗ {url}: {e}")
            self._failed_urls.append(url)
            self._stats["failed"] += 1
            return False

    async def _crawl_with_playwright(self, url: str) -> str:
        """Fallback: dùng Playwright để bypass Cloudflare."""
        async with PlaywrightStealthClient() as client:
            return await client.get_html(url)

    async def run(
        self,
        doc_types: Optional[list[str]] = None,
        max_docs: int = 500,
    ) -> dict:
        """
        Main spider loop: discover URLs → crawl sequential.

        Args:
            doc_types: Loại VB cần crawl (None = dùng PRIORITY_TYPES)
            max_docs: Số VB tối đa cần crawl

        Returns:
            dict: Thống kê kết quả crawl
        """
        types_to_crawl = doc_types or self.PRIORITY_TYPES
        all_urls = []

        # Phase 1: Discover URLs
        logger.info("[Spider] Phase 1: Discovering URLs...")
        for doc_type in types_to_crawl:
            urls = await self.discover_urls(doc_type)
            all_urls.extend(urls)
            logger.info(f"  [{doc_type}] Found {len(urls)} URLs")

        all_urls = list(set(all_urls))[:max_docs]
        logger.info(f"[Spider] Total URLs to crawl: {len(all_urls)}")

        # Phase 2: Crawl sequential (1 request at a time for TVPL)
        for i, url in enumerate(all_urls):
            await self.crawl_document(url)

            # Progress report mỗi 50 documents
            if (i + 1) % 50 == 0:
                logger.info(
                    f"[Progress] {i+1}/{len(all_urls)} — "
                    f"Success: {self._stats['success']}, "
                    f"Failed: {self._stats['failed']}, "
                    f"Skipped: {self._stats['skipped']}"
                )

        # Lưu failed URLs để retry sau
        if self._failed_urls:
            failed_file = Path("failed_urls.json")
            failed_file.write_text(
                json.dumps(self._failed_urls, indent=2),
                encoding="utf-8"
            )
            logger.info(f"[Spider] Failed URLs saved to {failed_file}")

        final_stats = {
            **self._stats,
            "total_urls": len(all_urls),
            "failed_urls": self._failed_urls,
        }
        logger.info(f"[Spider] Done! Stats: {self._stats}")
        return final_stats
