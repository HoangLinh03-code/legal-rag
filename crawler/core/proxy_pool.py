"""
Proxy Pool — Quản lý rotation proxy.

MVP: Có thể chạy không cần proxy — chỉ cần crawl đủ chậm.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class ProxyPool:
    """
    Quản lý pool proxy với round-robin rotation.

    Usage:
        pool = ProxyPool(["http://user:pass@proxy1:8080"])
        proxy = pool.get_proxy()
        pool.rotate()
        pool.mark_dead("http://...")
    """

    def __init__(self, proxies: Optional[list[str]] = None):
        self._proxies = list(proxies) if proxies else []
        self._dead_proxies: set[str] = set()
        self._current_index = 0

    def get_proxy(self) -> Optional[str]:
        """Lấy proxy hiện tại. None nếu không có."""
        alive = self._get_alive_proxies()
        if not alive:
            return None
        return alive[self._current_index % len(alive)]

    def rotate(self) -> Optional[str]:
        """Chuyển sang proxy tiếp theo (round-robin)."""
        alive = self._get_alive_proxies()
        if not alive:
            return None
        self._current_index = (self._current_index + 1) % len(alive)
        return alive[self._current_index]

    def mark_dead(self, proxy: str) -> None:
        """Đánh dấu proxy không hoạt động."""
        self._dead_proxies.add(proxy)

    def revive(self, proxy: str) -> None:
        """Đánh dấu proxy hoạt động trở lại."""
        self._dead_proxies.discard(proxy)

    def _get_alive_proxies(self) -> list[str]:
        return [p for p in self._proxies if p not in self._dead_proxies]

    @property
    def has_proxies(self) -> bool:
        return len(self._get_alive_proxies()) > 0

    @property
    def stats(self) -> dict:
        alive = self._get_alive_proxies()
        return {
            "total": len(self._proxies),
            "alive": len(alive),
            "dead": len(self._dead_proxies),
        }
