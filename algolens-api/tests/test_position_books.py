"""Positions are read for one book and that book's latest date.

trading.positions holds one row per (portfolio, strategy, date, symbol, book).
Two bugs this guards against (AlgoGators/AlgoLens#83):

* No book predicate: once qt rows exist, system and qt rows for the same symbol
  compete in one DISTINCT ON and the page shows whichever was updated last.
* `quantity != 0` applied BEFORE `DISTINCT ON (symbol)`: a flatten writes a
  zero-quantity row on the latest date, the filter skips it, and DISTINCT ON
  picks the previous non-zero row -- so a closed position still shows as open.

These run without a database. A Postgres-backed version of the same behaviour
lives in test_positions_book_integration.py (opt-in, needs a database URL).
"""

import re
from datetime import date

import pytest

import algolens.infrastructure.portfolio.repositories as repo_module
from algolens.application.portfolio.ports import PortfolioDetailRows
from algolens.application.portfolio.use_cases import (
    GetStrategyDetail,
    InvalidBook,
    resolve_book_request,
)
from algolens.domain.portfolio.streams import DEFAULT_BOOK, FALLBACK_BOOK, POSITION_BOOKS
from algolens.infrastructure.portfolio.repositories import PostgresPortfolioRepository


def _squash(sql):
    return re.sub(r"\s+", " ", sql).strip()


# --- book request parsing ----------------------------------------------------


def test_books_and_default():
    assert set(POSITION_BOOKS) == {"system", "qt_proposal", "qt"}
    assert DEFAULT_BOOK == "qt"
    assert FALLBACK_BOOK == "system"


def test_absent_book_defaults_to_qt_and_may_fall_back():
    assert resolve_book_request(None) == ("qt", True)


@pytest.mark.parametrize("book", ["system", "qt_proposal", "qt"])
def test_explicit_book_never_falls_back(book):
    assert resolve_book_request(book) == (book, False)


@pytest.mark.parametrize("book", ["", "QT", "benchmark", "qt;drop", " qt"])
def test_unknown_book_is_rejected(book):
    with pytest.raises(InvalidBook):
        resolve_book_request(book)


# --- SQL shape ---------------------------------------------------------------


class RecordingCursor:
    """Records every execute; answers via a handler(sql, params) -> rows."""

    def __init__(self, handler=None):
        self.calls = []
        self.handler = handler or (lambda sql, params: [])
        self._rows = []

    def execute(self, sql, params=None):
        self.calls.append((_squash(sql), params))
        self._rows = list(self.handler(_squash(sql), params))

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_positions_sql_filters_book_and_latest_date_then_drops_zero_outside():
    cursor = RecordingCursor()
    PostgresPortfolioRepository()._fetch_current_positions(
        cursor, "LIVE_TREND_FOLLOWING", "P1", "qt", has_portfolio_type=True
    )

    (sql, params), = cursor.calls
    assert params == ("LIVE_TREND_FOLLOWING", "P1", "qt") * 2

    inner, _, outer = sql.partition(") AS latest_positions")
    assert outer, "expected a derived table named latest_positions"
    # Book predicate on both the row select and the max(date) subquery.
    assert inner.count("portfolio_type = %s") == 2
    assert re.search(r"date = \( SELECT max\(date\) FROM trading\.positions", inner, re.I)
    # The zero-quantity filter must NOT run before DISTINCT ON ...
    assert "quantity" not in inner.split("FROM trading.positions", 1)[1].split("ORDER BY")[0]
    # ... it runs on the outer query, after the latest row per symbol is chosen.
    assert re.search(r"WHERE quantity <> 0", outer)


def test_positions_for_unknown_book_on_unmigrated_db_reads_nothing():
    cursor = RecordingCursor()
    rows = PostgresPortfolioRepository()._fetch_current_positions(
        cursor, "S", "P1", "qt", has_portfolio_type=False
    )
    assert rows == []
    assert cursor.calls == []


def test_positions_for_system_on_unmigrated_db_drops_book_predicate():
    cursor = RecordingCursor()
    PostgresPortfolioRepository()._fetch_current_positions(
        cursor, "S", "P1", "system", has_portfolio_type=False
    )
    (sql, params), = cursor.calls
    assert "portfolio_type" not in sql
    assert params == ("S", "P1") * 2
    assert "WHERE quantity <> 0" in sql.partition(") AS latest_positions")[2]


# --- served-book resolution in fetch_detail_rows -----------------------------


@pytest.fixture(autouse=True)
def _reset_column_cache(monkeypatch):
    monkeypatch.setattr(repo_module, "_has_portfolio_type_cache", None)
    monkeypatch.setattr(repo_module, "_has_portfolio_type_expires_at", 0)


class FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def close(self):
        pass


def _db(books_with_positions, has_column=True):
    """A handler simulating a DB where only `books_with_positions` have rows."""

    def handler(sql, params):
        if "information_schema.columns" in sql:
            return [{"?column?": 1}] if has_column else []
        if "FROM trading.live_results" in sql:
            return [{"date": date(2026, 10, 7)}]
        if sql.startswith("SELECT 1 FROM trading.positions"):
            return [{"?column?": 1}] if params[2] in books_with_positions else []
        if "FROM trading.positions" in sql and "max(date)" in sql:
            book = params[2] if has_column else "system"
            if book in books_with_positions:
                return [{"symbol": f"{book}-SYM", "quantity": 1}]
            return []
        if "FROM trading.equity_curve" in sql and "portfolio_type = %s" in sql:
            book = params[2]
            return [{"timestamp": book, "equity": 1}] if book in books_with_positions else []
        return []

    return handler


def _repo(cursor):
    return PostgresPortfolioRepository(connection_factory=lambda: FakeConn(cursor))


def _book_params(cursor, needle):
    return [p for s, p in cursor.calls if needle in s]


def test_default_qt_falls_back_to_system_when_qt_has_no_rows():
    cursor = RecordingCursor(_db({"system"}))
    rows = _repo(cursor).fetch_detail_rows("S", "P1", book="qt", allow_fallback=True)

    assert rows.book == "system"
    assert rows.fell_back is True
    assert [p["symbol"] for p in rows.positions] == ["system-SYM"]
    # The headline curve follows the served book.
    assert [r["timestamp"] for r in rows.equity_curve] == ["system"]


def test_default_qt_is_served_when_qt_rows_exist():
    cursor = RecordingCursor(_db({"system", "qt"}))
    rows = _repo(cursor).fetch_detail_rows("S", "P1", book="qt", allow_fallback=True)

    assert (rows.book, rows.fell_back) == ("qt", False)
    assert [p["symbol"] for p in rows.positions] == ["qt-SYM"]
    # Not a single positions read used the system book.
    for params in _book_params(cursor, "FROM trading.positions"):
        assert "system" not in params


def test_explicit_qt_never_falls_back():
    cursor = RecordingCursor(_db({"system"}))
    rows = _repo(cursor).fetch_detail_rows("S", "P1", book="qt", allow_fallback=False)

    assert (rows.book, rows.fell_back) == ("qt", False)
    assert rows.positions == []
    assert rows.equity_curve == []


def test_unmigrated_db_default_serves_system_as_fallback():
    cursor = RecordingCursor(_db({"system"}, has_column=False))
    rows = _repo(cursor).fetch_detail_rows("S", "P1", book="qt", allow_fallback=True)

    assert (rows.book, rows.fell_back) == ("system", True)
    assert [p["symbol"] for p in rows.positions] == ["system-SYM"]


# --- use case ----------------------------------------------------------------


class FakeRegistry:
    def get(self, strategy_id):
        if strategy_id != "trendfollowing":
            return None
        return {
            "id": "trendfollowing",
            "name": "Trend Following",
            "description": "",
            "strategy_type": "LIVE_TREND_FOLLOWING",
            "portfolio_id": "P1",
            "initial_equity": 500000.0,
            "managers": [],
        }


LATEST = {
    "date": date(2026, 10, 7),
    "current_portfolio_value": 510000,
    "volatility": 0.1,
    "total_annualized_return": 0.05,
    "daily_return": 0,
    "gross_leverage": 0,
    "net_leverage": 0,
    "portfolio_leverage": 0,
    "margin_posted": 0,
    "equity_to_margin_ratio": 0,
    "margin_cushion": 0,
    "gross_notional": 0,
    "total_unrealized_pnl": 0,
    "total_realized_pnl": 0,
    "total_transaction_costs": 0,
    "cash_available": 0,
}


class FakeReader:
    def __init__(self, served_book, fell_back):
        self.served_book = served_book
        self.fell_back = fell_back
        self.calls = []

    def fetch_detail_rows(self, strategy_type, portfolio_id, book, allow_fallback):
        self.calls.append((strategy_type, portfolio_id, book, allow_fallback))
        return PortfolioDetailRows(
            latest=LATEST,
            equity_curve=[],
            equity_by_stream={},
            positions=[],
            executions=[],
            yesterday_positions=[],
            book=self.served_book,
            fell_back=self.fell_back,
        )


def test_use_case_defaults_to_qt_with_fallback_and_reports_served_book():
    reader = FakeReader("system", True)
    detail = GetStrategyDetail(FakeRegistry(), reader).execute("trendfollowing")

    assert reader.calls == [("LIVE_TREND_FOLLOWING", "P1", "qt", True)]
    assert detail["book"] == "system"
    assert detail["fellBack"] is True
    # Existing fields are untouched.
    for key in ("positions", "historicalData", "equityByStream", "metrics", "lastUpdate"):
        assert key in detail


def test_use_case_explicit_book_disables_fallback():
    reader = FakeReader("qt_proposal", False)
    detail = GetStrategyDetail(FakeRegistry(), reader).execute(
        "trendfollowing", book="qt_proposal"
    )
    assert reader.calls == [("LIVE_TREND_FOLLOWING", "P1", "qt_proposal", False)]
    assert (detail["book"], detail["fellBack"]) == ("qt_proposal", False)


def test_use_case_rejects_invalid_book_before_reading():
    reader = FakeReader("qt", False)
    with pytest.raises(InvalidBook):
        GetStrategyDetail(FakeRegistry(), reader).execute("trendfollowing", book="nope")
    assert reader.calls == []


# --- HTTP --------------------------------------------------------------------


def _set_jwt_cookie(client):
    from flask_jwt_extended import create_access_token

    from app import app

    with app.app_context():
        token = create_access_token(identity="1", additional_claims={"role": "admin"})
    client.set_cookie("access_token_cookie", token)


@pytest.fixture
def http(client, monkeypatch):
    import algolens.adapters.http.portfolio as portfolio_http

    reader = FakeReader("system", True)
    monkeypatch.setattr(
        portfolio_http,
        "create_portfolio_dependencies",
        lambda: (FakeRegistry(), reader),
    )
    _set_jwt_cookie(client)
    return client, reader


def test_http_invalid_book_is_400(http):
    client, reader = http
    response = client.get("/portfolio/strategy/trendfollowing?book=benchmark")
    assert response.status_code == 400
    assert "book" in response.get_json()["error"]
    assert reader.calls == []


def test_http_default_request_reports_fallback(http):
    client, reader = http
    response = client.get("/portfolio/strategy/trendfollowing")
    assert response.status_code == 200
    data = response.get_json()
    assert (data["book"], data["fellBack"]) == ("system", True)
    assert reader.calls == [("LIVE_TREND_FOLLOWING", "P1", "qt", True)]


def test_http_explicit_book_is_passed_without_fallback(http):
    client, reader = http
    response = client.get("/portfolio/strategy/trendfollowing?book=system")
    assert response.status_code == 200
    assert reader.calls == [("LIVE_TREND_FOLLOWING", "P1", "system", False)]
