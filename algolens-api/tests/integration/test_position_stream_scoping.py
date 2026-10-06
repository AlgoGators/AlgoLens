"""A position read must name the stream it is reading.

``trading.positions`` carries one row per (symbol, date, stream). Today every
row in production is ``portfolio_type = 'system'``, so a query with no stream
predicate is accidentally right and no test could tell. The moment trade-ngin
migration 002 backfills the qt stream, every symbol and date has two rows, and
``DISTINCT ON (symbol) ORDER BY updated_at DESC`` returns whichever stream was
written last -- the model's book and the desk's book in one table, with nothing
on screen saying which.

The failure mode that matters most is on the write path. After a desk edit the
qt row has the newest ``updated_at``, so the edit appears to have worked. It
would look exactly the same if it had been written to the wrong stream.

This is AlgoLens issue #83, and these tests are what unblocks applying migration
002 to production. They are integration tests because the defect is in SQL: a
double would have agreed with whatever the code asked it for.
"""

import datetime

import pytest
from psycopg2.extras import RealDictCursor

from tests.integration.conftest import claim_schema, require_test_dsn

psycopg2 = pytest.importorskip("psycopg2")

from algolens.infrastructure.portfolio.repositories import (  # noqa: E402
    PostgresPortfolioRepository,
)
from algolens.infrastructure.portfolio import repositories as portfolio_repositories  # noqa: E402

pytestmark = pytest.mark.integration

SCHEMA = """
CREATE TABLE trading.positions (
    id                   BIGSERIAL PRIMARY KEY,
    strategy_id          TEXT NOT NULL,
    strategy_name        TEXT,
    portfolio_id         TEXT NOT NULL,
    portfolio_type       TEXT NOT NULL DEFAULT 'system',
    symbol               TEXT NOT NULL,
    quantity             NUMERIC NOT NULL,
    average_price        NUMERIC,
    daily_unrealized_pnl NUMERIC NOT NULL DEFAULT 0,
    daily_realized_pnl   NUMERIC NOT NULL DEFAULT 0,
    date                 DATE NOT NULL,
    last_update          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ
);
"""

STRATEGY = "LIVE_TREND_FOLLOWING"
BOOK = "BASE_PORTFOLIO"
TODAY = datetime.date(2026, 9, 4)
YESTERDAY = datetime.date(2026, 9, 3)


def _insert(cur, symbol, quantity, stream, date, updated_at, portfolio_id=BOOK):
    cur.execute(
        """
        INSERT INTO trading.positions
            (strategy_id, strategy_name, portfolio_id, portfolio_type, symbol,
             quantity, average_price, date, updated_at)
        VALUES (%s, 'Trend', %s, %s, %s, %s, 100.0, %s, %s)
        """,
        (STRATEGY, portfolio_id, stream, symbol, quantity, date, updated_at),
    )


@pytest.fixture()
def repo():
    dsn = require_test_dsn()
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    with conn.cursor() as cur:
        claim_schema(cur)
        cur.execute(SCHEMA)

        # Both streams, same symbols, same dates -- what migration 002 produces.
        # The qt rows are written LAST, which is what makes an unscoped
        # DISTINCT ON return them.
        _insert(cur, "ES.v.0", 10, "system", TODAY, "2026-09-04 09:00")
        _insert(cur, "ZN.v.0", 40, "system", TODAY, "2026-09-04 09:00")
        _insert(cur, "ES.v.0", 10, "system", YESTERDAY, "2026-09-03 09:00")
        _insert(cur, "ZN.v.0", 40, "system", YESTERDAY, "2026-09-03 09:00")

        # The desk holds a different size in ES and does not hold ZN at all.
        _insert(cur, "ES.v.0", 25, "qt", TODAY, "2026-09-04 17:30")
        _insert(cur, "GC.v.0", 7, "qt", TODAY, "2026-09-04 17:30")
        _insert(cur, "ES.v.0", 20, "qt", YESTERDAY, "2026-09-03 17:30")

    yield PostgresPortfolioRepository(
        connection_factory=lambda: psycopg2.connect(dsn, cursor_factory=RealDictCursor)
    )
    with conn.cursor() as cur:
        cur.execute("DROP SCHEMA IF EXISTS trading CASCADE")
    conn.close()


def _by_symbol(rows):
    return {r["symbol"]: float(r["quantity"]) for r in rows}


def _current(repo, **kwargs):
    """The current-positions read, called the way fetch_detail_rows calls it.

    Called with no stream argument, so it exercises the default -- which is the
    behaviour under test. Going through fetch_detail_rows would drag in
    live_results and equity_curve, neither of which this defect lives in.
    """
    conn = repo.connection_factory()
    try:
        with conn.cursor() as cur:
            return repo._fetch_current_positions(cur, STRATEGY, BOOK, **kwargs)
    finally:
        conn.close()


def _yesterday(repo, **kwargs):
    conn = repo.connection_factory()
    try:
        with conn.cursor() as cur:
            return repo._fetch_yesterday_positions(cur, STRATEGY, BOOK, **kwargs)
    finally:
        conn.close()


class TestCurrentPositionsAreOneStream:
    def test_the_default_is_the_real_book(self, repo):
        # PRIMARY_STREAM. Every headline figure on the landing dashboard means
        # the system/model book, including the equity curve above this table.
        assert _by_symbol(_current(repo)) == {"ES.v.0": 10.0, "ZN.v.0": 40.0}

    def test_the_other_stream_is_not_blended_in(self, repo):
        # ZN is a system-only holding. Before the stream predicate it appeared
        # in the desk's table, because DISTINCT ON had no reason to exclude it.
        assert "GC.v.0" not in _by_symbol(_current(repo))

    def test_the_quantity_is_the_requested_streams_not_the_newest_rows(self, repo):
        # The two streams disagree about ES: 10 in the model, 25 on the desk.
        # An unscoped read returns 25 here too -- but only because the qt row
        # happens to have been written later. It would return 10 if the engine
        # ran after the desk edit, which is the same bug with the opposite sign.
        assert _by_symbol(_current(repo))["ES.v.0"] == 10.0

    def test_an_explicit_stream_is_honoured(self, repo):
        rows = _current(repo, portfolio_type="qt")
        assert _by_symbol(rows) == {"ES.v.0": 25.0, "GC.v.0": 7.0}


class TestYesterdayComesFromTheSameStream:
    def test_the_comparison_column_is_not_a_different_book(self, repo):
        # The panel puts today beside yesterday. If they come from different
        # streams the difference is a composition change, not a trade.
        assert _by_symbol(_yesterday(repo)) == {"ES.v.0": 10.0, "ZN.v.0": 40.0}

    def test_the_snapshot_date_is_found_within_the_stream(self, repo):
        # The qt stream has no row for a date the system stream reached alone.
        # Taking max(date) across all streams would ask the qt stream for a day
        # it never had and return nothing.
        conn = repo.connection_factory()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO trading.positions
                        (strategy_id, strategy_name, portfolio_id, portfolio_type,
                         symbol, quantity, average_price, date, updated_at)
                    VALUES (%s,'Trend',%s,'system','CL.v.0',5,100.0,%s,now())
                    """,
                    (STRATEGY, BOOK, datetime.date(2026, 9, 5)),
                )
                conn.commit()
        finally:
            conn.close()

        # The system stream now reaches one day further than qt. The dashboard
        # must use that latest model snapshot, not the newer-written QT rows.
        assert _by_symbol(_current(repo)) == {"CL.v.0": 5.0}
        # And its previous day is still the system stream's own snapshot.
        assert _by_symbol(_yesterday(repo)) == {"ES.v.0": 10.0, "ZN.v.0": 40.0}


class TestHeldSymbolsAreOneStream:
    def test_the_correlation_matrix_is_built_from_one_book(self, repo):
        # held_symbols feeds the correlation matrix. Unioning both streams
        # would correlate a portfolio nobody holds.
        assert repo.held_symbols([BOOK]) == ["ES.v.0", "ZN.v.0"]

    def test_an_explicit_stream_is_honoured(self, repo):
        assert repo.held_symbols([BOOK], portfolio_type="qt") == [
            "ES.v.0",
            "GC.v.0",
        ]


CURRENT_BOOK = "HELD_CURRENT_PORTFOLIO"
LAGGING_BOOK = "HELD_LAGGING_PORTFOLIO"
FLAT_BOOK = "HELD_FLAT_PORTFOLIO"
HELD_BOOKS = [LAGGING_BOOK, CURRENT_BOOK, LAGGING_BOOK, None, "", FLAT_BOOK]


@pytest.fixture()
def unequal_book_repo(repo):
    """Requested books have different latest dates in each stream."""
    conn = repo.connection_factory()
    try:
        with conn.cursor() as cur:
            rows = [
                # QT: current book reaches Sep 4, lagging book only Sep 3.
                (CURRENT_BOOK, "GC.v.0", 3, "qt", TODAY),
                (CURRENT_BOOK, "ES.v.0", 2, "qt", TODAY),
                (CURRENT_BOOK, "CURRENT_CLOSED", 4, "qt", YESTERDAY),
                (CURRENT_BOOK, "CURRENT_CLOSED", 0, "qt", TODAY),
                (CURRENT_BOOK, "CURRENT_STALE", 2, "qt", YESTERDAY),
                (LAGGING_BOOK, "ZN.v.0", 5, "qt", YESTERDAY),
                (LAGGING_BOOK, "ES.v.0", 7, "qt", YESTERDAY),
                (LAGGING_BOOK, "LAG_CLOSED", 5, "qt", datetime.date(2026, 9, 2)),
                (LAGGING_BOOK, "LAG_CLOSED", 0, "qt", YESTERDAY),
                (LAGGING_BOOK, "LAG_STALE", 4, "qt", datetime.date(2026, 9, 2)),
                (FLAT_BOOK, "WAS_HELD", 8, "qt", YESTERDAY),
                (FLAT_BOOK, "WAS_HELD", 0, "qt", TODAY),
                # System: current reaches Sep 5, lagging only Sep 2. Thus the
                # other stream is newer in current/QT and lagging/system reads.
                (CURRENT_BOOK, "HG.v.0", 4, "system", datetime.date(2026, 9, 5)),
                (CURRENT_BOOK, "SYS_CURRENT_CLOSED", 4, "system", TODAY),
                (CURRENT_BOOK, "SYS_CURRENT_CLOSED", 0, "system", datetime.date(2026, 9, 5)),
                (CURRENT_BOOK, "SYS_CURRENT_STALE", 2, "system", YESTERDAY),
                (LAGGING_BOOK, "6E.v.0", 5, "system", datetime.date(2026, 9, 2)),
                (LAGGING_BOOK, "HG.v.0", 3, "system", datetime.date(2026, 9, 2)),
                (LAGGING_BOOK, "SYS_LAG_CLOSED", 4, "system", datetime.date(2026, 9, 1)),
                (LAGGING_BOOK, "SYS_LAG_CLOSED", 0, "system", datetime.date(2026, 9, 2)),
                (LAGGING_BOOK, "SYS_LAG_STALE", 2, "system", datetime.date(2026, 9, 1)),
                (FLAT_BOOK, "MODEL_WAS_HELD", 8, "system", TODAY),
                (FLAT_BOOK, "MODEL_WAS_HELD", 0, "system", datetime.date(2026, 9, 5)),
                # An unrequested book reaches Sep 6 in both streams.
                ("UNRELATED_PORTFOLIO", "UNRELATED_QT", 1, "qt", datetime.date(2026, 9, 6)),
                ("UNRELATED_PORTFOLIO", "UNRELATED_SYSTEM", 1, "system", datetime.date(2026, 9, 6)),
            ]
            for book, symbol, quantity, stream, snapshot_date in rows:
                _insert(cur, symbol, quantity, stream, snapshot_date, "2026-09-06 17:30", portfolio_id=book)
            conn.commit()
    finally:
        conn.close()
    return repo


class TestHeldSymbolsUseEachBooksLatestSnapshot:
    def test_default_system_includes_lagging_book_without_stale_or_zero_holdings(self, unequal_book_repo):
        # A global max drops ZN; a per-symbol max resurrects closed/stale rows;
        # an unscoped max lets the newer system snapshot erase QT holdings.
        assert unequal_book_repo.held_symbols(HELD_BOOKS) == [
            "6E.v.0", "HG.v.0",
        ]

    def test_explicit_qt_uses_each_books_qt_date(self, unequal_book_repo):
        assert unequal_book_repo.held_symbols(HELD_BOOKS, portfolio_type="qt") == [
            "ES.v.0", "GC.v.0", "ZN.v.0",
        ]

    def test_explicit_unscoped_read_still_uses_each_books_latest_date(self, unequal_book_repo):
        # Without a requested stream, each book uses its newest snapshot across
        # all streams: system/Sep 5 for current, QT/Sep 3 for lagging.
        assert unequal_book_repo.held_symbols(HELD_BOOKS, portfolio_type=None) == [
            "ES.v.0", "HG.v.0", "ZN.v.0",
        ]

    def test_legacy_schema_uses_each_books_latest_date(self, unequal_book_repo, monkeypatch):
        conn = unequal_book_repo.connection_factory()
        try:
            with conn.cursor() as cur:
                cur.execute("ALTER TABLE trading.positions DROP COLUMN portfolio_type")
                conn.commit()
        finally:
            conn.close()

        # The disposable schema changed after earlier tests cached its columns.
        # Reset only the cache; the real catalog query detects the legacy schema.
        monkeypatch.setattr(portfolio_repositories, "_has_portfolio_type_cache", {})
        monkeypatch.setattr(portfolio_repositories, "_has_portfolio_type_expires_at", 0)
        assert unequal_book_repo.held_symbols(HELD_BOOKS) == [
            "ES.v.0", "HG.v.0", "ZN.v.0",
        ]


class TestADatabaseWithoutStreams:
    """Migration 001 adds portfolio_type. Before it, there is nothing to scope."""

    def test_the_predicate_is_dropped_rather_than_failing(self, repo):
        conn = repo.connection_factory()
        try:
            with conn.cursor() as cur:
                cur.execute("ALTER TABLE trading.positions DROP COLUMN portfolio_type")
                conn.commit()
        finally:
            conn.close()

        # The capability check is cached for a few seconds, so ask directly
        # with the flag the caller would have computed.
        rows = _current(repo, has_portfolio_type=False)

        # Every row for the latest date, because there are no streams to
        # separate. Not an error, and not empty.
        assert set(_by_symbol(rows)) == {"ES.v.0", "GC.v.0", "ZN.v.0"}
