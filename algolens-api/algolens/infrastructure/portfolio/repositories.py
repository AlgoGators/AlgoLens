import logging
"""Postgres portfolio readers."""

import json
import math
import time
from datetime import datetime, time as day_time, timedelta, timezone

import psycopg2

from algolens.application.portfolio.ports import (
    DeskFinalizationPendingError,
    IncubationError,
    IncubationPerformanceRows,
    IncubationStorageError,
    OpenPositionsError,
    PortfolioDetailRows,
    PositionsUnavailableError,
    StrategyNameUnresolved,
    StrategyNotInRegistry,
)
from algolens.domain.portfolio.position_edit import (
    PositionValidationError,
    QT_STREAM,
    build_after_state,
)
from algolens.domain.portfolio.position_decimal import canonical_position_decimal8
from algolens.domain.portfolio.streams import (
    DEFAULT_POSITION_STREAM,
    PORTFOLIO_STREAMS,
    PRIMARY_STREAM,
    current_utc_date,
    validate_position_stream,
)
from algolens.infrastructure.db.postgres import get_db_connection
from algolens.infrastructure.portfolio.book_lock import acquire_qt_book_locks
from algolens.infrastructure.portfolio.qt_publication_proof import require_legacy_qt_disabled

logger = logging.getLogger(__name__)

_PORTFOLIO_TYPE_CACHE_TTL_SECONDS = 300
#: {table name: bool}, refreshed wholesale when the TTL lapses. Keyed by table
#: because the flag gates whether a query names the column, and the two tables
#: migration 001 touches can be out of step during a partial migration.
_has_portfolio_type_cache = {}
_has_portfolio_type_expires_at = 0



def _plain_number(value):
    """Decimal from a NUMERIC column -> float, so domain arithmetic and JSON both work."""
    return float(value) if value is not None else None


def _plain_position(row):
    """Legacy float projections plus exact companions from original NUMERICs."""
    out = dict(row)
    for key in ("quantity", "average_price"):
        if key in out:
            out[key + "_exact"] = (
                canonical_position_decimal8(out[key]) if out[key] is not None else None
            )
    for key in ("quantity", "average_price", "daily_unrealized_pnl", "daily_realized_pnl"):
        if key in out:
            out[key] = _plain_number(out[key])
    return out

class PostgresPortfolioRepository:
    def __init__(self, connection_factory=None, launch_date=None):
        self.connection_factory = connection_factory or get_db_connection
        self.launch_date = launch_date

    def _date_launch_scope(self):
        if self.launch_date is None:
            return "", ()
        return "AND date >= %s", (self.launch_date,)

    def _timestamp_launch_scope(self):
        if self.launch_date is None:
            return "", ()
        launch_instant = datetime.combine(
            self.launch_date, day_time.min, tzinfo=timezone.utc
        )
        return "AND timestamp >= %s", (launch_instant,)

    def _fetch_latest_live_results(self, cursor, strategy_type, portfolio_id):
        if not self._has_portfolio_type(cursor, "live_results"):
            # A legacy table is un-attributable; a missing table is a schema
            # failure and must still reach the caller as such.
            cursor.execute("SELECT 1 FROM trading.live_results LIMIT 0")
            return None
        launch_predicate, launch_params = self._date_launch_scope()
        cursor.execute(
            f"""
            SELECT * FROM trading.live_results
            WHERE config::jsonb->>'strategy_type' = %s
            AND portfolio_id = %s
            AND portfolio_type = %s
            {launch_predicate}
            ORDER BY date DESC
            LIMIT 1
            """,
            (strategy_type, portfolio_id, PRIMARY_STREAM) + launch_params,
        )
        return cursor.fetchone()

    def _fetch_summary_row(self, cursor, strategy_type, portfolio_id):
        if not self._has_portfolio_type(cursor, "live_results"):
            cursor.execute("SELECT 1 FROM trading.live_results LIMIT 0")
            return None
        launch_predicate, launch_params = self._date_launch_scope()
        cursor.execute(
            f"""
            SELECT date, current_portfolio_value, total_annualized_return,
                   volatility, total_cumulative_return
            FROM trading.live_results
            WHERE config::jsonb->>'strategy_type' = %s
            AND portfolio_id = %s
            AND portfolio_type = %s
            {launch_predicate}
            ORDER BY date DESC
            LIMIT 1
            """,
            (strategy_type, portfolio_id, PRIMARY_STREAM) + launch_params,
        )
        return cursor.fetchone()

    def _has_portfolio_type(self, cursor, table="equity_curve"):
        """Does `table` carry the stream column migration 001 adds?

        Asked per table, not once for the schema. Migration 001 adds
        portfolio_type to equity_curve and positions together, so in a healthy
        database the answer is the same for both -- but this flag decides
        whether a query names a column, and a query against positions has no
        business trusting what equity_curve looks like. A partial migration or
        a restore that brought back one table and not the other would otherwise
        make the positions read ask for a column that is not there.
        """
        global _has_portfolio_type_cache, _has_portfolio_type_expires_at

        now = time.monotonic()
        if _has_portfolio_type_expires_at < now:
            _has_portfolio_type_cache = {}
            _has_portfolio_type_expires_at = now + _PORTFOLIO_TYPE_CACHE_TTL_SECONDS
        if table in _has_portfolio_type_cache:
            return _has_portfolio_type_cache[table]

        cursor.execute(
            """
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'trading' AND table_name = %s
              AND column_name = 'portfolio_type'
            """,
            (table,),
        )
        present = cursor.fetchone() is not None
        _has_portfolio_type_cache[table] = present
        return present

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

        launch_predicate, launch_params = self._timestamp_launch_scope()
        if portfolio_type is not None and has_portfolio_type:
            cursor.execute(
                f"""
                SELECT timestamp, equity
                FROM trading.equity_curve
                WHERE strategy_id = %s
                AND portfolio_id = %s
                AND portfolio_type = %s
                {launch_predicate}
                ORDER BY timestamp ASC
                """,
                (strategy_type, portfolio_id, portfolio_type) + launch_params,
            )
        else:
            cursor.execute(
                f"""
                SELECT timestamp, equity
                FROM trading.equity_curve
                WHERE strategy_id = %s
                AND portfolio_id = %s
                {launch_predicate}
                ORDER BY timestamp ASC
                """,
                (strategy_type, portfolio_id) + launch_params,
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
    # ---------------------------------------------------------------------
    # THE STREAM PREDICATE
    #
    # trading.positions carries one row per (symbol, date, STREAM). Today every
    # row is portfolio_type = 'system', so a query with no stream predicate
    # happens to be right. The moment trade-ngin migration 002 backfills the qt
    # stream, every symbol and date has two rows, and DISTINCT ON (symbol)
    # ORDER BY updated_at DESC returns whichever stream was written last --
    # blending the model's book and the desk's book in one table with nothing
    # on screen saying which is which.
    #
    # Worse for the write path: after a desk edit the qt row has the newest
    # updated_at, so the edit appears to have worked, for the wrong reason. It
    # would look identical if the edit had been written to the wrong stream.
    #
    # The equity-curve read has taken a stream since the streams landed. These
    # three now do too. See AlgoLens issue #83; this predicate is what unblocks
    # applying migration 002 to production.
    #
    # The default is PRIMARY_STREAM -- the model/system book shown on login --
    # because every other headline figure on the landing page uses that same
    # source, including the equity curve directly above the table.
    #
    # has_portfolio_type exists because the column does not, on a database that
    # has not had migration 001. There the predicate is dropped, which is
    # correct: a database with no streams has nothing to disambiguate.
    # ---------------------------------------------------------------------
    def _fetch_current_positions(
        self,
        cursor,
        strategy_type,
        portfolio_id,
        portfolio_type=PRIMARY_STREAM,
        has_portfolio_type=None,
    ):
        if portfolio_type is not None and has_portfolio_type is None:
            has_portfolio_type = self._has_portfolio_type(cursor, "positions")
        scoped = portfolio_type is not None and has_portfolio_type

        # The snapshot date has to be found within the same stream. Taking the
        # max over every stream would ask for the qt stream's rows on a date
        # only the system stream reached, and return nothing at all.
        stream_predicate = "AND portfolio_type = %s" if scoped else ""
        launch_predicate, launch_params = self._date_launch_scope()
        scope = (
            (strategy_type, portfolio_id, portfolio_type)
            if scoped
            else (strategy_type, portfolio_id)
        ) + launch_params
        params = scope + scope
        cursor.execute(
            f"""
            SELECT * FROM (
                SELECT DISTINCT ON (strategy_name, symbol)
                       strategy_name, date, symbol, quantity, average_price,
                       daily_unrealized_pnl, daily_realized_pnl
                FROM trading.positions
                WHERE strategy_id = %s
                AND portfolio_id = %s
                {stream_predicate}
                {launch_predicate}
                AND quantity != 0
                AND date = (
                    SELECT max(date) FROM trading.positions
                    WHERE strategy_id = %s AND portfolio_id = %s
                    {stream_predicate}
                    {launch_predicate}
                )
                ORDER BY strategy_name, symbol, updated_at DESC
            ) AS latest_positions
            ORDER BY ABS(quantity * average_price) DESC
            """,
            params,
        )
        return cursor.fetchall()

    def held_symbols(self, portfolio_ids, portfolio_type=PRIMARY_STREAM):
        """Every symbol the named books hold in each book's most recent snapshot.

        Scoped to that snapshot for the same reason the position view is: a
        symbol closed months ago is not something the fund holds, and
        correlating it would describe a book nobody has.

        Scoped to the named books because every read of a portfolio-keyed table
        is (tests/test_portfolio_queries.py). The caller passes the books the
        fund actually reports on, so a stray row for some other portfolio
        cannot put an instrument on screen that no reported book holds.

        Scoped to a stream for the same reason the position table is: once the
        qt stream is backfilled, an unscoped DISTINCT would union the model's
        holdings with the desk's and correlate a book nobody holds.
        """
        books = [b for b in dict.fromkeys(portfolio_ids) if b]
        if not books:
            return []
        conn = self.connection_factory()
        try:
            with conn.cursor() as cursor:
                scoped = (
                    portfolio_type is not None
                    and self._has_portfolio_type(cursor, "positions")
                )
                stream_predicate = "AND portfolio_type = %s" if scoped else ""
                launch_predicate, launch_params = self._date_launch_scope()
                params = (books,)
                if scoped:
                    params += (portfolio_type,)
                params += launch_params
                if scoped:
                    params += (portfolio_type,)
                params += launch_params
                cursor.execute(
                    f"""
                    SELECT DISTINCT symbol
                    FROM trading.positions AS held_positions
                    WHERE portfolio_id = ANY(%s)
                      AND quantity != 0
                      {stream_predicate}
                      {launch_predicate}
                      AND date = (
                          SELECT max(date) FROM trading.positions
                          WHERE portfolio_id = held_positions.portfolio_id
                          {stream_predicate}
                          {launch_predicate}
                      )
                    ORDER BY symbol
                    """,
                    params,
                )
                rows = cursor.fetchall()
        finally:
            conn.close()
        return [row["symbol"] if isinstance(row, dict) else row[0] for row in rows]

    def _fetch_recent_executions(self, cursor, strategy_type, portfolio_id,
                                 reporting_date=None, portfolio_type=PRIMARY_STREAM,
                                 has_portfolio_type=None):
        if has_portfolio_type is None:
            has_portfolio_type = self._has_portfolio_type(cursor, "executions")
        # Legacy execution rows cannot be attributed to a stream. Do not label
        # an unscoped historical list as this day's QT fills.
        if not has_portfolio_type or reporting_date is None or portfolio_type is None:
            return []
        start = datetime.combine(reporting_date, day_time.min, tzinfo=timezone.utc)
        cursor.execute(
            """
            SELECT symbol, side, quantity, price,
                   execution_time, commissions_fees
            FROM trading.executions
            WHERE strategy_id = %s
            AND portfolio_id = %s
            AND portfolio_type = %s
            AND execution_time >= %s AND execution_time < %s
            ORDER BY execution_time DESC
            """,
            (strategy_type, portfolio_id, portfolio_type, start, start + timedelta(days=1)),
        )
        return cursor.fetchall()

    def _fetch_yesterday_positions(
        self,
        cursor,
        strategy_type,
        portfolio_id,
        portfolio_type=PRIMARY_STREAM,
        has_portfolio_type=None,
    ):
        """The snapshot before the latest one, in the same stream.

        This asked for CURRENT_DATE - 1 literally, so the comparison had
        nothing to compare against every Monday and after every holiday --
        markets are shut, the engine writes no rows, and the panel went blank
        with no explanation. "The previous snapshot" is the question the panel
        is actually asking.
        """
        if portfolio_type is not None and has_portfolio_type is None:
            has_portfolio_type = self._has_portfolio_type(cursor, "positions")
        scoped = portfolio_type is not None and has_portfolio_type

        # Same stream as the current snapshot, or the two columns of the
        # comparison are two different books.
        stream_predicate = "AND portfolio_type = %s" if scoped else ""
        launch_predicate, launch_params = self._date_launch_scope()
        scope = (
            (strategy_type, portfolio_id, portfolio_type)
            if scoped
            else (strategy_type, portfolio_id)
        ) + launch_params
        params = scope + scope + scope
        cursor.execute(
            f"""
            SELECT DISTINCT ON (strategy_name, symbol)
                   strategy_name, date, symbol, quantity, average_price,
                   daily_unrealized_pnl, daily_realized_pnl, updated_at
            FROM trading.positions
            WHERE strategy_id = %s
            AND portfolio_id = %s
            {stream_predicate}
            {launch_predicate}
            AND date = (
                SELECT max(date) FROM trading.positions
                WHERE strategy_id = %s AND portfolio_id = %s
                {stream_predicate}
                {launch_predicate}
                AND date < (
                    SELECT max(date) FROM trading.positions
                    WHERE strategy_id = %s AND portfolio_id = %s
                    {stream_predicate}
                    {launch_predicate}
                )
            )
            ORDER BY strategy_name, symbol, updated_at DESC
            """,
            params,
        )
        return cursor.fetchall()

    def fetch_summary_row(self, strategy_type, portfolio_id):
        conn = self.connection_factory()
        try:
            with conn.cursor() as cursor:
                return self._fetch_summary_row(cursor, strategy_type, portfolio_id)
        finally:
            conn.close()

    def fetch_detail_rows(self, strategy_type, portfolio_id, position_stream=DEFAULT_POSITION_STREAM):
        position_stream = validate_position_stream(position_stream)
        conn = self.connection_factory()
        try:
            with conn.cursor() as cursor:
                latest = self._fetch_latest_live_results(cursor, strategy_type, portfolio_id)
                has_portfolio_type = self._has_portfolio_type(cursor)
                equity_curve = self._fetch_equity_curve(
                    cursor,
                    strategy_type,
                    portfolio_id,
                    PRIMARY_STREAM,
                    has_portfolio_type=has_portfolio_type,
                ) if has_portfolio_type else []
                equity_by_stream = self._fetch_equity_by_stream(
                    cursor,
                    strategy_type,
                    portfolio_id,
                    has_portfolio_type=has_portfolio_type,
                )
                positions_scoped = self._has_portfolio_type(cursor, "positions")
                positions = self._fetch_current_positions(
                    cursor, strategy_type, portfolio_id,
                    portfolio_type=position_stream,
                    has_portfolio_type=positions_scoped,
                )
                stream_predicate = "AND portfolio_type = %s" if positions_scoped else ""
                launch_predicate, launch_params = self._date_launch_scope()
                snapshots = {}
                streams = (position_stream, PRIMARY_STREAM) if positions_scoped and position_stream != PRIMARY_STREAM else (position_stream,)
                for stream in streams:
                    scope = (
                        (strategy_type, portfolio_id, stream)
                        if positions_scoped
                        else (strategy_type, portfolio_id)
                    ) + launch_params
                    # Includes zero rows: a flat book still has a dated
                    # snapshot and its own engine component identities.
                    cursor.execute(
                        f"""SELECT date, strategy_name FROM trading.positions
                            WHERE strategy_id = %s AND portfolio_id = %s {stream_predicate}
                              {launch_predicate}
                              AND date = (SELECT max(date) FROM trading.positions
                                          WHERE strategy_id = %s AND portfolio_id = %s {stream_predicate}
                                          {launch_predicate})""",
                        scope + scope,
                    )
                    snapshots[stream] = cursor.fetchall()
                snapshot = snapshots[position_stream]
                position_date = snapshot[0]["date"] if snapshot else None
                position_names = tuple({r["strategy_name"] for r in snapshot})
                qt_snapshot = snapshots.get(PRIMARY_STREAM, ()) if positions_scoped else ()
                qt_positions = (
                    positions if position_stream == PRIMARY_STREAM else
                    self._fetch_current_positions(
                        cursor, strategy_type, portfolio_id,
                        portfolio_type=PRIMARY_STREAM,
                        has_portfolio_type=True,
                    )
                ) if positions_scoped else None
                executions_scoped = self._has_portfolio_type(cursor, "executions")
                executions = self._fetch_recent_executions(
                    cursor, strategy_type, portfolio_id,
                    latest["date"] if latest else None,
                    has_portfolio_type=executions_scoped,
                )
                yesterday_positions = self._fetch_yesterday_positions(
                    cursor, strategy_type, portfolio_id,
                    has_portfolio_type=positions_scoped,
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
            position_date=position_date,
            position_strategy_names=position_names,
            position_stream=position_stream if positions_scoped else None,
            execution_date=latest["date"] if latest else None,
            executions_available=executions_scoped and latest is not None,
            qt_positions=qt_positions,
            activity_stream=PRIMARY_STREAM if positions_scoped else None,
            finalized_positions_available=bool(qt_snapshot) and bool(yesterday_positions) if positions_scoped else False,
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

                # The MODEL is the system stream. Every non-empty publication also
                # writes qt (and, with migration 015, qt_proposal) rows for the same
                # symbol-day, and other streams share equity_curve, so both reads
                # select the system stream only: one row per symbol-day.
                cursor.execute(
                    """
                    SELECT updated_at AS date, symbol, quantity,
                           average_price AS entry_price
                    FROM trading.positions
                    WHERE strategy_id = %s AND portfolio_id = %s AND updated_at >= %s
                      AND portfolio_type = 'system'
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
                      AND portfolio_type = 'system'
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

    def _fetch_lifecycle(self, cursor, strategy_id, *, for_update=False):
        cursor.execute(
            """
            SELECT id, strategy_type, portfolio_id, lifecycle
            FROM trading.strategy_registry WHERE id = %s
            """ + (" FOR UPDATE" if for_update else ""),
            (strategy_id,),
        )
        return cursor.fetchone()

    def _lock_lifecycle_books(self, cursor, strategy_row):
        """Lock every current or historical evidence book canonically.

        Membership removal is intentionally non-destructive: positions and the
        assignment audit remain in the removed book. Limiting this set to current
        membership would make removal a retirement bypass, so persisted position
        scopes and both sides of assignment history remain part of the lock and
        flatness universe.
        """
        cursor.execute(
            """
            SELECT portfolio_id FROM (
                SELECT portfolio_id
                FROM trading.strategy_book_memberships
                WHERE strategy_id = %s
                UNION
                SELECT positions.portfolio_id
                FROM trading.positions AS positions
                JOIN trading.strategy_registry AS registry
                  ON registry.strategy_type = positions.strategy_id
                WHERE registry.id = %s
                UNION
                SELECT from_portfolio_id AS portfolio_id
                FROM trading.portfolio_assignments
                WHERE strategy_id = %s AND from_portfolio_id IS NOT NULL
                UNION
                SELECT to_portfolio_id AS portfolio_id
                FROM trading.portfolio_assignments
                WHERE strategy_id = %s AND to_portfolio_id IS NOT NULL
            ) AS relevant_books
            ORDER BY portfolio_id
            """,
            (
                strategy_row["id"],
                strategy_row["id"],
                strategy_row["id"],
                strategy_row["id"],
            ),
        )
        books = [row["portfolio_id"] for row in cursor.fetchall()]
        books.append(strategy_row["portfolio_id"])
        acquire_qt_book_locks(cursor, *books)
        return sorted(set(books))

    def _ever_live(self, cursor, strategy_id, current_state):
        if current_state == "live":
            return True
        cursor.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM trading.strategy_lifecycle_log
                WHERE strategy_id = %s
                  AND (before_state = 'live' OR after_state = 'live')
            ) AS ever_live
            """,
            (strategy_id,),
        )
        return bool(cursor.fetchone()["ever_live"])

    def _require_effectively_flat(self, cursor, strategy_row, books, *, ever_live):
        """Refuse any effective holding and fail closed on incomplete live evidence.

        Position identity deliberately excludes the stream: QT and system are
        competing views of the same engine/book/name/symbol identity. The newest
        date wins for each identity and QT wins the tie, retaining explicit zero
        rows as closure evidence.
        """
        cursor.execute(
            """
            SELECT portfolio_id, strategy_id, strategy_name, symbol, date,
                   portfolio_type, quantity
            FROM trading.positions
            WHERE strategy_id = %s AND portfolio_id = ANY(%s)
              AND portfolio_type IN ('qt', 'system')
            ORDER BY portfolio_id, strategy_name, symbol, date DESC,
                     CASE portfolio_type WHEN 'qt' THEN 0 ELSE 1 END
            """,
            (strategy_row["strategy_type"], books),
        )
        grouped = {}
        for row in cursor.fetchall():
            identity = (
                row["portfolio_id"],
                row["strategy_id"],
                row["strategy_name"],
                row["symbol"],
            )
            grouped.setdefault(identity, []).append(row)

        unreliable = not grouped and ever_live
        for rows in grouped.values():
            newest = max(row["date"] for row in rows)
            newest_rows = [row for row in rows if row["date"] == newest]
            qt_rows = [row for row in newest_rows if row["portfolio_type"] == "qt"]
            selected = qt_rows[0] if qt_rows else None
            if selected is not None:
                if selected["quantity"] != 0:
                    raise OpenPositionsError("Strategy has open positions")
                continue

            # A never-live incubation may close without evidence, but it still
            # cannot close over a published nonzero proposal.
            if any(row["quantity"] != 0 for row in newest_rows):
                if ever_live:
                    unreliable = True
                else:
                    raise OpenPositionsError("Strategy has open positions")
            elif ever_live:
                unreliable = True

        if unreliable:
            raise PositionsUnavailableError("Reliable position evidence is unavailable")

    def _require_desk_days_finalized(self, cursor, books):
        """Refuse a lifecycle change away from live while a desk day awaits finalization.

        An unfinalized QT desk day is a processed desk decision whose stored
        accounting (trading.desk_run_results, written in the desk processor's
        processing transaction) has no trading.qt_desk_finalizations row yet.
        The next-day finalizers write qt-stream positions, live_results and
        equity_curve rows for that day; once the strategy is no longer live,
        only migration 025's scope check would stand between them and a
        non-live scope. Days are matched by book over every book the lifecycle
        change locks (the caller holds those canonical book locks, which the
        finalizer's upstream fence also takes).

        Only days the shipped finalizer can still finalize count (N5 r3): the
        next-day prepare finalizes day D only on D+1, so a pending day dated
        before yesterday (UTC, by the database clock) can never be finalized and
        never blocks. Unqualified clock_timestamp(), as the finalizer uses it, so
        a test clock applies identically. Any future tool that can finalize an
        older day must carry its own live-owner check. Without trading.desk_run_results
        there is nothing to finalize; with it but without the finalization
        table, every stored day counts as unfinalized (fail closed).
        """
        cursor.execute(
            """
            SELECT to_regclass('trading.desk_run_results') IS NOT NULL AS accounting,
                   to_regclass('trading.qt_desk_finalizations') IS NOT NULL AS finalizations
            """
        )
        present = cursor.fetchone()
        if not present["accounting"]:
            return
        canonical = sorted({str(book).strip().upper() for book in books if book is not None})
        finalized = (
            "AND NOT EXISTS (SELECT 1 FROM trading.qt_desk_finalizations AS finalization"
            " WHERE finalization.decision_id = accounting.decision_id)"
            if present["finalizations"] else ""
        )
        cursor.execute(
            """
            SELECT accounting.portfolio_id AS book_id, accounting.date AS source_day,
                   accounting.decision_id
            FROM trading.desk_run_results AS accounting
            WHERE upper(btrim(accounting.portfolio_id)) = ANY(%s)
              AND accounting.date >= (clock_timestamp() AT TIME ZONE 'UTC')::date - 1
            """ + finalized + """
            ORDER BY accounting.date, accounting.portfolio_id, accounting.decision_id
            """,
            (canonical,),
        )
        pending = cursor.fetchall()
        if pending:
            days = ", ".join(
                f"{row['book_id']} {row['source_day']}" for row in pending[:5]
            )
            more = f" and {len(pending) - 5} more" if len(pending) > 5 else ""
            raise DeskFinalizationPendingError(
                "QT desk day(s) awaiting next-day finalization: "
                f"{days}{more}. Finalize them before changing the lifecycle away from live."
            )

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
        if not math.isfinite(mock_capital) or mock_capital <= 0:
            raise IncubationError("mock_capital must be a positive finite number")
        if not reason or not reason.strip():
            raise IncubationError("reason must be non-empty")

        conn = self.connection_factory()
        try:
            with conn:
                with conn.cursor() as cursor:
                    row = self._fetch_lifecycle(cursor, strategy_id, for_update=True)
                    if row is None:
                        raise StrategyNotInRegistry(f"Strategy {strategy_id} not found")
                    current_state = row["lifecycle"]
                    if current_state == "incubating":
                        raise IncubationError(f"Strategy {strategy_id} is already incubating")
                    books = self._lock_lifecycle_books(cursor, row)
                    revalidated = self._fetch_lifecycle(cursor, strategy_id)
                    if revalidated["lifecycle"] != current_state:
                        raise IncubationStorageError("Lifecycle changed during transition")
                    if current_state == "live":
                        self._require_effectively_flat(
                            cursor, row, books, ever_live=True
                        )
                    # Live -> incubating (and retired -> incubating) must not reopen
                    # a desk day to a finalizer under a non-live scope.
                    self._require_desk_days_finalized(cursor, books)
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
                        cursor, strategy_id, current_state, "incubating", reason, user_id
                    )
        except psycopg2.Error as exc:
            logger.error("Incubation write failed: %s", exc, exc_info=True)
            raise IncubationStorageError("Database error") from exc
        finally:
            conn.close()

    def promote_to_live(self, strategy_id, reason, user_id):
        if not reason or not reason.strip():
            raise IncubationError("reason must be non-empty")

        conn = self.connection_factory()
        try:
            with conn:
                with conn.cursor() as cursor:
                    row = self._fetch_lifecycle(cursor, strategy_id, for_update=True)
                    if row is None:
                        raise StrategyNotInRegistry(f"Strategy {strategy_id} not found")
                    current_state = row["lifecycle"]
                    if current_state != "incubating":
                        raise IncubationError(
                            f"Strategy {strategy_id} is not currently incubating"
                        )
                    self._lock_lifecycle_books(cursor, row)
                    revalidated = self._fetch_lifecycle(cursor, strategy_id)
                    if revalidated["lifecycle"] != current_state:
                        raise IncubationStorageError("Lifecycle changed during transition")
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
                        cursor, strategy_id, "incubating", "live", reason, user_id
                    )
        except psycopg2.Error as exc:
            logger.error("Incubation write failed: %s", exc, exc_info=True)
            raise IncubationStorageError("Database error") from exc
        finally:
            conn.close()

    def retire_strategy(self, strategy_id, reason, user_id):
        if not reason or not reason.strip():
            raise IncubationError("reason must be non-empty")

        conn = self.connection_factory()
        try:
            with conn:
                with conn.cursor() as cursor:
                    row = self._fetch_lifecycle(cursor, strategy_id, for_update=True)
                    if row is None:
                        raise StrategyNotInRegistry(f"Strategy {strategy_id} not found")
                    current_state = row["lifecycle"]
                    if current_state == "retired":
                        return
                    books = self._lock_lifecycle_books(cursor, row)
                    revalidated = self._fetch_lifecycle(cursor, strategy_id)
                    if revalidated["lifecycle"] != current_state:
                        raise IncubationStorageError("Lifecycle changed during transition")
                    ever_live = self._ever_live(cursor, strategy_id, current_state)
                    self._require_effectively_flat(
                        cursor, row, books, ever_live=ever_live
                    )
                    if current_state == "live":
                        self._require_desk_days_finalized(cursor, books)
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
                        cursor, strategy_id, current_state, "retired", reason, user_id
                    )
        except psycopg2.Error as exc:
            logger.error("Incubation write failed: %s", exc, exc_info=True)
            raise IncubationStorageError("Database error") from exc
        finally:
            conn.close()

    def list_lifecycle_history(self, strategy_id, limit=100):
        conn = self.connection_factory()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, strategy_id, before_state, after_state, reason,
                           user_id, created_at
                    FROM trading.strategy_lifecycle_log
                    WHERE strategy_id = %s
                    ORDER BY created_at DESC, id DESC
                    LIMIT %s
                    """,
                    (strategy_id, min(limit, 100)),
                )
                return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()


    # -- qt stream writes (F2) ------------------------------------------------
    #
    # Restores AlgoLens PR #31, ported onto the layered package. The engine
    # seeds trading.positions with portfolio_type='qt' as a copy of 'system';
    # these are the only writes that make the two diverge, and every one of
    # them lands in trading.position_overrides in the same transaction.

    def _fetch_risk_envelope(self, cursor, strategy_type, portfolio_id):
        """Select the latest publication, breaking timestamp ties by row ID."""
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
            SELECT limits FROM trading.risk_limits
            WHERE strategy_id = %s AND portfolio_id = %s
            ORDER BY published_at DESC, id DESC LIMIT 1
            """,
            (strategy_type, portfolio_id),
        )
        row = cursor.fetchone()
        return row["limits"] if row else None

    def fetch_risk_envelope(self, strategy_type, portfolio_id):
        """The most recent envelope trade-ngin published for this book."""
        conn = self.connection_factory()
        try:
            with conn.cursor() as cursor:
                return self._fetch_risk_envelope(cursor, strategy_type, portfolio_id)
        finally:
            conn.close()

    def _fetch_qt_book(self, cursor, strategy_type, portfolio_id, position_date):
        cursor.execute(
            """
            SELECT symbol, strategy_name, date, quantity, average_price
            FROM trading.positions
            WHERE strategy_id = %s AND portfolio_id = %s
              AND portfolio_type = %s AND date = %s
            ORDER BY strategy_name, symbol
            """,
            (strategy_type, portfolio_id, QT_STREAM, position_date),
        )
        return [_plain_position(row) for row in cursor.fetchall()]

    def fetch_qt_book(self, strategy_type, portfolio_id):
        """Today's QT positions, retaining individual strategy and zero evidence."""
        conn = self.connection_factory()
        try:
            with conn.cursor() as cursor:
                return self._fetch_qt_book(
                    cursor, strategy_type, portfolio_id, current_utc_date()
                )
        finally:
            conn.close()

    def _strategy_is_book_member(self, cursor, strategy_id, portfolio_id):
        """Current membership, with the migration-era primary-book fallback."""
        cursor.execute(
            """
            SELECT to_regclass('trading.strategy_book_memberships') IS NOT NULL
                   AS memberships_present
            """
        )
        memberships_present = cursor.fetchone()["memberships_present"]
        if memberships_present:
            cursor.execute(
                """
                SELECT CASE
                    WHEN EXISTS (
                        SELECT 1 FROM trading.strategy_book_memberships
                        WHERE strategy_id = %s
                    ) THEN EXISTS (
                        SELECT 1 FROM trading.strategy_book_memberships
                        WHERE strategy_id = %s AND portfolio_id = %s
                    )
                    ELSE EXISTS (
                        SELECT 1 FROM trading.strategy_registry
                        WHERE id = %s AND portfolio_id = %s
                    )
                END AS is_member
                """,
                (strategy_id, strategy_id, portfolio_id, strategy_id, portfolio_id),
            )
        else:
            cursor.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM trading.strategy_registry
                    WHERE id = %s AND portfolio_id = %s
                ) AS is_member
                """,
                (strategy_id, portfolio_id),
            )
        return bool(cursor.fetchone()["is_member"])

    def _fetch_summary_if_available(self, cursor, strategy_type, portfolio_id):
        """Preserve the advisory gate when the engine has no results table yet."""
        cursor.execute(
            "SELECT to_regclass('trading.live_results') IS NOT NULL AS present"
        )
        if not cursor.fetchone()["present"]:
            return None
        return self._fetch_summary_row(cursor, strategy_type, portfolio_id)

    def _fetch_existing_position(self, cursor, strategy_type, portfolio_id, symbol,
                                 strategy_name, position_date):
        # Lock the row for the rest of the transaction so we capture the true
        # before_state in the audit trail. If two QT members edit the same symbol
        # concurrently, or the engine's daily run writes between our read and
        # write, the lock ensures we read the current row and record what it was
        # at the moment we decided to change it. When the row does not exist there
        # is nothing to lock; the ON CONFLICT clause still makes the insert safe.
        cursor.execute(
            """
            SELECT symbol, strategy_name, date, quantity, average_price,
                   daily_unrealized_pnl, daily_realized_pnl
            FROM trading.positions
            WHERE strategy_id = %s
              AND portfolio_id = %s
              AND portfolio_type = %s
              AND symbol = %s
              AND strategy_name = %s AND date = %s
            FOR UPDATE
            """,
            (strategy_type, portfolio_id, QT_STREAM, symbol, strategy_name, position_date),
        )
        row = cursor.fetchone()
        # Keep raw NUMERICs here: the quantity-only UPDATE binds this price.
        # Projection to floats belongs only in JSON response/audit material.
        return dict(row) if row else None

    def _resolve_strategy_name(self, cursor, strategy_type, portfolio_id,
                               symbol, position_date, requested_name=None):
        """The engine's own strategy_name for this book.

        strategy_name is part of the positions primary key and the engine
        chooses its value. Guessing it (from the registry's display name, say)
        would write QT's edit to a different key than the engine's row -- the
        write would appear to succeed and the engine would never see it. So take
        the value from rows the engine already wrote.
        """
        cursor.execute(
            """
            SELECT DISTINCT strategy_name
            FROM trading.positions
            WHERE portfolio_id = %s AND strategy_id = %s
              AND portfolio_type = %s AND date = %s AND symbol = %s
            """,
            (portfolio_id, strategy_type, QT_STREAM, position_date, symbol),
        )
        names = {row["strategy_name"] for row in cursor.fetchall()}
        if not names:
            # A new symbol has no row to bind. Only a unique current QT
            # strategy (or an explicitly named member of that snapshot) may
            # own it; an unrelated most-recent row is never a tie-breaker.
            cursor.execute(
                """
                SELECT DISTINCT strategy_name FROM trading.positions
                WHERE portfolio_id = %s AND strategy_id = %s
                  AND portfolio_type = %s AND date = %s
                """,
                (portfolio_id, strategy_type, QT_STREAM, position_date),
            )
            names = {row["strategy_name"] for row in cursor.fetchall()}
        if requested_name is not None:
            names = names.intersection({requested_name})
        if len(names) != 1 or any(not isinstance(name, str) or not name.strip() for name in names):
            raise StrategyNameUnresolved(
                f"Expected one QT position identity for {portfolio_id}/"
                f"{strategy_type}/{symbol} on {position_date}; found {len(names)}."
            )
        return next(iter(names))

    def write_qt_position(
        self,
        strategy_type,
        portfolio_id,
        normalized,
        user_id,
        risk_check,
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
                    strategy_row = self._fetch_lifecycle(
                        cursor, normalized["strategy_id"], for_update=True
                    )
                    if strategy_row is None:
                        raise PositionValidationError(
                            "strategy_not_found", "Strategy not found"
                        )
                    acquire_qt_book_locks(cursor, portfolio_id)
                    require_legacy_qt_disabled(cursor, portfolio_id)
                    revalidated = self._fetch_lifecycle(
                        cursor, normalized["strategy_id"]
                    )
                    if revalidated["lifecycle"] == "retired":
                        raise PositionValidationError(
                            "strategy_retired",
                            "A retired strategy cannot accept position edits",
                        )
                    # Sample after waiting for the book lock. A request queued
                    # across UTC midnight must evaluate and write the new day,
                    # matching the engine/report calendar.
                    position_date = current_utc_date()
                    if not self._strategy_is_book_member(
                        cursor, normalized["strategy_id"], portfolio_id
                    ):
                        raise PositionValidationError(
                            "not_a_member_of_book",
                            f"{normalized['strategy_id']} does not belong to {portfolio_id}",
                        )
                    envelope = self._fetch_risk_envelope(
                        cursor, strategy_type, portfolio_id
                    )
                    book = self._fetch_qt_book(
                        cursor, strategy_type, portfolio_id, position_date
                    )
                    summary = self._fetch_summary_if_available(
                        cursor, strategy_type, portfolio_id
                    )
                    verdict = risk_check(envelope, book, summary)
                    overrode_risk = not verdict["passed"]
                    strategy_name = self._resolve_strategy_name(
                        cursor, strategy_type, portfolio_id, normalized["symbol"],
                        position_date, normalized.get("strategy_name"),
                    )
                    # Reserve an absent identity before taking its snapshot.
                    # SELECT ... FOR UPDATE protects an existing row, but locks
                    # nothing when the row is absent. Two writers could therefore
                    # both record {} as before_state, even though PostgreSQL later
                    # serialised their upserts. INSERT ... DO NOTHING waits for a
                    # competing engine/manual insert to commit or roll back; only
                    # the loser then reads the committed row under FOR UPDATE.
                    #
                    # A quantity-only edit needs a price only if it wins this
                    # reservation. Use a temporary valid value so the conflict
                    # path can still reach and preserve an existing price. If it
                    # really did create a row, build_after_state raises the
                    # user-facing missing-price validation error and this whole
                    # transaction rolls its temporary insert back.
                    provisional_price = normalized["average_price"]
                    if provisional_price is None:
                        provisional_price = 0
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
                        -- On conflict nothing is overwritten. The loser must
                        -- snapshot the winner before it can edit it and write
                        -- an audit row with a truthful before_state.
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0, 0, now(), now())
                        ON CONFLICT (portfolio_id, strategy_id, strategy_name, date,
                                     symbol, portfolio_type)
                        DO NOTHING
                        RETURNING symbol, quantity, average_price
                        """,
                        (
                            portfolio_id,
                            strategy_type,
                            strategy_name,
                            position_date,
                            normalized["symbol"],
                            QT_STREAM,
                            normalized["quantity"],
                            provisional_price,
                        ),
                    )
                    position = cursor.fetchone()
                    if position is None:
                        before = self._fetch_existing_position(
                            cursor, strategy_type, portfolio_id, normalized["symbol"],
                            strategy_name, position_date,
                        )
                        after = build_after_state(before, normalized)
                        after.update(strategy_name=strategy_name, date=str(position_date),
                                     portfolio_id=portfolio_id, portfolio_type=QT_STREAM)
                        cursor.execute(
                            """
                            UPDATE trading.positions
                            SET quantity = %s, average_price = %s, updated_at = now()
                            WHERE portfolio_id = %s AND strategy_id = %s
                              AND strategy_name = %s AND date = %s
                              AND symbol = %s AND portfolio_type = %s
                            RETURNING symbol, quantity, average_price
                            """,
                            (
                                after["quantity"],
                                after.get("average_price"),
                                portfolio_id,
                                strategy_type,
                                strategy_name,
                                position_date,
                                normalized["symbol"],
                                QT_STREAM,
                            ),
                        )
                        position = cursor.fetchone()
                    else:
                        before = None
                        after = build_after_state(before, normalized)
                        after.update(strategy_name=strategy_name, date=str(position_date),
                                     portfolio_id=portfolio_id, portfolio_type=QT_STREAM)
                    # PostgreSQL may silently round to a column's declared scale.
                    # Compare raw RETURNING values to the intended exact values
                    # before JSON projection or audit. Raising inside `with conn`
                    # rolls back both an inserted reservation and an UPDATE.
                    for field, code in (
                        ("quantity", "quantity_storage_not_exact"),
                        ("average_price", "price_storage_not_exact"),
                    ):
                        if position is None or position.get(field) != after[field]:
                            raise PositionValidationError(
                                code, "Database could not preserve the exact position value"
                            )
                    # Coerced, not raw: NUMERIC columns come back as Decimal and
                    # jsonify renders those as JSON strings. The 201 body was
                    # returning "quantity": "20", which any client parsing it as
                    # a number would get wrong.
                    position = _plain_position(position)

                    cursor.execute(
                        """
                        INSERT INTO trading.position_overrides
                            (portfolio_id, user_id, source_app, strategy_id, symbol,
                             before_state, after_state, reason,
                             risk_check_result, overrode_risk)
                        VALUES (%s, %s, 'algolens', %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                        """,
                        (
                            portfolio_id,
                            user_id,
                            strategy_type,
                            normalized["symbol"],
                            json.dumps(_plain_position(before) if before else {}, default=str),
                            json.dumps(_plain_position(after), default=str),
                            normalized["reason"],
                            json.dumps(verdict),
                            overrode_risk,
                        ),
                    )
                    override_id = cursor.fetchone()["id"]

            return {
                "position": position,
                "override_id": override_id,
                "risk_check": verdict,
            }
        finally:
            conn.close()

    def fetch_overrides(self, strategy_type, portfolio_id, limit=100):
        """Recent audit entries. Read-only -- this table cannot be modified."""
        conn = self.connection_factory()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT o.id, o.user_id, o.source_app, o.strategy_id, o.symbol,
                           o.before_state, o.after_state, o.reason,
                           o.risk_check_result, o.overrode_risk, o.created_at
                    FROM trading.position_overrides o
                    LEFT JOIN trading.position_override_legacy_scopes legacy
                           ON legacy.override_id = o.id
                    WHERE COALESCE(o.portfolio_id, legacy.portfolio_id) = %s
                      AND o.strategy_id = %s
                    ORDER BY o.created_at DESC
                    LIMIT %s
                    """,
                    (portfolio_id, strategy_type, limit),
                )
                return [dict(r) for r in cursor.fetchall()]
        finally:
            conn.close()
