"""Postgres portfolio readers."""

import time

import psycopg2

from algolens.application.portfolio.ports import (
    IncubationError,
    IncubationPerformanceRows,
    PortfolioDetailRows,
)
from algolens.domain.portfolio.streams import (
    DEFAULT_BOOK,
    FALLBACK_BOOK,
    PORTFOLIO_STREAMS,
)
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

    def _book_has_positions(self, cursor, strategy_type, portfolio_id, book):
        cursor.execute(
            """
            SELECT 1 FROM trading.positions
            WHERE strategy_id = %s
            AND portfolio_id = %s
            AND portfolio_type = %s
            LIMIT 1
            """,
            (strategy_type, portfolio_id, book),
        )
        return cursor.fetchone() is not None

    def _resolve_served_book(
        self, cursor, strategy_type, portfolio_id, book, allow_fallback, has_portfolio_type
    ):
        """Return (book to serve, fell_back).

        Only a request that did not name a book may fall back, only to the
        system book, and only when the requested book has no position rows at
        all for this portfolio.
        """
        if not allow_fallback or book == FALLBACK_BOOK:
            return book, False
        if not has_portfolio_type:
            # Unmigrated schema: every row is the system book.
            return FALLBACK_BOOK, True
        if self._book_has_positions(cursor, strategy_type, portfolio_id, book):
            return book, False
        return FALLBACK_BOOK, True

    def _fetch_current_positions(
        self, cursor, strategy_type, portfolio_id, book, has_portfolio_type=None
    ):
        """Open positions of one book on that book's latest date.

        The zero-quantity filter runs in the OUTER query, after the latest row
        per symbol is chosen, so a flatten (a quantity-0 row on the latest date)
        hides the symbol instead of resurrecting an older non-zero row.
        """
        if has_portfolio_type is None:
            has_portfolio_type = self._has_portfolio_type(cursor)

        if has_portfolio_type:
            cursor.execute(
                """
                SELECT * FROM (
                    SELECT DISTINCT ON (symbol)
                           symbol, quantity, average_price,
                           daily_unrealized_pnl, daily_realized_pnl
                    FROM trading.positions
                    WHERE strategy_id = %s
                    AND portfolio_id = %s
                    AND portfolio_type = %s
                    AND date = (
                        SELECT max(date) FROM trading.positions
                        WHERE strategy_id = %s
                        AND portfolio_id = %s
                        AND portfolio_type = %s
                    )
                    ORDER BY symbol, updated_at DESC
                ) AS latest_positions
                WHERE quantity <> 0
                ORDER BY ABS(quantity * average_price) DESC
                """,
                (strategy_type, portfolio_id, book) * 2,
            )
            return cursor.fetchall()

        if book != FALLBACK_BOOK:
            # Unmigrated schema holds only system rows.
            return []

        cursor.execute(
            """
            SELECT * FROM (
                SELECT DISTINCT ON (symbol)
                       symbol, quantity, average_price,
                       daily_unrealized_pnl, daily_realized_pnl
                FROM trading.positions
                WHERE strategy_id = %s
                AND portfolio_id = %s
                AND date = (
                    SELECT max(date) FROM trading.positions
                    WHERE strategy_id = %s
                    AND portfolio_id = %s
                )
                ORDER BY symbol, updated_at DESC
            ) AS latest_positions
            WHERE quantity <> 0
            ORDER BY ABS(quantity * average_price) DESC
            """,
            (strategy_type, portfolio_id) * 2,
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

    def _fetch_yesterday_positions(
        self, cursor, strategy_type, portfolio_id, book=FALLBACK_BOOK, has_portfolio_type=None
    ):
        if has_portfolio_type is None:
            has_portfolio_type = self._has_portfolio_type(cursor)

        if has_portfolio_type:
            cursor.execute(
                """
                SELECT DISTINCT ON (symbol)
                       symbol, quantity, average_price,
                       daily_unrealized_pnl, daily_realized_pnl, updated_at
                FROM trading.positions
                WHERE strategy_id = %s
                AND portfolio_id = %s
                AND portfolio_type = %s
                AND updated_at::date = (CURRENT_DATE - INTERVAL '1 day')::date
                ORDER BY symbol, updated_at DESC
                """,
                (strategy_type, portfolio_id, book),
            )
            return cursor.fetchall()

        if book != FALLBACK_BOOK:
            return []

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

    def fetch_detail_rows(
        self, strategy_type, portfolio_id, book=DEFAULT_BOOK, allow_fallback=True
    ):
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
                        book=book,
                        fell_back=False,
                    )

                has_portfolio_type = self._has_portfolio_type(cursor)
                served_book, fell_back = self._resolve_served_book(
                    cursor,
                    strategy_type,
                    portfolio_id,
                    book,
                    allow_fallback,
                    has_portfolio_type,
                )
                if has_portfolio_type or served_book == FALLBACK_BOOK:
                    # The headline curve follows the served book so the page
                    # shows one book throughout.
                    equity_curve = self._fetch_equity_curve(
                        cursor,
                        strategy_type,
                        portfolio_id,
                        served_book,
                        has_portfolio_type=has_portfolio_type,
                    )
                else:
                    # Unmigrated schema has no rows for a non-system book.
                    equity_curve = []
                equity_by_stream = self._fetch_equity_by_stream(
                    cursor,
                    strategy_type,
                    portfolio_id,
                    has_portfolio_type=has_portfolio_type,
                )
                positions = self._fetch_current_positions(
                    cursor,
                    strategy_type,
                    portfolio_id,
                    served_book,
                    has_portfolio_type=has_portfolio_type,
                )
                executions = self._fetch_recent_executions(
                    cursor, strategy_type, portfolio_id
                )
                yesterday_positions = self._fetch_yesterday_positions(
                    cursor,
                    strategy_type,
                    portfolio_id,
                    served_book,
                    has_portfolio_type=has_portfolio_type,
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
            book=served_book,
            fell_back=fell_back,
        )

    # --- reads keyed by portfolio id (AlgoLens#102) ------------------------
    #
    # One portfolio is one book: these reads find a book by its portfolio id
    # and never match on the strategy id. A book with several sleeves is
    # netted per symbol.

    def _has_column(self, cursor, table, column):
        cursor.execute(
            """
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'trading' AND table_name = %s AND column_name = %s
            """,
            (table, column),
        )
        return cursor.fetchone() is not None

    def _portfolio_book_has_positions(self, cursor, portfolio_id, book):
        cursor.execute(
            """
            SELECT 1 FROM trading.positions
            WHERE portfolio_id = %s AND portfolio_type = %s
            LIMIT 1
            """,
            (portfolio_id, book),
        )
        return cursor.fetchone() is not None

    def _portfolio_latest_results(self, cursor, portfolio_id, book, results_have_book):
        if results_have_book:
            # The served book's own row; a book whose results are not written
            # (qt_proposal never has any) shows the system row's numbers.
            cursor.execute(
                """
                SELECT * FROM trading.live_results
                WHERE portfolio_id = %s AND portfolio_type IN (%s, 'system')
                ORDER BY date DESC, (portfolio_type = %s) DESC
                LIMIT 1
                """,
                (portfolio_id, book, book),
            )
        else:
            cursor.execute(
                """
                SELECT * FROM trading.live_results
                WHERE portfolio_id = %s
                ORDER BY date DESC
                LIMIT 1
                """,
                (portfolio_id,),
            )
        return cursor.fetchone()

    def _portfolio_equity_curve(self, cursor, portfolio_id, book, has_portfolio_type):
        if has_portfolio_type:
            cursor.execute(
                """
                SELECT timestamp, equity FROM trading.equity_curve
                WHERE portfolio_id = %s AND portfolio_type = %s
                ORDER BY timestamp ASC
                """,
                (portfolio_id, book),
            )
        else:
            cursor.execute(
                """
                SELECT timestamp, equity FROM trading.equity_curve
                WHERE portfolio_id = %s
                ORDER BY timestamp ASC
                """,
                (portfolio_id,),
            )
        return cursor.fetchall()

    def _portfolio_equity_by_stream(self, cursor, portfolio_id, has_portfolio_type):
        if not has_portfolio_type:
            return {}
        by_stream = {}
        for stream in PORTFOLIO_STREAMS:
            rows = self._portfolio_equity_curve(cursor, portfolio_id, stream, True)
            if rows:
                by_stream[stream] = rows
        return by_stream

    def _portfolio_positions(self, cursor, portfolio_id, book, has_portfolio_type):
        """The book's positions on its latest date, netted across sleeves.

        A symbol whose net quantity is zero (a flatten row) is left out.
        """
        book_filter = "AND portfolio_type = %s" if has_portfolio_type else ""
        params = (portfolio_id, book) if has_portfolio_type else (portfolio_id,)
        cursor.execute(
            f"""
            SELECT symbol,
                   SUM(quantity) AS quantity,
                   CASE WHEN SUM(quantity) <> 0
                        THEN SUM(quantity * average_price) / SUM(quantity)
                        ELSE MAX(average_price) END AS average_price,
                   SUM(daily_unrealized_pnl) AS daily_unrealized_pnl,
                   SUM(daily_realized_pnl) AS daily_realized_pnl
            FROM trading.positions
            WHERE portfolio_id = %s {book_filter}
            AND date = (
                SELECT max(date) FROM trading.positions
                WHERE portfolio_id = %s {book_filter}
            )
            GROUP BY symbol
            HAVING SUM(quantity) <> 0
            ORDER BY ABS(SUM(quantity * average_price)) DESC, symbol
            """,
            params * 2,
        )
        return cursor.fetchall()

    def _portfolio_yesterday_positions(self, cursor, portfolio_id, book, has_portfolio_type):
        book_filter = "AND portfolio_type = %s" if has_portfolio_type else ""
        params = (portfolio_id, book) if has_portfolio_type else (portfolio_id,)
        cursor.execute(
            f"""
            SELECT DISTINCT ON (symbol)
                   symbol, quantity, average_price,
                   daily_unrealized_pnl, daily_realized_pnl, updated_at
            FROM trading.positions
            WHERE portfolio_id = %s {book_filter}
            AND updated_at::date = (CURRENT_DATE - INTERVAL '1 day')::date
            ORDER BY symbol, updated_at DESC
            """,
            params,
        )
        return cursor.fetchall()

    def _portfolio_executions(self, cursor, portfolio_id, book, executions_have_book):
        book_filter = "AND portfolio_type = %s" if executions_have_book else ""
        params = (portfolio_id, book) if executions_have_book else (portfolio_id,)
        cursor.execute(
            f"""
            SELECT symbol, side, quantity, price, execution_time, commissions_fees
            FROM trading.executions
            WHERE portfolio_id = %s {book_filter}
            ORDER BY execution_time DESC
            LIMIT 100
            """,
            params,
        )
        return cursor.fetchall()

    def fetch_portfolio_rows(self, portfolio_id, book=DEFAULT_BOOK, allow_fallback=True):
        """Detail rows for one portfolio's book, found by portfolio id alone."""
        conn = self.connection_factory()
        try:
            with conn.cursor() as cursor:
                has_portfolio_type = self._has_portfolio_type(cursor)
                if not allow_fallback or book == FALLBACK_BOOK:
                    served_book, fell_back = book, False
                elif not has_portfolio_type:
                    served_book, fell_back = FALLBACK_BOOK, True
                elif self._portfolio_book_has_positions(cursor, portfolio_id, book):
                    served_book, fell_back = book, False
                else:
                    served_book, fell_back = FALLBACK_BOOK, True

                results_have_book = self._has_column(cursor, "live_results", "portfolio_type")
                latest = self._portfolio_latest_results(
                    cursor, portfolio_id, served_book, results_have_book
                )
                if not latest:
                    return PortfolioDetailRows(
                        latest=None,
                        equity_curve=[],
                        equity_by_stream={},
                        positions=[],
                        executions=[],
                        yesterday_positions=[],
                        book=served_book,
                        fell_back=fell_back,
                    )

                if has_portfolio_type or served_book == FALLBACK_BOOK:
                    equity_curve = self._portfolio_equity_curve(
                        cursor, portfolio_id, served_book, has_portfolio_type
                    )
                    positions = self._portfolio_positions(
                        cursor, portfolio_id, served_book, has_portfolio_type
                    )
                    yesterday = self._portfolio_yesterday_positions(
                        cursor, portfolio_id, served_book, has_portfolio_type
                    )
                else:
                    # Unmigrated schema: no rows for a non-system book.
                    equity_curve, positions, yesterday = [], [], []
                equity_by_stream = self._portfolio_equity_by_stream(
                    cursor, portfolio_id, has_portfolio_type
                )
                executions_have_book = self._has_column(cursor, "executions", "portfolio_type")
                if executions_have_book or served_book == FALLBACK_BOOK:
                    executions = self._portfolio_executions(
                        cursor, portfolio_id, served_book, executions_have_book
                    )
                else:
                    executions = []
        finally:
            conn.close()

        return PortfolioDetailRows(
            latest=latest,
            equity_curve=equity_curve,
            equity_by_stream=equity_by_stream,
            positions=positions,
            executions=executions,
            yesterday_positions=yesterday,
            book=served_book,
            fell_back=fell_back,
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
