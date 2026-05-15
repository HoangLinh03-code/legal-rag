"""
Ban Detector — Phát hiện sớm dấu hiệu bị block.

Khi crawl, ta cần nhận biết NGAY khi bị block để:
1. Không tiếp tục gửi request (sẽ bị ban nặng hơn)
2. Thực hiện recovery phù hợp (sleep, đổi proxy, chuyển Playwright)

Mỗi dấu hiệu ban có 1 action tương ứng — hệ thống tự phản ứng.
"""

import asyncio
import random
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class BanDetector:
    """
    Phát hiện và xử lý các dấu hiệu bị block khi crawl.

    Kiểm tra 3 loại dấu hiệu:
    1. HTTP status codes (403, 429, 503)
    2. Nội dung response (Cloudflare challenge, CAPTCHA)
    3. Redirect bất thường

    Usage:
        detector = BanDetector()
        action = detector.check(response)
        if action:
            await detector.handle(action, proxy_pool)
    """

    # Danh sách dấu hiệu ban và action tương ứng
    BAN_INDICATORS = [
        # --- HTTP Status Codes ---
        {"type": "status", "value": 403, "action": "rotate_proxy_immediately",
         "description": "Forbidden — IP bị block hoàn toàn"},
        {"type": "status", "value": 429, "action": "sleep_30min",
         "description": "Too Many Requests — rate limit triggered"},
        {"type": "status", "value": 503, "action": "sleep_10min",
         "description": "Service Unavailable — có thể tạm thời hoặc bị block"},

        # --- Cloudflare Challenges ---
        {"type": "content", "contains": "cf-browser-verification", "action": "use_playwright",
         "description": "Cloudflare browser verification challenge"},
        {"type": "content", "contains": "Just a moment", "action": "use_playwright",
         "description": "Cloudflare 'Just a moment' interstitial page"},
        {"type": "content", "contains": "Checking your browser", "action": "use_playwright",
         "description": "Cloudflare browser check"},

        # --- CAPTCHA / Honeypot ---
        {"type": "content", "contains": "captcha", "action": "sleep_1hour",
         "description": "CAPTCHA detected — cần nghỉ lâu"},
        {"type": "content", "contains": "robot", "action": "rotate_identity",
         "description": "Bot detection triggered"},

        # --- Redirect bất thường ---
        {"type": "redirect_to", "contains": "blocked", "action": "rotate_proxy_immediately",
         "description": "Redirect đến trang block"},
        {"type": "redirect_to", "contains": "error", "action": "sleep_15min",
         "description": "Redirect đến trang error"},
    ]

    def __init__(self):
        """Khởi tạo ban detector với bộ đếm."""
        self._ban_count = 0        # Tổng số lần phát hiện ban
        self._consecutive_bans = 0  # Số lần ban liên tiếp (reset khi request thành công)

    def check(self, response: httpx.Response) -> Optional[str]:
        """
        Kiểm tra response có dấu hiệu bị ban không.

        Args:
            response: httpx.Response từ request

        Returns:
            str: Tên action cần thực hiện (VD: "sleep_30min")
            None: Nếu không phát hiện ban
        """
        # Kiểm tra status code
        for indicator in self.BAN_INDICATORS:
            if indicator["type"] == "status":
                if response.status_code == indicator["value"]:
                    self._record_ban(indicator)
                    return indicator["action"]

            elif indicator["type"] == "content":
                # Chỉ check content nếu response có body
                try:
                    text = response.text.lower()
                    if indicator["contains"].lower() in text:
                        self._record_ban(indicator)
                        return indicator["action"]
                except Exception:
                    pass

            elif indicator["type"] == "redirect_to":
                # Kiểm tra URL cuối cùng sau redirect
                final_url = str(response.url).lower()
                if indicator["contains"].lower() in final_url:
                    self._record_ban(indicator)
                    return indicator["action"]

        # Không bị ban → reset consecutive counter
        self._consecutive_bans = 0
        return None

    def _record_ban(self, indicator: dict) -> None:
        """Ghi log và cập nhật thống kê khi phát hiện ban."""
        self._ban_count += 1
        self._consecutive_bans += 1
        logger.warning(
            f"[BAN DETECTED] {indicator['description']} "
            f"(total: {self._ban_count}, consecutive: {self._consecutive_bans})"
        )

    async def handle(self, action: str, proxy_pool=None) -> None:
        """
        Thực hiện recovery action khi bị ban.

        Args:
            action: Tên action từ check() (VD: "sleep_30min")
            proxy_pool: Optional ProxyPool instance để rotate proxy

        Các action có thể:
        - rotate_proxy_immediately: Đổi proxy ngay
        - sleep_Xmin: Nghỉ X phút + jitter
        - use_playwright: Cần chuyển sang Playwright (caller xử lý)
        - rotate_identity: Đổi proxy + UA + xóa cookies
        """
        if action == "rotate_proxy_immediately":
            if proxy_pool:
                proxy_pool.rotate()
            logger.info("[RECOVERY] Rotated proxy")

        elif action == "sleep_30min":
            wait = 1800 + random.uniform(0, 600)  # 30-40 phút
            logger.info(f"[RECOVERY] Sleeping {wait:.0f}s (429 rate limit)")
            await asyncio.sleep(wait)

        elif action == "sleep_10min":
            wait = 600 + random.uniform(0, 300)  # 10-15 phút
            logger.info(f"[RECOVERY] Sleeping {wait:.0f}s (503)")
            await asyncio.sleep(wait)

        elif action == "sleep_15min":
            wait = 900 + random.uniform(0, 300)  # 15-20 phút
            logger.info(f"[RECOVERY] Sleeping {wait:.0f}s (redirect error)")
            await asyncio.sleep(wait)

        elif action == "sleep_1hour":
            wait = 3600 + random.uniform(0, 1800)  # 1-1.5 giờ
            logger.info(f"[RECOVERY] Sleeping {wait:.0f}s (CAPTCHA detected)")
            await asyncio.sleep(wait)

        elif action == "use_playwright":
            # Caller cần handle — chuyển sang PlaywrightStealthClient
            logger.info("[RECOVERY] Switching to Playwright mode (Cloudflare)")

        elif action == "rotate_identity":
            if proxy_pool:
                proxy_pool.rotate()
            logger.info("[RECOVERY] Rotated full identity (proxy + UA)")

        else:
            logger.warning(f"[RECOVERY] Unknown action: {action}")

    @property
    def is_heavily_banned(self) -> bool:
        """
        Kiểm tra có bị ban nặng không (≥ 3 lần liên tiếp).
        Nếu True → nên dừng crawl hoàn toàn.
        """
        return self._consecutive_bans >= 3

    @property
    def stats(self) -> dict:
        """Trả về thống kê ban detection."""
        return {
            "total_bans": self._ban_count,
            "consecutive_bans": self._consecutive_bans,
            "is_heavily_banned": self.is_heavily_banned,
        }
