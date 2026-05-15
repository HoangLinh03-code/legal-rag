"""
Run Crawl — Logic crawl chính.

Workflow:
1. Fetch danh sách URL từ trang listing hoặc sitemap
2. Lọc URL chưa crawl
3. Crawl từng URL (sequential, có rate limiting)
4. Parse HTML → lưu document

Hai chế độ:
- httpx (mặc định): Nhanh, nhẹ, nhưng có thể bị Cloudflare
- Playwright: Chậm hơn 10x, nhưng bypass được Cloudflare
"""

import asyncio
import hashlib
import json
import logging
import time
from pathlib import Path
from datetime import datetime
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from .parsers.tvpl_parser import TVPLParser
from .core.storage import CrawlStorage
from .core.rate_limiter import TokenBucketRateLimiter, DomainRateConfig

logger = logging.getLogger(__name__)

BASE_URL = "https://thuvienphapluat.vn"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Cache-Control": "max-age=0",
}

# Danh sách URL đã biết — fallback khi listing page không hoạt động
KNOWN_URLS = {
    "bo-luat": [
        "https://thuvienphapluat.vn/van-ban/Lao-dong-Tien-luong/Bo-Luat-lao-dong-2019-333670.aspx",
        "https://thuvienphapluat.vn/van-ban/Quyen-dan-su/Bo-luat-dan-su-2015-296215.aspx",
        "https://thuvienphapluat.vn/van-ban/Trach-nhiem-hinh-su/Bo-luat-Hinh-su-2015-296661.aspx",
        "https://thuvienphapluat.vn/van-ban/Thu-tuc-To-tung/Bo-luat-to-tung-hinh-su-2015-296884.aspx",
        "https://thuvienphapluat.vn/van-ban/Thu-tuc-To-tung/Bo-luat-To-tung-dan-su-2015-296861.aspx",
        "https://thuvienphapluat.vn/van-ban/Thuong-mai/Bo-luat-hang-hai-Viet-Nam-2015-299078.aspx",
    ],
    "luat": [
        "https://thuvienphapluat.vn/van-ban/Doanh-nghiep/Luat-doanh-nghiep-2020-437468.aspx",
        "https://thuvienphapluat.vn/van-ban/Dau-tu/Luat-Dau-tu-2020-437535.aspx",
        "https://thuvienphapluat.vn/van-ban/Bat-dong-san/Luat-nha-o-2023-594963.aspx",
        "https://thuvienphapluat.vn/van-ban/Bat-dong-san/Luat-Dat-dai-2024-594925.aspx",
        "https://thuvienphapluat.vn/van-ban/Thue-Phi-Le-Phi/Luat-thue-thu-nhap-ca-nhan-sua-doi-2012-154674.aspx",
        "https://thuvienphapluat.vn/van-ban/Lao-dong-Tien-luong/Luat-bao-hiem-xa-hoi-2024-601186.aspx",
        "https://thuvienphapluat.vn/van-ban/Quyen-dan-su/Luat-hon-nhan-va-gia-dinh-2014-238640.aspx",
        "https://thuvienphapluat.vn/van-ban/Bo-may-hanh-chinh/Luat-xu-ly-vi-pham-hanh-chinh-2012-144615.aspx",
        "https://thuvienphapluat.vn/van-ban/Giao-duc/Luat-Giao-duc-2019-417400.aspx",
        "https://thuvienphapluat.vn/van-ban/The-thao-Y-te/Luat-Bao-hiem-y-te-sua-doi-2014-257967.aspx",
    ],
}


async def discover_urls_from_listing(
    doc_type: str,
    max_pages: int = 10,
) -> list[str]:
    """
    Discover URLs từ trang listing.
    Fallback sang KNOWN_URLS nếu listing không hoạt động.
    """
    urls = []
    list_url = f"{BASE_URL}/van-ban/{doc_type}"

    logger.info(f"Discovering URLs from: {list_url}")

    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            for page in range(1, max_pages + 1):
                page_url = f"{list_url}?page={page}" if page > 1 else list_url

                response = await client.get(page_url, headers=HEADERS)
                if response.status_code != 200:
                    logger.warning(f"Page {page} returned {response.status_code}")
                    break

                soup = BeautifulSoup(response.text, "html.parser")

                # Tìm links đến văn bản
                page_links = []
                for a in soup.select("a[href*='/van-ban/']"):
                    href = a.get("href", "")
                    if ".aspx" in href and "/van-ban/" in href:
                        full_url = href if href.startswith("http") else BASE_URL + href
                        if full_url not in urls:
                            page_links.append(full_url)
                            urls.append(full_url)

                if not page_links:
                    break

                logger.info(f"  Page {page}: found {len(page_links)} links")

                # Rate limit giữa các trang listing
                await asyncio.sleep(3)

    except Exception as e:
        logger.warning(f"Listing discovery failed: {e}")

    # Fallback: thêm KNOWN_URLS nếu discovery ít
    known = KNOWN_URLS.get(doc_type, [])
    for url in known:
        if url not in urls:
            urls.append(url)

    logger.info(f"Total URLs for [{doc_type}]: {len(urls)} (including {len(known)} known)")
    return urls


async def crawl_single_httpx(
    url: str,
    parser: TVPLParser,
    storage: CrawlStorage,
) -> dict:
    """
    Crawl 1 văn bản bằng httpx.

    Returns:
        {"status": "success|skipped|cloudflare|parse_error|error", ...}
    """
    url_hash = hashlib.md5(url.encode()).hexdigest()

    # Skip nếu đã crawl
    if await storage.is_crawled(url_hash):
        return {"status": "skipped", "url": url}

    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(url, headers=HEADERS)

        if response.status_code != 200:
            return {"status": "error", "url": url, "code": response.status_code}

        html = response.text

        # Cloudflare?
        if "Just a moment" in html or "cf-browser-verification" in html:
            return {"status": "cloudflare", "url": url}

        # Lưu raw HTML
        await storage.save_raw_html(url_hash, html, url)

        # Parse
        doc = parser.parse(html, url)
        if not doc:
            return {"status": "parse_error", "url": url}

        # Lưu document
        await storage.save_document(doc, url_hash)

        return {
            "status": "success",
            "url": url,
            "title": doc.title,
            "doc_number": doc.doc_number,
            "articles": doc.total_articles,
        }

    except Exception as e:
        return {"status": "error", "url": url, "error": str(e)}


async def crawl_single_playwright(
    url: str,
    parser: TVPLParser,
    storage: CrawlStorage,
) -> dict:
    """
    Crawl 1 văn bản bằng Playwright (bypass Cloudflare).
    """
    from .core.playwright_client import PlaywrightStealthClient

    url_hash = hashlib.md5(url.encode()).hexdigest()

    if await storage.is_crawled(url_hash):
        return {"status": "skipped", "url": url}

    try:
        async with PlaywrightStealthClient() as client:
            html = await client.get_html(url, wait_selector="body")

        await storage.save_raw_html(url_hash, html, url)

        doc = parser.parse(html, url)
        if not doc:
            return {"status": "parse_error", "url": url}

        await storage.save_document(doc, url_hash)

        return {
            "status": "success",
            "url": url,
            "title": doc.title,
            "doc_number": doc.doc_number,
            "articles": doc.total_articles,
        }

    except Exception as e:
        return {"status": "error", "url": url, "error": str(e)}


async def run_crawl(
    doc_types: Optional[list[str]] = None,
    max_docs: int = 10,
    use_playwright: bool = False,
):
    """
    Main crawl flow.

    Args:
        doc_types: Loại VB cần crawl (None = bo-luat + luat)
        max_docs: Số VB tối đa
        use_playwright: True = dùng Playwright (chậm hơn, bypass Cloudflare)
    """
    types = doc_types or ["bo-luat", "luat"]
    storage = CrawlStorage(raw_dir="raw_html", db_dir="crawl_db")
    parser = TVPLParser()

    print(f"\n🏛️  Legal RAG Crawler")
    print(f"{'='*60}")
    print(f"  Types: {types}")
    print(f"  Max docs: {max_docs}")
    print(f"  Engine: {'Playwright' if use_playwright else 'httpx'}")
    print(f"  Started: {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*60}")

    # Phase 1: Discover URLs
    all_urls = []
    for doc_type in types:
        urls = await discover_urls_from_listing(doc_type)
        all_urls.extend(urls)

    # Deduplicate và limit
    all_urls = list(dict.fromkeys(all_urls))[:max_docs]
    print(f"\n📋 Total URLs to crawl: {len(all_urls)}")

    # Phase 2: Crawl
    crawl_func = crawl_single_playwright if use_playwright else crawl_single_httpx

    stats = {"success": 0, "skipped": 0, "cloudflare": 0, "parse_error": 0, "error": 0}
    cloudflare_urls = []
    start_time = time.time()

    for i, url in enumerate(all_urls):
        result = await crawl_func(url, parser, storage)
        status = result["status"]
        stats[status] = stats.get(status, 0) + 1

        # Log
        if status == "success":
            title = result.get("title", "")[:50]
            articles = result.get("articles", 0)
            print(f"  ✓ [{i+1}/{len(all_urls)}] {title} ({articles} articles)")
        elif status == "skipped":
            print(f"  ⏭ [{i+1}/{len(all_urls)}] Skipped (already crawled)")
        elif status == "cloudflare":
            print(f"  ⚠️  [{i+1}/{len(all_urls)}] Cloudflare! → Thử --playwright")
            cloudflare_urls.append(url)
        elif status == "parse_error":
            print(f"  ⚠️  [{i+1}/{len(all_urls)}] Parse failed (selector mismatch?)")
        else:
            error = result.get("error", result.get("code", "unknown"))
            print(f"  ✗ [{i+1}/{len(all_urls)}] Error: {error}")

        # Rate limiting — delay giữa các requests
        if i < len(all_urls) - 1 and status != "skipped":
            import random
            delay = random.uniform(10, 20)
            if (i + 1) % 15 == 0:
                delay = random.uniform(60, 120)  # Nghỉ dài sau 15 requests
                print(f"  ⏳ Long break: {delay:.0f}s")
            else:
                print(f"  ⏳ Delay: {delay:.0f}s")
            await asyncio.sleep(delay)

    # Summary
    elapsed = time.time() - start_time
    print(f"\n{'='*60}")
    print(f"📊 Crawl Summary")
    print(f"{'='*60}")
    print(f"  Duration: {elapsed:.0f}s ({elapsed/60:.1f} min)")
    print(f"  Success:    {stats['success']}")
    print(f"  Skipped:    {stats['skipped']}")
    print(f"  Cloudflare: {stats['cloudflare']}")
    print(f"  Parse Error:{stats['parse_error']}")
    print(f"  Error:      {stats['error']}")
    print(f"\n  Storage: {storage.stats}")

    if cloudflare_urls:
        print(f"\n⚠️  {len(cloudflare_urls)} URLs bị Cloudflare.")
        print(f"   Chạy lại với: uv run python -m crawler crawl --playwright --max {len(cloudflare_urls)}")
        # Lưu cloudflare URLs
        Path("cloudflare_urls.json").write_text(
            json.dumps(cloudflare_urls, indent=2), encoding="utf-8"
        )


async def reparse_all():
    """Re-parse tất cả HTML đã lưu trong raw_html/ (khi cập nhật parser)."""
    storage = CrawlStorage(raw_dir="raw_html", db_dir="crawl_db")
    parser = TVPLParser()

    html_dir = Path("raw_html")
    html_files = list(html_dir.glob("*.html"))

    print(f"\n🔄 Re-parsing {len(html_files)} HTML files...")

    success, failed = 0, 0
    for f in html_files:
        html = f.read_text(encoding="utf-8")
        url_hash = f.stem

        # Lấy URL từ index
        url = storage._index.get(url_hash, {}).get("url", f"unknown/{url_hash}")

        doc = parser.parse(html, url)
        if doc:
            await storage.save_document(doc, url_hash)
            success += 1
            print(f"  ✓ {doc.title[:60]} ({doc.total_articles} articles)")
        else:
            failed += 1
            print(f"  ✗ {f.name}: parse failed")

    print(f"\nDone! Success: {success}, Failed: {failed}")
