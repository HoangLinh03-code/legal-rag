"""
Recon Script — Phân tích cấu trúc HTML thực từ TVPL trước khi crawl.

Mục đích:
1. Fetch 1 trang thực → kiểm tra CSS selectors
2. In ra những gì parser extract được
3. Nếu selectors sai → bạn biết cần sửa gì

Chạy: uv run python -m crawler.recon
"""

import asyncio
import sys
import hashlib
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from .parsers.tvpl_parser import TVPLParser
from .core.storage import CrawlStorage


# URLs mẫu để test — các văn bản phổ biến
RECON_URLS = [
    # Bộ luật Lao động 2019
    "https://thuvienphapluat.vn/van-ban/Lao-dong-Tien-luong/Bo-Luat-lao-dong-2019-333670.aspx",
    # Bộ luật Dân sự 2015
    "https://thuvienphapluat.vn/van-ban/Quyen-dan-su/Bo-luat-dan-su-2015-296215.aspx",
]

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


async def recon_single(url: str, save_html: bool = True) -> dict:
    """
    Recon 1 URL: fetch + analyze HTML.

    Returns dict với kết quả phân tích.
    """
    print(f"\n{'='*70}")
    print(f"RECON: {url}")
    print(f"{'='*70}")

    # Fetch
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        response = await client.get(url, headers=HEADERS)

    print(f"Status: {response.status_code}")
    print(f"Content-Length: {len(response.text):,} chars")
    print(f"Content-Type: {response.headers.get('content-type', 'N/A')}")
    print(f"CF-Ray: {response.headers.get('cf-ray', 'Không có (không Cloudflare)')}")

    html = response.text

    # Kiểm tra Cloudflare
    is_cloudflare = "Just a moment" in html or "cf-browser-verification" in html
    print(f"Cloudflare Challenge: {'CÓ ⚠️' if is_cloudflare else 'KHÔNG ✓'}")

    if is_cloudflare:
        print("\n⚠️  Bị Cloudflare challenge!")
        print("   → Cần dùng Playwright để bypass")
        print("   → Hoặc thử lại sau vài phút")
        return {"status": "cloudflare", "url": url}

    # Lưu HTML
    if save_html:
        url_hash = hashlib.md5(url.encode()).hexdigest()
        storage = CrawlStorage(raw_dir="raw_html", db_dir="crawl_db")
        filepath = await storage.save_raw_html(url_hash, html, url)
        print(f"Saved HTML: {filepath}")

    # Phân tích HTML
    soup = BeautifulSoup(html, "html.parser")
    parser = TVPLParser()

    print(f"\n--- CSS Selector Analysis ---")

    # Test từng selector
    for name, selectors in parser.SELECTORS.items():
        for sel in selectors.split(", "):
            el = soup.select_one(sel)
            if el:
                text = el.get_text(strip=True)[:100]
                print(f"  ✓ {name} [{sel}]: '{text}'")
            else:
                print(f"  ✗ {name} [{sel}]: NOT FOUND")

    # Thử tìm content area khác nếu selectors mặc định không match
    print(f"\n--- Content Area Detection ---")
    # Tìm div lớn nhất chứa "Điều"
    all_divs = soup.find_all("div")
    best_div = None
    best_count = 0
    for div in all_divs:
        text = div.get_text()
        count = text.count("Điều ")
        if count > best_count:
            best_count = count
            best_div = div
            best_id = div.get("id", "")
            best_class = div.get("class", [])

    if best_div:
        print(f"  Div chứa nhiều 'Điều' nhất:")
        print(f"    id='{best_id}', class={best_class}")
        print(f"    Số lần 'Điều' xuất hiện: {best_count}")
        print(f"    Text length: {len(best_div.get_text()):,} chars")

    # Tìm h1/h2 cho title
    print(f"\n--- Title Detection ---")
    for tag in ["h1", "h2", "h3"]:
        elements = soup.select(tag)
        for el in elements[:3]:
            text = el.get_text(strip=True)[:120]
            cls = el.get("class", [])
            el_id = el.get("id", "")
            print(f"  <{tag} class='{cls}' id='{el_id}'>: '{text}'")

    # Parse thử
    print(f"\n--- Parse Result ---")
    doc = parser.parse(html, url)

    result = {"status": "ok", "url": url}

    if doc:
        print(f"  ✓ Title: {doc.title}")
        print(f"  ✓ Doc Number: {doc.doc_number}")
        print(f"  ✓ Type: {doc.doc_type}")
        print(f"  ✓ Issuer: {doc.issuer}")
        print(f"  ✓ Issue Date: {doc.issue_date}")
        print(f"  ✓ Status: {doc.status}")
        print(f"  ✓ Chapters: {len(doc.chapters)}")
        print(f"  ✓ Articles: {doc.total_articles}")

        if doc.articles:
            print(f"\n  --- Sample Articles ---")
            for art in doc.articles[:3]:
                print(f"    Điều {art.article_number}. {art.article_title[:60]}")
                print(f"      Clauses: {len(art.clauses)}")

            last = doc.articles[-1]
            print(f"    ...")
            print(f"    Điều {last.article_number}. {last.article_title[:60]}")
            print(f"      Clauses: {len(last.clauses)}")

        result["parsed"] = True
        result["articles"] = doc.total_articles
        result["chapters"] = len(doc.chapters)
    else:
        print(f"  ✗ Parser returned None!")
        print(f"  → Cần cập nhật CSS selectors")
        print(f"  → Xem HTML đã lưu trong raw_html/ để tìm selectors đúng")
        result["parsed"] = False

    return result


async def recon_listing_page(doc_type: str = "Bo-Luat") -> list[str]:
    """
    Recon trang danh sách văn bản — tìm cách discover URLs.
    """
    print(f"\n{'='*70}")
    print(f"RECON LISTING: {doc_type}")
    print(f"{'='*70}")

    # Thử nhiều URL pattern
    url_patterns = [
        f"https://thuvienphapluat.vn/van-ban/{doc_type}",
        f"https://thuvienphapluat.vn/page/tim-van-ban.aspx?type=0&s=0&sig=0",
    ]

    for url in url_patterns:
        print(f"\nTrying: {url}")
        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                response = await client.get(url, headers=HEADERS)

            print(f"  Status: {response.status_code}")
            print(f"  Final URL: {response.url}")

            if response.status_code != 200:
                continue

            soup = BeautifulSoup(response.text, "html.parser")

            # Tìm links đến văn bản
            links = []

            # Pattern 1: links chứa /van-ban/ và .aspx
            for a in soup.select("a[href*='/van-ban/']"):
                href = a.get("href", "")
                if ".aspx" in href and href not in links:
                    links.append(href)

            # Pattern 2: links với class title
            for a in soup.select("a.title, a.doc-title"):
                href = a.get("href", "")
                if href and href not in links:
                    links.append(href)

            print(f"  Links found: {len(links)}")
            if links:
                print(f"  Sample links:")
                for link in links[:5]:
                    print(f"    → {link}")

            return links

        except Exception as e:
            print(f"  Error: {e}")

    return []


async def main():
    """Main recon flow."""
    print("🔍 RECON — Phân tích thuvienphapluat.vn")
    print("="*70)

    results = []

    # Phase 1: Recon detail pages
    print("\n📄 PHASE 1: Phân tích trang chi tiết văn bản")
    for url in RECON_URLS:
        result = await recon_single(url)
        results.append(result)
        # Delay giữa các requests
        print("\n⏳ Chờ 5s trước request tiếp...")
        await asyncio.sleep(5)

    # Phase 2: Recon listing page
    print("\n📋 PHASE 2: Phân tích trang danh sách văn bản")
    links = await recon_listing_page()

    # Summary
    print(f"\n{'='*70}")
    print("📊 RECON SUMMARY")
    print(f"{'='*70}")
    for r in results:
        status = "✓ Parsed" if r.get("parsed") else "✗ Failed"
        articles = r.get("articles", 0)
        print(f"  {status} | {r['url'][:60]}... | {articles} articles")

    if links:
        print(f"\n  Listing page: {len(links)} links found")
    else:
        print(f"\n  Listing page: No links found — cần phân tích thêm")

    # Kiểm tra kết quả
    parsed_count = sum(1 for r in results if r.get("parsed"))
    if parsed_count == len(results):
        print(f"\n✅ Tất cả {parsed_count} URLs parse thành công!")
        print("   → Sẵn sàng crawl hàng loạt")
    elif parsed_count > 0:
        print(f"\n⚠️  {parsed_count}/{len(results)} URLs parse thành công")
        print("   → Cần cập nhật selectors cho URLs thất bại")
    else:
        print(f"\n❌ Không parse được URL nào!")
        print("   → Cần xem HTML trong raw_html/ và cập nhật CSS selectors")


if __name__ == "__main__":
    asyncio.run(main())
