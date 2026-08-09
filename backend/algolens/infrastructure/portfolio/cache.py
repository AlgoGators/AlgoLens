"""In-memory portfolio reader cache."""

import copy
import logging
import time
from collections.abc import Callable, Mapping
from typing import Any

from algolens.application.portfolio.ports import (
    PortfolioDetailRows,
    PortfolioReaderPort,
)

logger = logging.getLogger(__name__)


class CachedPortfolioReader:
    """Process-local TTL cache for expensive portfolio reads."""

    def __init__(
        self,
        reader: PortfolioReaderPort,
        ttl_seconds: float = 30,
        clock: Callable[[], float] | None = None,
    ):
        self.reader = reader
        self.ttl_seconds = ttl_seconds
        self.clock = clock or time.monotonic
        self._cache: dict[tuple[str, str, str], tuple[float, Any]] = {}

    def clear(self):
        self._cache.clear()

    def fetch_summary_row(
        self, strategy_type: str, portfolio_id: str
    ) -> Mapping[str, Any] | None:
        return self._cached(
            ("summary", strategy_type, portfolio_id),
            lambda: self.reader.fetch_summary_row(strategy_type, portfolio_id),
        )

    def fetch_detail_rows(
        self, strategy_type: str, portfolio_id: str
    ) -> PortfolioDetailRows:
        return self._cached(
            ("detail", strategy_type, portfolio_id),
            lambda: self.reader.fetch_detail_rows(strategy_type, portfolio_id),
        )

    def _cached(self, key, load):
        if self.ttl_seconds <= 0:
            return load()

        now = self.clock()
        entry = self._cache.get(key)
        if entry:
            expires_at, value = entry
            if now < expires_at:
                logger.info("[PORTFOLIO_CACHE] hit key=%s", key)
                return copy.deepcopy(value)

        logger.info("[PORTFOLIO_CACHE] miss key=%s", key)
        start = time.perf_counter()
        value = load()
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info("[PORTFOLIO_CACHE] fill key=%s elapsed_ms=%.0f", key, elapsed_ms)
        self._cache[key] = (now + self.ttl_seconds, copy.deepcopy(value))
        return copy.deepcopy(value)
