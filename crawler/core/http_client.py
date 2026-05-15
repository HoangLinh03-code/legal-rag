"""
Stealth HTTP Client — Giả lập browser thực để crawl.

Tại sao cần stealth?
- Các trang pháp luật VN kiểm tra User-Agent, headers, cookies
- Request từ httpx thuần bị block ngay vì thiếu browser headers
- Client này thêm đầy đủ headers giống Chrome thực

Features:
- Rate limiting tự động (TokenBucket)
- UA rotation sau mỗi 10 requests
- Session cookie management
- Ban detection + auto recovery
- Exponential backoff retry
"""

import asyncio
import random
import logging
from typing import Optional

import httpx

from .rate_limiter import TokenBucketRateLimiter
from .ban_detector import BanDetector
from .proxy_pool import ProxyPool

logger = logging.getLogger(__name__)


class StealthHTTPClient:
    """
    Async HTTP client giả lập browser thực.
    Tự động rotate UA, handle retry, detect ban.

    Usage:
        client = StealthHTTPClient("thuvienphapluat.vn")
        response = await client.get("https://thuvienphapluat.vn/van-ban/...")
    """

    # User-Agent phổ biến tại Việt Nam (Chrome, Firefox, Edge)
    UA_POOL = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Linux; Android 13; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.6367.82 Mobile Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    ]

    def __init__(self, domain: str, proxy_pool: Optional[ProxyPool] = None):
        """
        Khởi tạo HTTP client cho domain cụ thể.

        Args:
            domain: Domain target (VD: "thuvienphapluat.vn")
            proxy_pool: ProxyPool instance (optional, None = direct connection)
        """
        self.domain = domain
        self.rate_limiter = TokenBucketRateLimiter(domain)
        self.ban_detector = BanDetector()
        self.proxy_pool = proxy_pool
        self._current_ua = random.choice(self.UA_POOL)
        self._session_cookies: dict = {}
        self._request_count = 0

    def _build_headers(self, referer: Optional[str] = None) -> dict:
        """
        Build headers giống browser thực.

        Headers quan trọng nhất:
        - User-Agent: phải match browser thực
        - Accept-Language: vi-VN (traffic từ VN)
        - Sec-Fetch-*: Chrome security headers
        """
        headers = {
            "User-Agent": self._current_ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin" if referer else "none",
            "Cache-Control": "max-age=0",
        }
        if referer:
            headers["Referer"] = referer
        return headers

    async def get(
        self,
        url: str,
        referer: Optional[str] = None,
        max_retries: int = 3,
    ) -> httpx.Response:
        """
        GET request với rate limiting, retry và ban detection.

        Flow:
        1. Chờ rate limiter (có thể mất 10-25s)
        2. Rotate UA nếu cần (mỗi 10 requests)
        3. Gửi request với headers + cookies + proxy
        4. Kiểm tra ban → recovery nếu cần
        5. Retry nếu lỗi mạng

        Args:
            url: URL cần fetch
            referer: URL trang trước (tăng tính tin cậy)
            max_retries: Số lần retry tối đa khi lỗi

        Returns:
            httpx.Response: Response từ server

        Raises:
            RuntimeError: Nếu tất cả retries đều thất bại
        """
        # Rate limiting — chờ đến lượt
        await self.rate_limiter.acquire()

        # Rotate UA sau mỗi 10 requests
        self._request_count += 1
        if self._request_count % 10 == 0:
            self._current_ua = random.choice(self.UA_POOL)

        proxy = self.proxy_pool.get_proxy() if self.proxy_pool else None

        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(
                    proxy=proxy,
                    timeout=30.0,
                    follow_redirects=True,
                    cookies=self._session_cookies,
                ) as client:
                    response = await client.get(
                        url,
                        headers=self._build_headers(referer),
                    )

                # Cập nhật cookies từ response
                self._session_cookies.update(dict(response.cookies))

                # Kiểm tra ban
                ban_action = self.ban_detector.check(response)
                if ban_action:
                    await self.ban_detector.handle(ban_action, self.proxy_pool)
                    if self.proxy_pool:
                        proxy = self.proxy_pool.get_proxy()
                    continue

                return response

            except (httpx.ConnectError, httpx.TimeoutException) as e:
                logger.warning(f"[HTTP] Attempt {attempt+1}/{max_retries} failed: {e}")
                if attempt == max_retries - 1:
                    raise
                # Exponential backoff
                wait = (2 ** attempt) * 5 + random.uniform(0, 5)
                await asyncio.sleep(wait)

        raise RuntimeError(f"Failed to fetch {url} after {max_retries} attempts")
