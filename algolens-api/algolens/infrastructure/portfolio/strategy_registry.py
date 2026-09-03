"""Postgres-backed strategy registry with a built-in fallback."""

import json
import logging

import psycopg2

from algolens.application.portfolio.ports import BookNotEmpty

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
        "mock_capital": None,
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
        # Needed wherever an incubating strategy is displayed: without it the
        # trial size silently reads as absent.
        "mock_capital": float(row["mock_capital"])
        if row.get("mock_capital") is not None
        else None,
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
    """Reads and writes the strategy registry, books and membership.

    This class does NOT create schema. It did briefly -- the Books tab shipped
    before the migration existed and created its three tables lazily -- and that
    is exactly the arrangement that lets an application and its database drift
    apart without anyone noticing. trade-ngin owns this schema; the tables here
    come from migration 009_books_and_membership.sql and must be applied before
    the Books features will work.
    """

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
                               initial_equity, managers, is_active, lifecycle,
                               sort_order, mock_capital
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



    def list_declared_books(self):
        conn = self.connection_factory()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT portfolio_id, name, description, created_by, created_at
                    FROM trading.portfolios
                    ORDER BY portfolio_id
                    """
                )
                # RealDictCursor: rows are already dicts.
                return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def list_portfolio_ids_in_use(self):
        conn = self.connection_factory()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT DISTINCT portfolio_id FROM trading.strategy_registry"
                )
                return [row["portfolio_id"] for row in cursor.fetchall()]
        finally:
            conn.close()

    def create_book(self, book, user_id):
        """Declare a book. Idempotent on the id: re-declaring updates the label.

        Deliberately an upsert rather than a conflict: a book that already
        exists because a strategy sits in it is exactly the case where someone
        wants to give it a proper name.
        """
        conn = self.connection_factory()
        try:
            with conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO trading.portfolios
                            (portfolio_id, name, description, created_by)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (portfolio_id) DO UPDATE
                          SET name = EXCLUDED.name,
                              description = EXCLUDED.description
                        """,
                        (
                            book["portfolio_id"],
                            book["name"],
                            book["description"],
                            user_id,
                        ),
                    )
        finally:
            conn.close()
        return book

    def delete_book(self, portfolio_id):
        """Remove a book declaration. Refuses if anything still sits in it."""
        conn = self.connection_factory()
        try:
            with conn:
                with conn.cursor() as cursor:
                    # Both sources of "in this book". A strategy whose primary is
                    # elsewhere but which is a member here still has positions,
                    # limits and a history keyed on this book; deleting the
                    # declaration would leave those rows naming a book that no
                    # longer exists.
                    cursor.execute(
                        """
                        SELECT count(*) AS occupied FROM (
                            SELECT id AS strategy_id FROM trading.strategy_registry
                            WHERE portfolio_id = %s
                            UNION
                            SELECT strategy_id FROM trading.strategy_book_memberships
                            WHERE portfolio_id = %s
                        ) AS members
                        """,
                        (portfolio_id, portfolio_id),
                    )
                    occupied = cursor.fetchone()["occupied"]
                    if occupied:
                        raise BookNotEmpty(portfolio_id, occupied)
                    cursor.execute(
                        "DELETE FROM trading.portfolios WHERE portfolio_id = %s",
                        (portfolio_id,),
                    )
        finally:
            conn.close()
        return {"portfolio_id": portfolio_id}

    # ------------------------------------------------------------------
    # Membership: a strategy can belong to several books
    # ------------------------------------------------------------------


    def list_memberships(self):
        """Every (strategy_id, portfolio_id) pair."""
        conn = self.connection_factory()
        try:
            with conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT strategy_id, portfolio_id
                        FROM trading.strategy_book_memberships
                        ORDER BY strategy_id, portfolio_id
                        """
                    )
                    return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def books_for_strategy(self, strategy_id):
        """Books this strategy belongs to, primary included.

        Falls back to the primary column when there are no membership rows. That
        is the state between migration 009 creating the table and its seed
        running, and on any database where the seed was skipped. Reporting none
        would defeat the last-book guard: a strategy would look like it belonged
        nowhere and could be removed from the only book it is actually in.
        """
        conn = self.connection_factory()
        try:
            with conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT portfolio_id FROM trading.strategy_book_memberships
                        WHERE strategy_id = %s ORDER BY portfolio_id
                        """,
                        (strategy_id,),
                    )
                    books = [row["portfolio_id"] for row in cursor.fetchall()]
                    if books:
                        return books
                    cursor.execute(
                        "SELECT portfolio_id FROM trading.strategy_registry WHERE id = %s",
                        (strategy_id,),
                    )
                    row = cursor.fetchone()
                    return [row["portfolio_id"]] if row else []
        finally:
            conn.close()

    def add_membership(self, strategy_id, portfolio_id, audit):
        """Put a strategy in a book, and record it, in one transaction."""
        conn = self.connection_factory()
        try:
            with conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO trading.strategy_book_memberships
                            (strategy_id, portfolio_id, added_by)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (strategy_id, portfolio_id) DO NOTHING
                        """,
                        (strategy_id, portfolio_id, audit["user_id"]),
                    )
                    self._insert_membership_audit(cursor, audit)
        finally:
            conn.close()
        return {"strategy_id": strategy_id, "portfolio_id": portfolio_id}

    def remove_membership(self, strategy_id, portfolio_id, audit):
        """Take a strategy out of a book.

        If it was the primary book, the primary moves to another book the
        strategy still belongs to -- strategy_registry.portfolio_id must always
        name a book the strategy is actually in, or every scoped read for it
        returns nothing.
        """
        conn = self.connection_factory()
        try:
            with conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        DELETE FROM trading.strategy_book_memberships
                        WHERE strategy_id = %s AND portfolio_id = %s
                        """,
                        (strategy_id, portfolio_id),
                    )
                    cursor.execute(
                        """
                        SELECT portfolio_id FROM trading.strategy_book_memberships
                        WHERE strategy_id = %s ORDER BY portfolio_id LIMIT 1
                        """,
                        (strategy_id,),
                    )
                    remaining = cursor.fetchone()
                    if remaining is None:
                        # The domain refuses this, so reaching it means two
                        # concurrent removals raced. Fail the transaction rather
                        # than leave the strategy unreachable.
                        raise ValueError(
                            f"{strategy_id} would be left in no book"
                        )
                    cursor.execute(
                        """
                        UPDATE trading.strategy_registry
                        SET portfolio_id = %s
                        WHERE id = %s AND portfolio_id = %s
                        """,
                        (remaining["portfolio_id"], strategy_id, portfolio_id),
                    )
                    # rowcount is 1 only when the removed book WAS the primary.
                    # The caller is told, because a primary that moved silently
                    # is a change nobody asked for and nobody can see.
                    new_primary = remaining["portfolio_id"] if cursor.rowcount else None
                    self._insert_membership_audit(cursor, audit)
        finally:
            conn.close()
        return {
            "strategy_id": strategy_id,
            "portfolio_id": portfolio_id,
            "primary_portfolio_id": new_primary,
        }

    def _insert_membership_audit(self, cursor, audit):
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

    def reassign_portfolio(self, strategy_id, portfolio_id, audit):
        """Move the strategy and record why, in one transaction.

        Both or neither: a move with no audit row is indistinguishable from a
        database accident when someone reads it back months later.
        """
        conn = self.connection_factory()
        try:
            with conn:
                with conn.cursor() as cursor:
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
                return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()


def clear_registry_cache():
    """Compatibility no-op; registry reads intentionally remain uncached."""
    return None


def get_registry(active_only=True):
    return PostgresStrategyRegistry().list(active_only=active_only)


def get_strategy_config(strategy_id):
    return PostgresStrategyRegistry().get(strategy_id)
