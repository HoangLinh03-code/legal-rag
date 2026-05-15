"""
Rate Limiter — Token Bucket Algorithm cho crawling.

Tại sao không dùng sleep() đơn giản?
- sleep() cố định → dễ bị detect pattern
- Token bucket cho phép burst nhỏ khi cần, nhưng vẫn giữ rate trung bình thấp
- Kết hợp jitter (delay ngẫu nhiên) → hành vi giống người thực

Nguyên lý Token Bucket:
- Mỗi giây, thêm (requests_per_minute / 60) tokens vào bucket
- Mỗi request tiêu 1 token
- Nếu không đủ token → chờ cho đến khi có
- burst_limit = 1 nghĩa là KHÔNG cho phép gửi 2 request liên tiếp
"""

import asyncio
import time
import random
from dataclasses import dataclass
from typing import Dict


@dataclass
class DomainRateConfig:
    """
    Cấu hình rate limit cho từng domain.

    Attributes:
        requests_per_minute: Số request tối đa mỗi phút (VD: 4 = ~15s/request)
        min_delay_seconds: Delay tối thiểu giữa 2 requests (jitter lower bound)
        max_delay_seconds: Delay tối đa (jitter upper bound)
        burst_limit: Số request liên tiếp tối đa (1 = không burst)
        night_crawl: Có crawl ban đêm không
        crawl_hours: Tuple (giờ bắt đầu, giờ kết thúc) — VD: (8, 22)
    """
    requests_per_minute: float
    min_delay_seconds: float
    max_delay_seconds: float
    burst_limit: int = 1
    night_crawl: bool = False
    crawl_hours: tuple[int, int] = (8, 22)


# Config cho từng domain — dựa trên phân tích thực tế
DOMAIN_CONFIGS: Dict[str, DomainRateConfig] = {
    "thuvienphapluat.vn": DomainRateConfig(
        requests_per_minute=4,       # ~1 request / 15 giây — rất chậm vì có Cloudflare
        min_delay_seconds=10,        # Tối thiểu 10s giữa 2 requests
        max_delay_seconds=25,        # Tối đa 25s (random)
        burst_limit=1,               # Không burst — TVPL rất nhạy
        crawl_hours=(9, 21),         # Chỉ crawl giờ hành chính + tối
    ),
    "luatvietnam.vn": DomainRateConfig(
        requests_per_minute=6,       # ~1 request / 10 giây — ít bảo vệ hơn
        min_delay_seconds=8,
        max_delay_seconds=20,
        burst_limit=1,
        crawl_hours=(8, 22),
    ),
}


class TokenBucketRateLimiter:
    """
    Token bucket rate limiter với jitter và giờ crawl.

    Thread-safe với asyncio.Lock — an toàn khi dùng trong async code.

    Usage:
        limiter = TokenBucketRateLimiter("thuvienphapluat.vn")
        wait_time = await limiter.acquire()  # Chờ đến khi được phép gửi request
        # → gửi request ở đây
    """

    def __init__(self, domain: str):
        """
        Khởi tạo rate limiter cho domain cụ thể.

        Args:
            domain: Tên domain (VD: "thuvienphapluat.vn")
                    Nếu domain không có trong DOMAIN_CONFIGS, dùng config của luatvietnam.vn
        """
        self.domain = domain
        self.config = DOMAIN_CONFIGS.get(domain, DOMAIN_CONFIGS["luatvietnam.vn"])
        self._tokens = float(self.config.burst_limit)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()
        self._request_count = 0
        self._session_start = time.time()

    async def acquire(self) -> float:
        """
        Chờ cho đến khi có thể gửi request tiếp theo.

        Flow:
        1. Kiểm tra giờ crawl → chờ nếu ngoài giờ
        2. Refill tokens dựa trên thời gian đã trôi qua
        3. Nếu không đủ token → tính thời gian chờ → sleep
        4. Thêm jitter ngẫu nhiên (human-like)
        5. Sau 15 requests → nghỉ dài 1-3 phút

        Returns:
            float: Số giây đã chờ (jitter)
        """
        async with self._lock:
            # Bước 1: Kiểm tra giờ crawl
            await self._wait_for_crawl_hours()

            # Bước 2: Refill tokens theo thời gian
            now = time.monotonic()
            elapsed = now - self._last_refill
            refill = elapsed * (self.config.requests_per_minute / 60.0)
            self._tokens = min(self.config.burst_limit, self._tokens + refill)
            self._last_refill = now

            # Bước 3: Chờ nếu không đủ token
            if self._tokens < 1:
                wait_time = (1 - self._tokens) / (self.config.requests_per_minute / 60.0)
                await asyncio.sleep(wait_time)
                self._tokens = 0
            else:
                self._tokens -= 1

            # Bước 4: Jitter ngẫu nhiên — quan trọng nhất cho anti-detection
            jitter = random.uniform(
                self.config.min_delay_seconds,
                self.config.max_delay_seconds
            )

            # Bước 5: "Page break" — nghỉ dài sau mỗi 15 requests
            self._request_count += 1
            if self._request_count % 15 == 0:
                long_break = random.uniform(60, 180)  # 1-3 phút
                await asyncio.sleep(long_break)

            await asyncio.sleep(jitter)
            return jitter

    async def _wait_for_crawl_hours(self) -> None:
        """
        Chờ đến giờ được phép crawl nếu hiện tại ngoài giờ.

        VD: Nếu config.crawl_hours = (9, 21) và bây giờ là 23h
        → chờ đến 9h sáng hôm sau
        """
        from datetime import datetime, timedelta

        hour = datetime.now().hour
        start, end = self.config.crawl_hours

        if not (start <= hour < end):
            now = datetime.now()
            next_start = now.replace(hour=start, minute=0, second=0, microsecond=0)
            if now.hour >= end:
                next_start += timedelta(days=1)
            wait_secs = (next_start - now).total_seconds()
            if wait_secs > 0:
                await asyncio.sleep(wait_secs)

    @property
    def stats(self) -> dict:
        """Trả về thống kê hiện tại của rate limiter."""
        return {
            "domain": self.domain,
            "total_requests": self._request_count,
            "tokens_remaining": self._tokens,
            "session_duration_seconds": time.time() - self._session_start,
        }
