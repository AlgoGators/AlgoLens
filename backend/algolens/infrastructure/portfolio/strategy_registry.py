"""Postgres-backed strategy registry with a built-in fallback."""

import logging
import time

import psycopg2

from database import get_db_connection

logger = logging.getLogger(__name__)

DEFAULT_REGISTRY = [
    {
        "id": "trendfollowing",
        "strategy_type": "LIVE_TREND_FOLLOWING",
        "portfolio_id": "CONSERVATIVE_PORTFOLIO",
        "name": "Trend Following",
        "description": "Systematic trend following across multiple futures contracts",
        "initial_equity": 500000.0,
        "managers": ["AlgoLens System"],
        "is_active": True,
        "sort_order": 0,
    }
]

_CACHE_TTL_SECONDS = 60
_registry_cache = None
_registry_cache_expires_at = 0


def _copy_registry(registry):
    copied = []
    for strategy in registry:
        item = dict(strategy)
        item["managers"] = list(item.get("managers") or [])
        copied.append(item)
    return copied


def _cached_registry():
    if _registry_cache is None or time.monotonic() >= _registry_cache_expires_at:
        return None
    return _copy_registry(_registry_cache)


def _cache_registry(registry):
    global _registry_cache, _registry_cache_expires_at
    _registry_cache = _copy_registry(registry)
    _registry_cache_expires_at = time.monotonic() + _CACHE_TTL_SECONDS


def clear_registry_cache():
    global _registry_cache, _registry_cache_expires_at
    _registry_cache = None
    _registry_cache_expires_at = 0


def _normalize(row):
    return {
        "id": row["id"],
        "strategy_type": row["strategy_type"],
        "portfolio_id": row["portfolio_id"],
        "name": row["name"],
        "description": row.get("description") or "",
        "initial_equity": float(row["initial_equity"])
        if row.get("initial_equity") is not None
        else 500000.0,
        "managers": row.get("managers") or ["AlgoLens System"],
        "is_active": bool(row.get("is_active", True)),
        "sort_order": int(row.get("sort_order") or 0),
    }


class PostgresStrategyRegistry:
    def __init__(self, connection_factory=None):
        self.connection_factory = connection_factory or get_db_connection

    def list(self, active_only=True):
        registry = _cached_registry()
        if registry is not None:
            if active_only:
                registry = [strategy for strategy in registry if strategy["is_active"]]
            return registry

        conn = None
        try:
            conn = self.connection_factory()
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, strategy_type, portfolio_id, name, description,
                           initial_equity, managers, is_active, sort_order
                    FROM trading.strategy_registry
                    ORDER BY sort_order ASC, id ASC
                    """
                )
                rows = cursor.fetchall()

            registry = [_normalize(row) for row in rows]
            if not registry:
                logger.warning(
                    "[REGISTRY] strategy_registry table is empty; using built-in default"
                )
                registry = list(DEFAULT_REGISTRY)
        except (psycopg2.Error, ValueError) as exc:
            logger.warning(
                "[REGISTRY] Could not read strategy_registry (%s); using built-in default",
                getattr(exc, "pgcode", None) or str(exc),
            )
            registry = list(DEFAULT_REGISTRY)
        finally:
            if conn is not None:
                conn.close()

        _cache_registry(registry)
        if active_only:
            registry = [strategy for strategy in registry if strategy["is_active"]]
        return registry

    def get(self, strategy_id):
        for strategy in self.list(active_only=True):
            if strategy["id"] == strategy_id:
                return strategy
        return None


def get_registry(active_only=True):
    return PostgresStrategyRegistry().list(active_only=active_only)


def get_strategy_config(strategy_id):
    return PostgresStrategyRegistry().get(strategy_id)
