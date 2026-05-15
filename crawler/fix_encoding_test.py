"""
Test fix encoding - phan tich HTML TVPL.

Chay: uv run python crawler/fix_encoding_test.py
"""

import asyncio
import sys
import io
import httpx

# Fix console encoding cho Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')


async def test_fetch_no_brotli():
    """Fetch TVPL khong dung brotli encoding."""
    url = "https://thuvienphapluat.vn/van-ban/Lao-dong-Tien-luong/Bo-Luat-lao-dong-2019-333670.aspx"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
        # KHONG co Accept-Encoding: br
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
    }

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        response = await client.get(url, headers=headers)

    print(f"Status: {response.status_code}")
    print(f"Content-Type: {response.headers.get('content-type', 'N/A')}")
    print(f"Content-Encoding: {response.headers.get('content-encoding', 'N/A')}")
    print(f"Content length: {len(response.text):,} chars")

    html = response.text

    is_html = "<html" in html.lower() or "<!doctype" in html.lower()
    print(f"Is valid HTML: {is_html}")

    if is_html:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")

        print(f"\n--- Tim kiem selectors ---")

        # Tim tat ca h1, h2, h3
        for tag in ["h1", "h2", "h3"]:
            elements = soup.find_all(tag)
            for el in elements[:5]:
                text = el.get_text(strip=True)[:120]
                classes = el.get("class", [])
                el_id = el.get("id", "")
                print(f"  <{tag} class={classes} id='{el_id}'>: '{text}'")

        # Tim div chua "Dieu"
        print(f"\n--- Tim div chua 'Dieu' ---")
        all_divs = soup.find_all("div")
        for div in all_divs:
            text = div.get_text()
            count = text.count("Điều ")
            if count > 5:
                div_id = div.get("id", "")
                div_class = div.get("class", [])
                print(f"  div id='{div_id}' class={div_class}: {count} lan 'Dieu', {len(text):,} chars")

        # Tim metadata
        print(f"\n--- Tim metadata ---")
        for text_to_find in ["45/2019/QH14", "Quốc hội", "Còn hiệu lực", "20/11/2019"]:
            el = soup.find(string=lambda s, t=text_to_find: s and t in s)
            if el:
                parent = el.parent
                gparent = parent.parent if parent.parent else None
                gp_info = f" -> parent: <{gparent.name} class={gparent.get('class', [])} id='{gparent.get('id', '')}'>" if gparent else ""
                print(f"  '{text_to_find}': <{parent.name} class={parent.get('class', [])} id='{parent.get('id', '')}'>{gp_info}")

        # Tim cac table hoac div co class lien quan den metadata
        print(f"\n--- Tim cac element metadata khac ---")
        for selector in [
            ".doc-title", ".title", "#doctitle", 
            ".doc-number", "#sohieu", ".number",
            "#noidung", "#content", ".content",
            "#vanban", ".vbcontent", ".law-content",
            ".box-info", ".info", ".metadata",
            "table.info", ".thongtin",
        ]:
            el = soup.select_one(selector)
            if el:
                text = el.get_text(strip=True)[:100]
                print(f"  FOUND [{selector}]: '{text}'")

        # Luu HTML sach
        from pathlib import Path
        Path("raw_html/test_clean.html").write_text(html, encoding="utf-8")
        print(f"\n OK Saved clean HTML to raw_html/test_clean.html ({len(html):,} chars)")

        # In first 3000 chars de xem structure
        print(f"\n--- First 2000 chars of HTML ---")
        print(html[:2000])
    else:
        print(f"\nNOT valid HTML - first 200 chars:")
        print(repr(html[:200]))


if __name__ == "__main__":
    asyncio.run(test_fetch_no_brotli())
