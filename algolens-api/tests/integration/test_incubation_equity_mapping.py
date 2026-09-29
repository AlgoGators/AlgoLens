"""Issue 84: actual incubation SQL and authenticated GETs on synthetic books."""

import psycopg2
from psycopg2.extras import RealDictCursor
import pytest

from algolens.infrastructure.config.dependencies import create_portfolio_dependencies
from tests.conftest import client, current_users  # noqa: F401  (fixtures; location-independent)
from tests.integration.conftest import claim_schema, require_test_dsn
from tests.test_incubation_routes import _set_jwt_cookie


pytestmark = pytest.mark.integration


def _reader_connection(dsn):
    connection = psycopg2.connect(dsn, cursor_factory=RealDictCursor)
    connection.set_session(readonly=True)
    return connection


@pytest.fixture
def synthetic_books(monkeypatch):
    dsn = require_test_dsn()
    connection = psycopg2.connect(dsn)
    connection.autocommit = True
    try:
        with connection.cursor() as cursor:
            claim_schema(cursor)
            cursor.execute(
                """
                CREATE TABLE trading.strategy_registry (
                    id text PRIMARY KEY, strategy_type text NOT NULL,
                    portfolio_id text NOT NULL, name text NOT NULL,
                    description text, lifecycle text NOT NULL,
                    mock_capital numeric, incubation_started_at timestamptz,
                    sort_order integer NOT NULL
                );
                CREATE TABLE trading.strategy_book_memberships (
                    strategy_id text NOT NULL, portfolio_id text NOT NULL,
                    PRIMARY KEY (strategy_id, portfolio_id)
                );
                CREATE TABLE trading.positions (
                    id integer PRIMARY KEY, strategy_id text NOT NULL,
                    portfolio_id text NOT NULL, updated_at timestamptz NOT NULL,
                    symbol text NOT NULL, quantity numeric NOT NULL,
                    average_price numeric NOT NULL,
                    portfolio_type text NOT NULL DEFAULT 'system'
                );
                CREATE TABLE trading.equity_curve (
                    id integer PRIMARY KEY, strategy_id text NOT NULL,
                    portfolio_id text NOT NULL, timestamp timestamptz NOT NULL,
                    equity numeric NOT NULL,
                    portfolio_type text NOT NULL DEFAULT 'system'
                );
                CREATE TABLE trading.portfolio_assignments (
                    id integer PRIMARY KEY, strategy_id text NOT NULL,
                    from_portfolio_id text, to_portfolio_id text
                );

                INSERT INTO trading.strategy_registry VALUES
                    ('inc_meanrev', 'LIVE_EQUITY_MEAN_REVERSION',
                     'EQUITY_MR_PORTFOLIO', 'Equity mean reversion',
                     'Synthetic equity incubation', 'incubating', 310000,
                     '2026-09-01T00:00:00Z', 1),
                    ('inc_tf_base', 'LIVE_TREND_FOLLOWING',
                     'BASE_PORTFOLIO', 'Trend base', '', 'incubating', 220000,
                     '2026-09-02T00:00:00Z', 2),
                    ('inc_tf_fast', 'LIVE_TREND_FOLLOWING_FAST',
                     'BASE_PORTFOLIO', 'Trend fast', '', 'incubating', 230000,
                     '2026-09-03T00:00:00Z', 3),
                    ('retired_meanrev', 'LIVE_EQUITY_MEAN_REVERSION',
                     'EQUITY_MR_PORTFOLIO', 'Retired control', '', 'retired', NULL,
                     '2026-09-01T00:00:00Z', 4),
                    ('no_start_meanrev', 'LIVE_EQUITY_MEAN_REVERSION',
                     'EQUITY_MR_PORTFOLIO', 'No start control', '', 'incubating', NULL,
                     NULL, 5);
                INSERT INTO trading.strategy_book_memberships VALUES
                    ('inc_meanrev', 'EQUITY_MR_PORTFOLIO'),
                    ('inc_meanrev', 'BASE_PORTFOLIO'),
                    ('inc_tf_base', 'BASE_PORTFOLIO'),
                    ('inc_tf_fast', 'BASE_PORTFOLIO');
                INSERT INTO trading.positions VALUES
                    (1, 'LIVE_EQUITY_MEAN_REVERSION', 'EQUITY_MR_PORTFOLIO',
                     '2026-08-31T12:00:00Z', 'PRE_TARGET', 11, 111),
                    (2, 'LIVE_EQUITY_MEAN_REVERSION', 'EQUITY_MR_PORTFOLIO',
                     '2026-09-01T12:00:00Z', 'EQ_A', 3, 127.25),
                    (3, 'LIVE_EQUITY_MEAN_REVERSION', 'EQUITY_MR_PORTFOLIO',
                     '2026-09-02T14:00:00Z', 'EQ_B', 7, 238.50),
                    (4, 'LIVE_EQUITY_MEAN_REVERSION', 'BASE_PORTFOLIO',
                     '2026-08-30T12:00:00Z', 'PRE_BASE', 13, 313),
                    (5, 'LIVE_EQUITY_MEAN_REVERSION', 'BASE_PORTFOLIO',
                     '2026-09-02T12:00:00Z', 'POST_BASE', 17, 417),
                    (6, 'LIVE_OTHER_ENGINE', 'EQUITY_MR_PORTFOLIO',
                     '2026-09-02T13:00:00Z', 'OTHER_ENGINE', 19, 519);
                -- N5 r2 (F4): the same symbol-days in the qt and qt_proposal
                -- streams, which every non-empty MODEL publication also writes.
                INSERT INTO trading.positions (id, strategy_id, portfolio_id,
                    updated_at, symbol, quantity, average_price, portfolio_type) VALUES
                    (7, 'LIVE_EQUITY_MEAN_REVERSION', 'EQUITY_MR_PORTFOLIO',
                     '2026-09-01T12:00:00Z', 'EQ_A', 4, 127.25, 'qt'),
                    (8, 'LIVE_EQUITY_MEAN_REVERSION', 'EQUITY_MR_PORTFOLIO',
                     '2026-09-01T12:00:00Z', 'EQ_A', 5, 127.25, 'qt_proposal'),
                    (9, 'LIVE_EQUITY_MEAN_REVERSION', 'EQUITY_MR_PORTFOLIO',
                     '2026-09-02T14:00:00Z', 'EQ_B', 8, 238.50, 'qt');
                INSERT INTO trading.equity_curve VALUES
                    (1, 'LIVE_EQUITY_MEAN_REVERSION', 'EQUITY_MR_PORTFOLIO',
                     '2026-08-31T12:00:00Z', 300111),
                    (2, 'LIVE_EQUITY_MEAN_REVERSION', 'EQUITY_MR_PORTFOLIO',
                     '2026-09-01T12:00:00Z', 310125.75),
                    (3, 'LIVE_EQUITY_MEAN_REVERSION', 'EQUITY_MR_PORTFOLIO',
                     '2026-09-02T14:00:00Z', 312430.25),
                    (4, 'LIVE_EQUITY_MEAN_REVERSION', 'BASE_PORTFOLIO',
                     '2026-08-30T12:00:00Z', 700313),
                    (5, 'LIVE_EQUITY_MEAN_REVERSION', 'BASE_PORTFOLIO',
                     '2026-09-02T12:00:00Z', 704417),
                    (6, 'LIVE_OTHER_ENGINE', 'EQUITY_MR_PORTFOLIO',
                     '2026-09-02T13:00:00Z', 805519);
                INSERT INTO trading.equity_curve (id, strategy_id, portfolio_id,
                    timestamp, equity, portfolio_type) VALUES
                    (7, 'LIVE_EQUITY_MEAN_REVERSION', 'EQUITY_MR_PORTFOLIO',
                     '2026-09-01T12:00:00Z', 310999, 'qt'),
                    (8, 'LIVE_EQUITY_MEAN_REVERSION', 'EQUITY_MR_PORTFOLIO',
                     '2026-09-02T14:00:00Z', 399999, 'benchmark');
                INSERT INTO trading.portfolio_assignments VALUES
                    (1, 'inc_tf_base', 'BASE_PORTFOLIO', 'BASE_PORTFOLIO');
                """
            )
    finally:
        connection.close()

    import algolens.adapters.http.portfolio as portfolio_http

    monkeypatch.setattr(
        portfolio_http,
        "create_portfolio_dependencies",
        lambda: create_portfolio_dependencies(
            connection_factory=lambda: _reader_connection(dsn)
        ),
    )
    return dsn


def _snapshot(dsn):
    connection = _reader_connection(dsn)
    try:
        snapshot = {}
        with connection.cursor() as cursor:
            for table in (
                "strategy_registry",
                "strategy_book_memberships",
                "positions",
                "equity_curve",
                "portfolio_assignments",
            ):
                cursor.execute(f"SELECT * FROM trading.{table} ORDER BY 1, 2")
                snapshot[table] = [dict(row) for row in cursor.fetchall()]
        return snapshot
    finally:
        connection.close()


def test_list_and_performance_use_registry_primary_equity_book(
    synthetic_books, client
):
    before = _snapshot(synthetic_books)
    _set_jwt_cookie(client, role="admin")

    listing = client.get("/portfolio/incubation")
    assert listing.status_code == 200
    assert [
        (row["id"], row["strategy_type"], row["portfolio_id"])
        for row in listing.get_json()["incubating_strategies"]
    ] == [
        ("inc_meanrev", "LIVE_EQUITY_MEAN_REVERSION", "EQUITY_MR_PORTFOLIO"),
        ("inc_tf_base", "LIVE_TREND_FOLLOWING", "BASE_PORTFOLIO"),
        ("inc_tf_fast", "LIVE_TREND_FOLLOWING_FAST", "BASE_PORTFOLIO"),
        ("no_start_meanrev", "LIVE_EQUITY_MEAN_REVERSION", "EQUITY_MR_PORTFOLIO"),
    ]

    response = client.get("/portfolio/incubation/inc_meanrev/performance")
    assert response.status_code == 200
    assert response.get_json() == {
        "positions": [
            {"date": "2026-09-01T12:00:00+00:00", "symbol": "EQ_A",
             "quantity": 3.0, "entry_price": 127.25},
            {"date": "2026-09-02T14:00:00+00:00", "symbol": "EQ_B",
             "quantity": 7.0, "entry_price": 238.5},
        ],
        "equity_curve": [
            {"date": "2026-09-01T12:00:00+00:00", "equity": 310125.75},
            {"date": "2026-09-02T14:00:00+00:00", "equity": 312430.25},
        ],
    }
    assert _snapshot(synthetic_books) == before


def test_missing_target_rows_never_fall_back_to_member_base_book(
    synthetic_books, client
):
    connection = psycopg2.connect(synthetic_books)
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM trading.positions WHERE portfolio_id = %s",
                    ("EQUITY_MR_PORTFOLIO",),
                )
                cursor.execute(
                    "DELETE FROM trading.equity_curve WHERE portfolio_id = %s",
                    ("EQUITY_MR_PORTFOLIO",),
                )
    finally:
        connection.close()
    before = _snapshot(synthetic_books)
    _set_jwt_cookie(client, role="admin")

    response = client.get("/portfolio/incubation/inc_meanrev/performance")

    assert response.status_code == 200
    assert response.get_json() == {"positions": [], "equity_curve": []}
    assert _snapshot(synthetic_books) == before


def test_unknown_nonincubating_and_absent_start_have_empty_shape(
    synthetic_books, client
):
    before = _snapshot(synthetic_books)
    _set_jwt_cookie(client, role="admin")

    for registry_id in ("unknown_meanrev", "retired_meanrev", "no_start_meanrev"):
        response = client.get(f"/portfolio/incubation/{registry_id}/performance")
        assert response.status_code == 200
        assert response.get_json() == {"positions": [], "equity_curve": []}

    assert _snapshot(synthetic_books) == before


def test_missing_jwt_and_demoted_current_role_refuse_both_reads(
    synthetic_books, client
):
    before = _snapshot(synthetic_books)
    paths = (
        "/portfolio/incubation",
        "/portfolio/incubation/inc_meanrev/performance",
    )

    for path in paths:
        response = client.get(path)
        assert response.status_code == 401
        assert "EQ_A" not in response.get_data(as_text=True)
        assert "310125.75" not in response.get_data(as_text=True)

    _set_jwt_cookie(
        client, role="admin", current_role="subscriber_individual"
    )
    for path in paths:
        response = client.get(path)
        assert response.status_code == 403
        assert response.get_json() == {"error": "Insufficient permissions"}
        assert "EQ_A" not in response.get_data(as_text=True)
        assert "310125.75" not in response.get_data(as_text=True)

    assert _snapshot(synthetic_books) == before
