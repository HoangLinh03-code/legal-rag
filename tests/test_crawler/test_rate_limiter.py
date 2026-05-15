"""
Test Rate Limiter — Verify tốc độ crawl đúng config.

Chạy: uv run pytest tests/test_crawler/test_rate_limiter.py -v
"""

import asyncio
import time
import pytest
from crawler.core.rate_limiter import (
    TokenBucketRateLimiter,
    DomainRateConfig,
    DOMAIN_CONFIGS,
)


class TestDomainRateConfig:
    """Test cấu hình rate limit cho các domain."""

    def test_tvpl_config_exists(self):
        """TVPL phải có config riêng."""
        assert "thuvienphapluat.vn" in DOMAIN_CONFIGS

    def test_lvn_config_exists(self):
        """LVN phải có config riêng."""
        assert "luatvietnam.vn" in DOMAIN_CONFIGS

    def test_tvpl_rate_is_slow(self):
        """TVPL rate phải ≤ 4 requests/phút (rất chậm vì Cloudflare)."""
        config = DOMAIN_CONFIGS["thuvienphapluat.vn"]
        assert config.requests_per_minute <= 4

    def test_delay_range_valid(self):
        """min_delay phải < max_delay."""
        for domain, config in DOMAIN_CONFIGS.items():
            assert config.min_delay_seconds < config.max_delay_seconds, \
                f"{domain}: min_delay >= max_delay"

    def test_burst_limit_is_one(self):
        """Không cho phép burst với các site pháp luật."""
        for domain, config in DOMAIN_CONFIGS.items():
            assert config.burst_limit == 1, f"{domain}: burst_limit != 1"


class TestTokenBucketRateLimiter:
    """Test TokenBucketRateLimiter behavior."""

    def test_init_with_known_domain(self):
        """Khởi tạo với domain có config."""
        limiter = TokenBucketRateLimiter("thuvienphapluat.vn")
        assert limiter.domain == "thuvienphapluat.vn"
        assert limiter.config.requests_per_minute == 4

    def test_init_with_unknown_domain(self):
        """Domain không có config → fallback LVN config."""
        limiter = TokenBucketRateLimiter("unknown.vn")
        assert limiter.config == DOMAIN_CONFIGS["luatvietnam.vn"]

    def test_stats_initial(self):
        """Stats ban đầu phải đúng."""
        limiter = TokenBucketRateLimiter("luatvietnam.vn")
        stats = limiter.stats
        assert stats["total_requests"] == 0
        assert stats["domain"] == "luatvietnam.vn"

    @pytest.mark.asyncio
    async def test_acquire_adds_delay(self):
        """acquire() phải tạo delay ≥ min_delay_seconds."""
        # Dùng config nhỏ để test nhanh
        limiter = TokenBucketRateLimiter("luatvietnam.vn")
        # Override config cho test nhanh
        limiter.config = DomainRateConfig(
            requests_per_minute=60,  # 1/giây
            min_delay_seconds=0.1,   # Delay rất nhỏ cho test
            max_delay_seconds=0.2,
            burst_limit=1,
            crawl_hours=(0, 24),     # Cho phép mọi giờ
        )

        start = time.monotonic()
        await limiter.acquire()
        elapsed = time.monotonic() - start

        assert elapsed >= 0.1, f"Delay quá ngắn: {elapsed:.3f}s"

    @pytest.mark.asyncio
    async def test_acquire_updates_stats(self):
        """acquire() phải tăng request count."""
        limiter = TokenBucketRateLimiter("luatvietnam.vn")
        limiter.config = DomainRateConfig(
            requests_per_minute=60,
            min_delay_seconds=0.01,
            max_delay_seconds=0.02,
            burst_limit=1,
            crawl_hours=(0, 24),
        )

        await limiter.acquire()
        assert limiter.stats["total_requests"] == 1

        await limiter.acquire()
        assert limiter.stats["total_requests"] == 2
