"""Data-driven registry of the strategies AlgoLens can display.

Previously portfolio.py hardcoded the single 'trendfollowing' strategy: its API
id, its internal discriminator ('LIVE_TREND_FOLLOWING'), its display name,
description and starting equity were all string literals scattered through the
route handlers. Adding a second strategy meant editing code.

This module makes that lookup data-driven via the `trading.strategy_registry`
table (see migrations/001_create_strategy_registry.sql). To keep deploys safe when
the migration has not been applied yet, it falls back to a built-in default that is
identical to the values that used to be hardcoded -- so the app behaves the same
whether or not the table exists.
"""

import logging

import psycopg2

from database import get_db_connection

logger = logging.getLogger(__name__)


# Built-in fallback, used when the strategy_registry table is missing or empty.
# These values are exactly what portfolio.py used to hardcode.
DEFAULT_REGISTRY = [
    {
        "id": "trendfollowing",
        "strategy_type": "LIVE_TREND_FOLLOWING",
        # Required: the trading tables are keyed by portfolio as well as
        # strategy, and LIVE_TREND_FOLLOWING exists under more than one.
        # CONSERVATIVE_PORTFOLIO is the only one still being written.
        "portfolio_id": "CONSERVATIVE_PORTFOLIO",
        "name": "Trend Following",
        "description": "Systematic trend following across multiple futures contracts",
        "initial_equity": 500000.0,
        "managers": ["AlgoLens System"],
        "is_active": True,
        "sort_order": 0,
    }
]


def _normalize(row):
    """Coerce a DB row (RealDictCursor) into the config dict shape the rest of the
    code expects, with sane defaults for nullable columns."""
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


def get_registry(active_only=True):
    """Return the list of strategy config dicts, ordered by sort_order then id.

    Reads from trading.strategy_registry; on any error indicating the table is not
    available (or if it yields no rows) falls back to DEFAULT_REGISTRY so the app
    keeps working before the migration is applied.
    """
    conn = None
    try:
        conn = get_db_connection()
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

        registry = [_normalize(r) for r in rows]
        if not registry:
            logger.warning(
                "[REGISTRY] strategy_registry table is empty; using built-in default"
            )
            registry = list(DEFAULT_REGISTRY)
    except (psycopg2.Error, ValueError) as e:
        # psycopg2.Error: table missing (UndefinedTable, i.e. migration not applied),
        #   connection refused, auth failure, etc.
        # ValueError: get_db_connection raises this when DB_* env vars are unset.
        # In every case, fall back to the built-in default rather than 500 the whole
        # dashboard on the registry lookup.
        logger.warning(
            "[REGISTRY] Could not read strategy_registry (%s); using built-in default",
            getattr(e, "pgcode", None) or str(e),
        )
        registry = list(DEFAULT_REGISTRY)
    finally:
        if conn is not None:
            conn.close()

    if active_only:
        registry = [s for s in registry if s["is_active"]]
    return registry


def get_strategy_config(strategy_id):
    """Return the config dict for a public API id, or None if unknown/inactive."""
    for strategy in get_registry(active_only=True):
        if strategy["id"] == strategy_id:
            return strategy
    return None
