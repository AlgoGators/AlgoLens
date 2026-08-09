"""Postgres portfolio readers."""

import time

import psycopg2

from algolens.application.portfolio.ports import (
    IncubationError,
    IncubationPerformanceRows,
    PortfolioDetailRows,
)
from algolens.domain.portfolio.streams import PORTFOLIO_STREAMS, PRIMARY_STREAM
from algolens.infrastructure.db.postgres import get_db_connection

_PORTFOLIO_TYPE_CACHE_TTL_SECONDS = 300
_has_portfolio_type_cache = None
_has_portfolio_type_expires_at = 0


class PostgresPortfolioRepository:
    def __init__(self, connection_factory=None):
        self.connection_factory = connection_factory or get_db_connection

    def _fetch_latest_live_results(self, cursor, strategy_type, portfolio_id):
        cursor.execute(
            """
            SELECT * FROM trading.live_results
            WHERE config::jsonb->>'strategy_type' = %s
            AND portfolio_id = %s
            ORDER BY date DESC
            LIMIT 1
            """,
            (strategy_type, portfolio_id),
        )
        return cursor.fetchone()

    def _fetch_summary_row(self, cursor, strategy_type, portfolio_id):
        cursor.execute(
            """
            SELECT current_portfolio_value, total_annualized_return,
                   volatility, total_cumulative_return
            FROM trading.live_results
            WHERE config::jsonb->>'strategy_type' = %s
            AND portfolio_id = %s
            ORDER BY date DESC
            LIMIT 1
            """,
            (strategy_type, portfolio_id),
        )
        return cursor.fetchone()

    def _has_portfolio_type(self, cursor):
        global _has_portfolio_type_cache, _has_portfolio_type_expires_at

        now = time.monotonic()
        if (
            _has_portfolio_type_cache is not None
            and now < _has_portfolio_type_expires_at
        ):
            return _has_portfolio_type_cache

        cursor.execute(
            """
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'trading' AND table_name = 'equity_curve'
              AND column_name = 'portfolio_type'
            """
        )
        _has_portfolio_type_cache = cursor.fetchone() is not None
        _has_portfolio_type_expires_at = now + _PORTFOLIO_TYPE_CACHE_TTL_SECONDS
        return _has_portfolio_type_cache

    def _fetch_equity_curve(
        self,
        cursor,
        strategy_type,
        portfolio_id,
        portfolio_type=None,
        has_portfolio_type=None,
    ):
        if portfolio_type is not None and has_portfolio_type is None:
            has_portfolio_type = self._has_portfolio_type(cursor)

        if portfolio_type is not None and has_portfolio_type:
            cursor.execute(
                """
                SELECT timestamp, equity
                FROM trading.equity_curve
                WHERE strategy_id = %s
                AND portfolio_id = %s
                AND portfolio_type = %s
                ORDER BY timestamp ASC
                """,
                (strategy_type, portfolio_id, portfolio_type),
            )
        else:
            cursor.execute(
                """
                SELECT timestamp, equity
                FROM trading.equity_curve
                WHERE strategy_id = %s
                AND portfolio_id = %s
                ORDER BY timestamp ASC
                """,
                (strategy_type, portfolio_id),
            )
        return cursor.fetchall()

    def _fetch_equity_by_stream(
        self, cursor, strategy_type, portfolio_id, has_portfolio_type=None
    ):
        if has_portfolio_type is None:
            has_portfolio_type = self._has_portfolio_type(cursor)
        if not has_portfolio_type:
            return {}

        by_stream = {}
        for stream in PORTFOLIO_STREAMS:
            rows = self._fetch_equity_curve(
                cursor,
                strategy_type,
                portfolio_id,
                stream,
                has_portfolio_type=has_portfolio_type,
            )
            if rows:
                by_stream[stream] = rows
        return by_stream

    def _fetch_current_positions(self, cursor, strategy_type, portfolio_id):
        cursor.execute(
            """
            SELECT * FROM (
                SELECT DISTINCT ON (symbol)
                       symbol, quantity, average_price,
                       daily_unrealized_pnl, daily_realized_pnl
                FROM trading.positions
                WHERE strategy_id = %s
                AND portfolio_id = %s
                AND quantity != 0
                ORDER BY symbol, updated_at DESC
            ) AS latest_positions
            ORDER BY ABS(quantity * average_price) DESC
            """,
            (strategy_type, portfolio_id),
        )
        return cursor.fetchall()

    def _fetch_recent_executions(self, cursor, strategy_type, portfolio_id):
        cursor.execute(
            """
            SELECT symbol, side, quantity, price,
                   execution_time, commissions_fees
            FROM trading.executions
            WHERE strategy_id = %s
            AND portfolio_id = %s
            ORDER BY execution_time DESC
            LIMIT 100
            """,
            (strategy_type, portfolio_id),
        )
        return cursor.fetchall()

    def _fetch_yesterday_positions(self, cursor, strategy_type, portfolio_id):
        cursor.execute(
            """
            SELECT DISTINCT ON (symbol)
                   symbol, quantity, average_price,
                   daily_unrealized_pnl, daily_realized_pnl, updated_at
            FROM trading.positions
            WHERE strategy_id = %s
            AND portfolio_id = %s
            AND updated_at::date = (CURRENT_DATE - INTERVAL '1 day')::date
            ORDER BY symbol, updated_at DESC
            """,
            (strategy_type, portfolio_id),
        )
        return cursor.fetchall()

    def fetch_summary_row(self, strategy_type, portfolio_id):
        conn = self.connection_factory()
        try:
            with conn.cursor() as cursor:
                return self._fetch_summary_row(cursor, strategy_type, portfolio_id)
        finally:
            conn.close()

    def fetch_detail_rows(self, strategy_type, portfolio_id):
        conn = self.connection_factory()
        try:
            with conn.cursor() as cursor:
                latest = self._fetch_latest_live_results(cursor, strategy_type, portfolio_id)
                if not latest:
                    return PortfolioDetailRows(
                        latest=None,
                        equity_curve=[],
                        equity_by_stream={},
                        positions=[],
                        executions=[],
                        yesterday_positions=[],
                    )

                has_portfolio_type = self._has_portfolio_type(cursor)
                equity_curve = self._fetch_equity_curve(
                    cursor,
                    strategy_type,
                    portfolio_id,
                    PRIMARY_STREAM,
                    has_portfolio_type=has_portfolio_type,
                )
                equity_by_stream = self._fetch_equity_by_stream(
                    cursor,
                    strategy_type,
                    portfolio_id,
                    has_portfolio_type=has_portfolio_type,
                )
                positions = self._fetch_current_positions(
                    cursor, strategy_type, portfolio_id
                )
                executions = self._fetch_recent_executions(
                    cursor, strategy_type, portfolio_id
                )
                yesterday_positions = self._fetch_yesterday_positions(
                    cursor, strategy_type, portfolio_id
                )
        finally:
            conn.close()

        return PortfolioDetailRows(
            latest=latest,
            equity_curve=equity_curve,
            equity_by_stream=equity_by_stream,
            positions=positions,
            executions=executions,
            yesterday_positions=yesterday_positions,
        )

    def list_incubating_strategies(self):
        conn = self.connection_factory()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, strategy_type, portfolio_id, name, description,
                           mock_capital, incubation_started_at
                    FROM trading.strategy_registry
                    WHERE lifecycle = 'incubating'
                    ORDER BY incubation_started_at ASC NULLS LAST, sort_order ASC, id ASC
                    """
                )
                return cursor.fetchall()
        finally:
            conn.close()

    def _fetch_incubating_registry_row(self, cursor, strategy_id):
        cursor.execute(
            """
            SELECT strategy_type, portfolio_id, incubation_started_at
            FROM trading.strategy_registry
            WHERE id = %s AND lifecycle = 'incubating'
            """,
            (strategy_id,),
        )
        return cursor.fetchone()

    def fetch_incubation_performance(self, strategy_id):
        conn = self.connection_factory()
        try:
            with conn.cursor() as cursor:
                registry_row = self._fetch_incubating_registry_row(cursor, strategy_id)
                if (
                    registry_row is None
                    or registry_row["incubation_started_at"] is None
                ):
                    return IncubationPerformanceRows(positions=[], equity_curve=[])

                strategy_type = registry_row["strategy_type"]
                portfolio_id = registry_row["portfolio_id"]
                incubation_start = registry_row["incubation_started_at"]

                cursor.execute(
                    """
                    SELECT updated_at AS date, symbol, quantity,
                           average_price AS entry_price
                    FROM trading.positions
                    WHERE strategy_id = %s AND portfolio_id = %s AND updated_at >= %s
                    ORDER BY updated_at ASC, symbol ASC
                    """,
                    (strategy_type, portfolio_id, incubation_start),
                )
                positions = cursor.fetchall()

                cursor.execute(
                    """
                    SELECT timestamp AS date, equity
                    FROM trading.equity_curve
                    WHERE strategy_id = %s AND portfolio_id = %s AND timestamp >= %s
                    ORDER BY timestamp ASC
                    """,
                    (strategy_type, portfolio_id, incubation_start),
                )
                equity_curve = cursor.fetchall()
        finally:
            conn.close()

        return IncubationPerformanceRows(
            positions=positions,
            equity_curve=equity_curve,
        )

    def _fetch_lifecycle(self, cursor, strategy_id):
        cursor.execute(
            "SELECT lifecycle FROM trading.strategy_registry WHERE id = %s",
            (strategy_id,),
        )
        return cursor.fetchone()

    def _insert_lifecycle_audit(
        self, cursor, strategy_id, before_state, after_state, reason, user_id
    ):
        cursor.execute(
            """
            INSERT INTO trading.strategy_lifecycle_log
                (strategy_id, before_state, after_state, reason, user_id)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (strategy_id, before_state, after_state, reason, user_id),
        )

    def start_incubation(self, strategy_id, mock_capital, reason, user_id):
        if mock_capital <= 0:
            raise IncubationError("mock_capital must be positive")
        if not reason or not reason.strip():
            raise IncubationError("reason must be non-empty")

        conn = self.connection_factory()
        try:
            with conn.cursor() as cursor:
                row = self._fetch_lifecycle(cursor, strategy_id)
                if row is None:
                    raise IncubationError(f"Strategy {strategy_id} not found")

                current_state = row["lifecycle"]
                if current_state == "incubating":
                    raise IncubationError(f"Strategy {strategy_id} is already incubating")

                cursor.execute(
                    """
                    UPDATE trading.strategy_registry
                    SET lifecycle = %s, mock_capital = %s,
                        incubation_started_at = now(), updated_at = now()
                    WHERE id = %s
                    """,
                    ("incubating", mock_capital, strategy_id),
                )
                self._insert_lifecycle_audit(
                    cursor,
                    strategy_id,
                    current_state,
                    "incubating",
                    reason,
                    user_id,
                )
            conn.commit()
        except psycopg2.Error as exc:
            conn.rollback()
            raise IncubationError(f"Database error: {exc}") from exc
        finally:
            conn.close()

    def promote_to_live(self, strategy_id, reason, user_id):
        if not reason or not reason.strip():
            raise IncubationError("reason must be non-empty")

        conn = self.connection_factory()
        try:
            with conn.cursor() as cursor:
                row = self._fetch_lifecycle(cursor, strategy_id)
                if row is None:
                    raise IncubationError(f"Strategy {strategy_id} not found")

                current_state = row["lifecycle"]
                if current_state != "incubating":
                    raise IncubationError(
                        f"Strategy {strategy_id} is not currently incubating"
                    )

                cursor.execute(
                    """
                    UPDATE trading.strategy_registry
                    SET lifecycle = %s, mock_capital = NULL,
                        incubation_started_at = NULL, updated_at = now()
                    WHERE id = %s
                    """,
                    ("live", strategy_id),
                )
                self._insert_lifecycle_audit(
                    cursor,
                    strategy_id,
                    "incubating",
                    "live",
                    reason,
                    user_id,
                )
            conn.commit()
        except psycopg2.Error as exc:
            conn.rollback()
            raise IncubationError(f"Database error: {exc}") from exc
        finally:
            conn.close()

    def retire_strategy(self, strategy_id, reason, user_id):
        if not reason or not reason.strip():
            raise IncubationError("reason must be non-empty")

        conn = self.connection_factory()
        try:
            with conn.cursor() as cursor:
                row = self._fetch_lifecycle(cursor, strategy_id)
                if row is None:
                    raise IncubationError(f"Strategy {strategy_id} not found")

                current_state = row["lifecycle"]
                cursor.execute(
                    """
                    UPDATE trading.strategy_registry
                    SET lifecycle = %s, mock_capital = NULL,
                        incubation_started_at = NULL, updated_at = now()
                    WHERE id = %s
                    """,
                    ("retired", strategy_id),
                )
                self._insert_lifecycle_audit(
                    cursor,
                    strategy_id,
                    current_state,
                    "retired",
                    reason,
                    user_id,
                )
            conn.commit()
        except psycopg2.Error as exc:
            conn.rollback()
            raise IncubationError(f"Database error: {exc}") from exc
        finally:
            conn.close()
