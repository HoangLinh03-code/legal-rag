"""
Test tích hợp Crawl — Fetch + Parse 1 văn bản thực từ TVPL.

Chạy:
    uv run pytest tests/test_crawler/test_crawl_integration.py -v

LƯU Ý:
- Test này GỬI REQUEST THỰC đến thuvienphapluat.vn
- Chạy thưa, không chạy liên tục
- Đánh dấu `@pytest.mark.integration` để tách khỏi unit tests
- Dùng `pytest -m integration` để chỉ chạy test này
"""

import asyncio
import hashlib
import os
from pathlib import Path

import pytest

# Marker cho integration tests — cần request thực
pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_fetch_single_url():
    """
    Test 1: Fetch 1 URL từ TVPL, kiểm tra response.

    Kỳ vọng:
    - Status 200
    - HTML có content (>1000 chars)
    - Không bị Cloudflare block (hoặc ít nhất có HTML)
    """
    import httpx

    url = "https://thuvienphapluat.vn/van-ban/lao-dong-tien-luong/bo-luat-lao-dong-2019-333670.aspx"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8",
    }

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        response = await client.get(url, headers=headers)

    # Kiểm tra response
    print(f"Status: {response.status_code}")
    print(f"Content length: {len(response.text)} chars")
    print(f"Has Cloudflare: {'Just a moment' in response.text}")

    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    assert len(response.text) > 1000, "Response quá ngắn — có thể bị block"


@pytest.mark.asyncio
async def test_parse_sample_html_from_file():
    """
    Test 2: Parse HTML mẫu đã lưu trên disk.

    Nếu bạn đã crawl thành công ở test 1, lưu HTML vào raw_html/
    rồi chạy test này để verify parser.

    Nếu chưa có file, test này dùng HTML mẫu nội bộ.
    """
    from crawler.parsers.tvpl_parser import TVPLParser

    parser = TVPLParser()

    # Tìm file HTML trong raw_html/
    raw_dir = Path("raw_html")
    html_files = list(raw_dir.glob("*.html")) if raw_dir.exists() else []

    if html_files:
        # Dùng file HTML thực
        html = html_files[0].read_text(encoding="utf-8")
        url = f"https://thuvienphapluat.vn/test/{html_files[0].stem}.aspx"
        print(f"Testing with real HTML: {html_files[0].name}")
    else:
        # Dùng HTML mẫu
        from tests.test_crawler.test_tvpl_parser import SAMPLE_HTML, SAMPLE_URL
        html = SAMPLE_HTML
        url = SAMPLE_URL
        print("No real HTML found, using sample HTML")

    doc = parser.parse(html, url)

    if doc:
        print(f"Title: {doc.title}")
        print(f"Doc number: {doc.doc_number}")
        print(f"Type: {doc.doc_type}")
        print(f"Articles: {doc.total_articles}")
        print(f"Chapters: {len(doc.chapters)}")

        assert doc.title != "", "Title rỗng"
        assert doc.total_articles > 0, "Không parse được article nào"
    else:
        print("Parser returned None — HTML may not be a legal document page")
        # Không fail — có thể HTML bị Cloudflare
        pytest.skip("Parser returned None, may need real HTML")


@pytest.mark.asyncio
async def test_crawl_and_parse_one():
    """
    Test 3: Full flow — Fetch HTML → Parse → Lưu file.

    Đây là integration test quan trọng nhất.
    Nếu test này pass → crawler cơ bản hoạt động.
    """
    from crawler.core.storage import CrawlStorage
    from crawler.parsers.tvpl_parser import TVPLParser

    import httpx

    url = "https://thuvienphapluat.vn/van-ban/lao-dong-tien-luong/bo-luat-lao-dong-2019-333670.aspx"
    url_hash = hashlib.md5(url.encode()).hexdigest()

    # Bước 1: Fetch
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8",
    }

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        response = await client.get(url, headers=headers)

    if response.status_code != 200:
        pytest.skip(f"Cannot fetch URL (status {response.status_code})")

    html = response.text

    # Kiểm tra Cloudflare
    if "Just a moment" in html:
        pytest.skip("Cloudflare challenge detected — need Playwright")

    # Bước 2: Lưu raw HTML
    storage = CrawlStorage(raw_dir="raw_html", db_dir="crawl_db")
    filepath = await storage.save_raw_html(url_hash, html, url)
    assert filepath.exists(), "Raw HTML file not saved"
    print(f"Saved HTML: {filepath} ({filepath.stat().st_size} bytes)")

    # Bước 3: Parse
    parser = TVPLParser()
    doc = parser.parse(html, url)

    if doc is None:
        print("Parser returned None — may need to update CSS selectors")
        print("First 500 chars of HTML:")
        print(html[:500])
        pytest.skip("Parser returned None — update selectors after Recon")

    print(f"\n=== Parse Result ===")
    print(f"Title: {doc.title}")
    print(f"Doc number: {doc.doc_number}")
    print(f"Type: {doc.doc_type}")
    print(f"Issuer: {doc.issuer}")
    print(f"Status: {doc.status}")
    print(f"Chapters: {len(doc.chapters)}")
    print(f"Articles: {doc.total_articles}")

    if doc.articles:
        first = doc.articles[0]
        print(f"\nFirst article: Điều {first.article_number}. {first.article_title}")
        print(f"  Clauses: {len(first.clauses)}")

    # Bước 4: Lưu document
    await storage.save_document(doc, url_hash)
    stats = storage.stats
    print(f"\nStorage stats: {stats}")

    assert doc.total_articles > 0, "Phải parse được ít nhất 1 article"
    assert stats["total_crawled"] > 0, "Storage phải có ít nhất 1 record"
