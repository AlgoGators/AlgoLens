"""Postgres portfolio readers."""

import time

from algolens.application.portfolio.ports import PortfolioDetailRows
from algolens.domain.portfolio.streams import PORTFOLIO_STREAMS, PRIMARY_STREAM
from database import get_db_connection

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
