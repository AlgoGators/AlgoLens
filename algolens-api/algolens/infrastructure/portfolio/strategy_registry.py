"""Postgres-backed strategy registry with a built-in fallback."""

import json
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
    }


def _has_lifecycle_column(cursor):
    cursor.execute(
        """
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'trading' AND table_name = 'strategy_registry'
          AND column_name = 'lifecycle'
        """
    )
    return cursor.fetchone() is not None


class PostgresStrategyRegistry:
    def __init__(self, connection_factory=None):
        self.connection_factory = connection_factory or get_db_connection

    def list(self, active_only=True):
        conn = None
        try:
            conn = self.connection_factory()
            with conn.cursor() as cursor:
                has_lifecycle = _has_lifecycle_column(cursor)
                if has_lifecycle:
                    cursor.execute(
                        """
                        SELECT id, strategy_type, portfolio_id, name, description,
                               initial_equity, managers, is_active, lifecycle, sort_order
                        FROM trading.strategy_registry
                        ORDER BY sort_order ASC, id ASC
                        """
                    )
                else:
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


    # ------------------------------------------------------------------
    # Portfolio assignment
    # ------------------------------------------------------------------

    def get_any(self, strategy_id):
        """Look up a strategy regardless of lifecycle.

        `get` only sees active, live strategies. Assignment has to reason about
        incubating and retired ones too -- retired specifically so it can refuse.
        """
        for strategy in self.list(active_only=False):
            if strategy["id"] == strategy_id:
                return strategy
        return None

    def _ensure_assignment_audit_table(self, cursor):
        """Create the audit table if the migration has not run.

        The canonical migration belongs in trade-ngin alongside 004/005, which
        owns this schema. This keeps the write path honest in the meantime: an
        assignment must never happen without its audit row, so the table being
        absent is not a reason to skip recording.
        """
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS trading.portfolio_assignments (
                id                BIGSERIAL PRIMARY KEY,
                strategy_id       TEXT        NOT NULL,
                user_id           TEXT,
                from_portfolio_id TEXT,
                to_portfolio_id   TEXT        NOT NULL,
                lifecycle_at_move TEXT,
                reason            TEXT,
                consequences      JSONB,
                acknowledged      BOOLEAN     NOT NULL DEFAULT FALSE,
                created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )

    def reassign_portfolio(self, strategy_id, portfolio_id, audit):
        """Move the strategy and record why, in one transaction.

        Both or neither: a move with no audit row is indistinguishable from a
        database accident when someone reads it back months later.
        """
        conn = self.connection_factory()
        try:
            with conn:
                with conn.cursor() as cursor:
                    self._ensure_assignment_audit_table(cursor)
                    cursor.execute(
                        """
                        UPDATE trading.strategy_registry
                        SET portfolio_id = %s
                        WHERE id = %s
                        """,
                        (portfolio_id, strategy_id),
                    )
                    if cursor.rowcount == 0:
                        raise ValueError(f"Strategy {strategy_id} not found")
                    cursor.execute(
                        """
                        INSERT INTO trading.portfolio_assignments
                            (strategy_id, user_id, from_portfolio_id, to_portfolio_id,
                             lifecycle_at_move, reason, consequences, acknowledged)
                        VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                        """,
                        (
                            audit["strategy_id"],
                            audit["user_id"],
                            audit["from_portfolio_id"],
                            audit["to_portfolio_id"],
                            audit["lifecycle_at_move"],
                            audit["reason"],
                            json.dumps(audit["consequences"]),
                            audit["acknowledged"],
                        ),
                    )
        finally:
            conn.close()
        return {"strategy_id": strategy_id, "portfolio_id": portfolio_id}

    def list_assignment_history(self, strategy_id, limit=100):
        conn = self.connection_factory()
        try:
            with conn.cursor() as cursor:
                self._ensure_assignment_audit_table(cursor)
                cursor.execute(
                    """
                    SELECT id, strategy_id, user_id, from_portfolio_id, to_portfolio_id,
                           lifecycle_at_move, reason, consequences, acknowledged, created_at
                    FROM trading.portfolio_assignments
                    WHERE strategy_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (strategy_id, limit),
                )
                columns = [c[0] for c in cursor.description]
                return [dict(zip(columns, row)) for row in cursor.fetchall()]
        finally:
            conn.close()


def clear_registry_cache():
    """Compatibility no-op; registry reads intentionally remain uncached."""
    return None


def get_registry(active_only=True):
    return PostgresStrategyRegistry().list(active_only=active_only)


def get_strategy_config(strategy_id):
    return PostgresStrategyRegistry().get(strategy_id)
