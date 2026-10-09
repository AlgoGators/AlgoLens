"""Postgres-backed strategy registry with a built-in fallback."""

import logging

import psycopg2

from algolens.infrastructure.db.postgres import get_db_connection

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
        "lifecycle": "live",
        "sort_order": 0,
    }
]


def _normalize(row):
    """Coerce a DB row into the strategy config shape used by the app."""
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
        "lifecycle": row.get("lifecycle") or "live",
        "sort_order": int(row.get("sort_order") or 0),
        # Migration 023 (trade-ngin): grouping for the portfolio switcher and
        # the desk-editing gate. Absent before 023 -> ungrouped, not editable.
        "portfolio_group": row.get("portfolio_group"),
        "desk_editable": bool(row.get("desk_editable") or False),
    }


# Columns read when present; each was added by a later migration.
_OPTIONAL_COLUMNS = ("lifecycle", "portfolio_group", "desk_editable")


def _optional_columns(cursor):
    cursor.execute(
        """
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = 'trading' AND table_name = 'strategy_registry'
          AND column_name = ANY(%s)
        """,
        (list(_OPTIONAL_COLUMNS),),
    )
    present = {row["column_name"] for row in cursor.fetchall()}
    # Fixed order, never caller-controlled text, so it is safe to splice in.
    return [column for column in _OPTIONAL_COLUMNS if column in present]


class PostgresStrategyRegistry:
    def __init__(self, connection_factory=None):
        self.connection_factory = connection_factory or get_db_connection

    def list(self, active_only=True):
        conn = None
        try:
            conn = self.connection_factory()
            with conn.cursor() as cursor:
                extra = "".join(f", {column}" for column in _optional_columns(cursor))
                cursor.execute(
                    "SELECT id, strategy_type, portfolio_id, name, description, "
                    "initial_equity, managers, is_active, sort_order"
                    + extra
                    + " FROM trading.strategy_registry ORDER BY sort_order ASC, id ASC"
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

        if active_only:
            registry = [
                strategy
                for strategy in registry
                if strategy["is_active"] and strategy.get("lifecycle", "live") == "live"
            ]
        return registry

    def get(self, strategy_id):
        for strategy in self.list(active_only=True):
            if strategy["id"] == strategy_id:
                return strategy
        return None

    def get_portfolio(self, portfolio_id):
        """The first live registry entry for a portfolio id, or None."""
        for strategy in self.list(active_only=True):
            if strategy["portfolio_id"] == portfolio_id:
                return strategy
        return None


def clear_registry_cache():
    """Compatibility no-op; registry reads intentionally remain uncached."""
    return None


def get_registry(active_only=True):
    return PostgresStrategyRegistry().list(active_only=active_only)


def get_strategy_config(strategy_id):
    return PostgresStrategyRegistry().get(strategy_id)
