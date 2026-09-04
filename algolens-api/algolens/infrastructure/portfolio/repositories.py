import logging
"""Postgres portfolio readers."""

import json
import time
from datetime import date as _date

import psycopg2

from algolens.application.portfolio.ports import (
    IncubationError,
    IncubationPerformanceRows,
    IncubationStorageError,
    PortfolioDetailRows,
    StrategyNameUnresolved,
    StrategyNotInRegistry,
)
from algolens.domain.portfolio.position_edit import (
    QT_STREAM,
    build_after_state,
)
from algolens.domain.portfolio.streams import PORTFOLIO_STREAMS, PRIMARY_STREAM
from algolens.infrastructure.db.postgres import get_db_connection

logger = logging.getLogger(__name__)

_PORTFOLIO_TYPE_CACHE_TTL_SECONDS = 300
_has_portfolio_type_cache = None
_has_portfolio_type_expires_at = 0



def _plain_number(value):
    """Decimal from a NUMERIC column -> float, so domain arithmetic and JSON both work."""
    return float(value) if value is not None else None


def _plain_position(row):
    """Position row with NUMERIC fields coerced, and nothing else changed."""
    out = dict(row)
    for key in ("quantity", "average_price", "daily_unrealized_pnl", "daily_realized_pnl"):
        if key in out:
            out[key] = _plain_number(out[key])
    return out

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

    # trading.positions holds one row per open position PER DAY. The engine
    # deletes the day's rows and rewrites them each run
    # (postgres_database.cpp, PostgresDatabase::store_positions), and a
    # position that closed simply gets no row for that day -- the engine never
    # writes a zero-quantity row to mark the close.
    #
    # Both queries below therefore work from a snapshot DATE. Picking the
    # latest row per symbol regardless of date, which is what the current
    # positions query used to do, returned every symbol the strategy had ever
    # held, each frozen at the last day it was open, under a heading that says
    # "Today's Positions". The `quantity != 0` guard did nothing about it: a
    # closed position has no row to be zero. Every figure downstream inherited
    # the error -- total notional, the position weights, and the current book
    # the risk gate checks a proposed edit against.
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
                AND date = (
                    SELECT max(date) FROM trading.positions
                    WHERE strategy_id = %s AND portfolio_id = %s
                )
                ORDER BY symbol, updated_at DESC
            ) AS latest_positions
            ORDER BY ABS(quantity * average_price) DESC
            """,
            (strategy_type, portfolio_id, strategy_type, portfolio_id),
        )
        return cursor.fetchall()

    def held_symbols(self, portfolio_ids):
        """Every symbol the named books hold in their most recent snapshot.

        Scoped to that snapshot for the same reason the position view is: a
        symbol closed months ago is not something the fund holds, and
        correlating it would describe a book nobody has.

        Scoped to the named books because every read of a portfolio-keyed table
        is (tests/test_portfolio_queries.py). The caller passes the books the
        fund actually reports on, so a stray row for some other portfolio
        cannot put an instrument on screen that no reported book holds.
        """
        books = [b for b in dict.fromkeys(portfolio_ids) if b]
        if not books:
            return []
        conn = self.connection_factory()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT DISTINCT symbol
                    FROM trading.positions
                    WHERE portfolio_id = ANY(%s)
                      AND quantity != 0
                      AND date = (
                          SELECT max(date) FROM trading.positions
                          WHERE portfolio_id = ANY(%s)
                      )
                    ORDER BY symbol
                    """,
                    (books, books),
                )
                rows = cursor.fetchall()
        finally:
            conn.close()
        return [row["symbol"] if isinstance(row, dict) else row[0] for row in rows]

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
        """The snapshot before the latest one.

        This asked for CURRENT_DATE - 1 literally, so the comparison had
        nothing to compare against every Monday and after every holiday --
        markets are shut, the engine writes no rows, and the panel went blank
        with no explanation. "The previous snapshot" is the question the panel
        is actually asking.
        """
        cursor.execute(
            """
            SELECT DISTINCT ON (symbol)
                   symbol, quantity, average_price,
                   daily_unrealized_pnl, daily_realized_pnl, updated_at
            FROM trading.positions
            WHERE strategy_id = %s
            AND portfolio_id = %s
            AND date = (
                SELECT max(date) FROM trading.positions
                WHERE strategy_id = %s AND portfolio_id = %s
                AND date < (
                    SELECT max(date) FROM trading.positions
                    WHERE strategy_id = %s AND portfolio_id = %s
                )
            )
            ORDER BY symbol, updated_at DESC
            """,
            (strategy_type, portfolio_id, strategy_type, portfolio_id,
             strategy_type, portfolio_id),
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
                    raise StrategyNotInRegistry(f"Strategy {strategy_id} not found")

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
            logger.error("Incubation write failed: %s", exc, exc_info=True)
            raise IncubationStorageError("Database error") from exc
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
                    raise StrategyNotInRegistry(f"Strategy {strategy_id} not found")

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
            logger.error("Incubation write failed: %s", exc, exc_info=True)
            raise IncubationStorageError("Database error") from exc
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
                    raise StrategyNotInRegistry(f"Strategy {strategy_id} not found")

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
            logger.error("Incubation write failed: %s", exc, exc_info=True)
            raise IncubationStorageError("Database error") from exc
        finally:
            conn.close()


    # -- qt stream writes (F2) ------------------------------------------------
    #
    # Restores AlgoLens PR #31, ported onto the layered package. The engine
    # seeds trading.positions with portfolio_type='qt' as a copy of 'system';
    # these are the only writes that make the two diverge, and every one of
    # them lands in trading.position_overrides in the same transaction.

    def fetch_risk_envelope(self, strategy_type, portfolio_id):
        """The most recent envelope trade-ngin published for this book.

        Returns None when the table does not exist yet (trade-ngin has not
        shipped the publisher) or holds no row -- the gate reports that as
        "not evaluated" rather than as a pass.
        """
        conn = self.connection_factory()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'trading' AND table_name = 'risk_limits'
                    """
                )
                if cursor.fetchone() is None:
                    return None

                cursor.execute(
                    """
                    SELECT limits
                    FROM trading.risk_limits
                    WHERE strategy_id = %s AND portfolio_id = %s
                    ORDER BY published_at DESC
                    LIMIT 1
                    """,
                    (strategy_type, portfolio_id),
                )
                row = cursor.fetchone()
                return row["limits"] if row else None
        finally:
            conn.close()

    def fetch_qt_book(self, strategy_type, portfolio_id):
        """Today's qt positions, one row per symbol."""
        conn = self.connection_factory()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT DISTINCT ON (symbol)
                           symbol, quantity, average_price
                    FROM trading.positions
                    WHERE strategy_id = %s
                      AND portfolio_id = %s
                      AND portfolio_type = %s
                      AND quantity != 0
                    ORDER BY symbol, updated_at DESC
                    """,
                    (strategy_type, portfolio_id, QT_STREAM),
                )
                return [_plain_position(r) for r in cursor.fetchall()]
        finally:
            conn.close()

    def _fetch_existing_position(self, cursor, strategy_type, portfolio_id, symbol):
        # Lock the row for the rest of the transaction so we capture the true
        # before_state in the audit trail. If two QT members edit the same symbol
        # concurrently, or the engine's daily run writes between our read and
        # write, the lock ensures we read the current row and record what it was
        # at the moment we decided to change it. When the row does not exist there
        # is nothing to lock; the ON CONFLICT clause still makes the insert safe.
        cursor.execute(
            """
            SELECT symbol, quantity, average_price,
                   daily_unrealized_pnl, daily_realized_pnl
            FROM trading.positions
            WHERE strategy_id = %s
              AND portfolio_id = %s
              AND portfolio_type = %s
              AND symbol = %s
            ORDER BY updated_at DESC
            LIMIT 1
            FOR UPDATE
            """,
            (strategy_type, portfolio_id, QT_STREAM, symbol),
        )
        row = cursor.fetchone()
        return _plain_position(row) if row else None

    def _resolve_strategy_name(self, cursor, strategy_type, portfolio_id):
        """The engine's own strategy_name for this book.

        strategy_name is part of the positions primary key and the engine
        chooses its value. Guessing it (from the registry's display name, say)
        would write QT's edit to a different key than the engine's row -- the
        write would appear to succeed and the engine would never see it. So take
        the value from rows the engine already wrote.
        """
        cursor.execute(
            """
            SELECT strategy_name
            FROM trading.positions
            WHERE portfolio_id = %s AND strategy_id = %s
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (portfolio_id, strategy_type),
        )
        row = cursor.fetchone()
        if row is None:
            raise StrategyNameUnresolved(
                f"No existing positions for strategy {strategy_type} in "
                f"portfolio {portfolio_id}, so the engine's strategy_name cannot "
                f"be determined. Refusing to guess: a wrong strategy_name writes "
                f"a row the engine will never reconcile."
            )
        return row["strategy_name"]

    def write_qt_position(
        self,
        strategy_type,
        portfolio_id,
        normalized,
        user_id,
        verdict,
        overrode_risk,
    ):
        """Upsert one qt position and its audit row, atomically.

        Both statements share a transaction: if the audit insert fails, the
        position change is rolled back with it. A position that changed without
        an audit row is the precise failure F2 exists to prevent, so it must not
        be reachable even through a partial failure.
        """
        conn = self.connection_factory()
        try:
            with conn:  # commits on success, rolls back on exception
                with conn.cursor() as cursor:
                    before = self._fetch_existing_position(
                        cursor, strategy_type, portfolio_id, normalized["symbol"]
                    )
                    after = build_after_state(before, normalized)
                    strategy_name = self._resolve_strategy_name(
                        cursor, strategy_type, portfolio_id
                    )

                    cursor.execute(
                        """
                        INSERT INTO trading.positions
                            (portfolio_id, strategy_id, strategy_name, date, symbol,
                             portfolio_type, quantity, average_price,
                             daily_unrealized_pnl, daily_realized_pnl,
                             last_update, updated_at)
                        -- The three constants are not padding. In the schema
                        -- trade-ngin actually ships, daily_unrealized_pnl,
                        -- daily_realized_pnl and last_update are NOT NULL with
                        -- no default, so omitting them made every manual write
                        -- fail outright. A position created by hand this second
                        -- has accrued no PnL, and it was last touched now.
                        -- On conflict none of the three is overwritten: they
                        -- belong to the engine, and an edit to quantity is not
                        -- a claim about PnL.
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0, 0, now(), now())
                        ON CONFLICT (portfolio_id, strategy_id, strategy_name, date,
                                     symbol, portfolio_type)
                        DO UPDATE SET quantity      = EXCLUDED.quantity,
                                      average_price = EXCLUDED.average_price,
                                      updated_at    = now()
                        RETURNING symbol, quantity, average_price
                        """,
                        (
                            portfolio_id,
                            strategy_type,
                            strategy_name,
                            _date.today(),
                            normalized["symbol"],
                            QT_STREAM,
                            after["quantity"],
                            # after, not normalized: a blank price on an edit means
                            # "keep it", and build_after_state already carried the
                            # existing price forward. Writing the raw proposal here
                            # wiped average_price on every quantity-only edit.
                            after.get("average_price"),
                        ),
                    )
                    # Coerced, not raw: NUMERIC columns come back as Decimal and
                    # jsonify renders those as JSON strings. The 201 body was
                    # returning "quantity": "20", which any client parsing it as
                    # a number would get wrong.
                    position = _plain_position(cursor.fetchone())

                    cursor.execute(
                        """
                        INSERT INTO trading.position_overrides
                            (user_id, source_app, strategy_id, symbol,
                             before_state, after_state, reason,
                             risk_check_result, overrode_risk)
                        VALUES (%s, 'algolens', %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                        """,
                        (
                            user_id,
                            strategy_type,
                            normalized["symbol"],
                            json.dumps(before or {}, default=str),
                            json.dumps(after, default=str),
                            normalized["reason"],
                            json.dumps(verdict),
                            overrode_risk,
                        ),
                    )
                    override_id = cursor.fetchone()["id"]

            return {"position": position, "override_id": override_id}
        finally:
            conn.close()

    def fetch_overrides(self, strategy_type, limit=100):
        """Recent audit entries. Read-only -- this table cannot be modified."""
        conn = self.connection_factory()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, user_id, source_app, strategy_id, symbol,
                           before_state, after_state, reason,
                           risk_check_result, overrode_risk, created_at
                    FROM trading.position_overrides
                    WHERE strategy_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (strategy_type, limit),
                )
                return [dict(r) for r in cursor.fetchall()]
        finally:
            conn.close()
