"""
Playwright Stealth Client — Bypass Cloudflare bằng headless browser.

Khi nào dùng Playwright thay vì httpx?
- thuvienphapluat.vn có Cloudflare → httpx bị challenge
- Nội dung load bằng JavaScript → cần browser render
- httpx bị block → fallback sang Playwright

Playwright chậm hơn httpx ~10x nhưng bypass được hầu hết anti-bot.
"""

import asyncio
import random
import logging

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

logger = logging.getLogger(__name__)


class PlaywrightStealthClient:
    """
    Playwright client với stealth mode để bypass Cloudflare.
    Chỉ dùng khi httpx bị block.

    Usage (async context manager):
        async with PlaywrightStealthClient() as client:
            html = await client.get_html("https://thuvienphapluat.vn/...")
    """

    def __init__(self, headless: bool = True):
        """
        Args:
            headless: True = không hiện browser (production).
                      False = hiện browser (debug, xem behavior).
        """
        self.headless = headless
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._playwright = None

    async def __aenter__(self):
        """
        Khởi tạo browser với stealth config:
        - Viewport 1366x768 (phổ biến ở VN)
        - Locale vi-VN, timezone Asia/Ho_Chi_Minh
        - Inject scripts ẩn dấu hiệu automation
        """
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--lang=vi-VN",
            ],
        )
        self._context = await self._browser.new_context(
            viewport={"width": 1366, "height": 768},
            locale="vi-VN",
            timezone_id="Asia/Ho_Chi_Minh",
            user_agent=random.choice([
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
            ]),
            extra_http_headers={
                "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8",
            },
        )
        # Inject stealth scripts — ẩn navigator.webdriver
        await self._context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
            Object.defineProperty(navigator, 'languages', { get: () => ['vi-VN', 'vi', 'en-US'] });
            window.chrome = { runtime: {} };
        """)
        return self

    async def get_html(self, url: str, wait_selector: str = "body") -> str:
        """
        Load page và trả HTML sau khi JS render xong.

        Args:
            url: URL cần load
            wait_selector: CSS selector chờ xuất hiện (đảm bảo content đã load)

        Returns:
            str: Full HTML của trang
        """
        page: Page = await self._context.new_page()
        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await page.wait_for_selector(wait_selector, timeout=10000)

            # Simulate human: scroll xuống từ từ
            await self._human_scroll(page)

            # Random delay trước khi lấy content
            await asyncio.sleep(random.uniform(1.5, 3.5))

            return await page.content()
        finally:
            await page.close()

    async def _human_scroll(self, page: Page) -> None:
        """
        Simulate human scrolling — cuộn trang từ từ như người thực.
        Giúp trigger lazy-load content và tránh bot detection.
        """
        total_height = await page.evaluate("document.body.scrollHeight")
        viewport_height = 768
        steps = total_height // viewport_height

        for i in range(min(steps, 5)):  # Tối đa 5 lần scroll
            await page.evaluate(f"window.scrollBy(0, {viewport_height})")
            await asyncio.sleep(random.uniform(0.3, 0.8))

    async def __aexit__(self, *args):
        """Cleanup: đóng browser và Playwright."""
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
