"""Risk-envelope publication order against an owned, disposable PostgreSQL schema."""

import json

import pytest

from tests.integration.conftest import claim_schema, require_test_dsn

psycopg2 = pytest.importorskip("psycopg2")
from psycopg2.extras import RealDictCursor

from algolens.infrastructure.portfolio.repositories import PostgresPortfolioRepository


pytestmark = pytest.mark.integration

STRATEGY = "ORDER_TEST"
BOOK = "ORDER_BOOK"
TIED_TIME = "2026-09-21 12:00:00+00"


@pytest.fixture()
def database():
    connection = psycopg2.connect(require_test_dsn())
    connection.autocommit = True
    try:
        with connection.cursor() as cursor:
            claim_schema(cursor)
            cursor.execute(
                """
                CREATE TABLE trading.risk_limits (
                    id BIGSERIAL PRIMARY KEY,
                    strategy_id TEXT NOT NULL,
                    portfolio_id TEXT NOT NULL,
                    limits JSONB NOT NULL,
                    published_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
        yield connection
    finally:
        connection.close()


def publish(connection, limits, *, strategy=STRATEGY, book=BOOK, published_at=TIED_TIME):
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO trading.risk_limits
                (strategy_id, portfolio_id, limits, published_at)
            VALUES (%s, %s, %s::jsonb, %s)
            RETURNING id
            """,
            (strategy, book, json.dumps(limits), published_at),
        )
        return cursor.fetchone()[0]


def fetch_with_cursor(connection):
    repository = PostgresPortfolioRepository()
    with connection.cursor(cursor_factory=RealDictCursor) as cursor:
        return repository._fetch_risk_envelope(cursor, STRATEGY, BOOK)


def test_tied_publication_uses_higher_id(database):
    older = {"max_book_notional": 100}
    newer = {"max_book_notional": 200}
    older_id = publish(database, older)
    newer_id = publish(database, newer)

    assert newer_id > older_id
    assert fetch_with_cursor(database) == newer


def test_newer_timestamp_beats_higher_id(database):
    newer = {"max_book_notional": 300}
    older = {"max_book_notional": 400}
    newer_id = publish(database, newer, published_at="2026-09-22 12:00:00+00")
    older_id = publish(database, older, published_at="2026-09-21 12:00:00+00")

    assert older_id > newer_id
    assert fetch_with_cursor(database) == newer


def test_other_strategy_and_book_publications_do_not_leak(database):
    target = {"max_book_notional": 500}
    publish(database, target)
    publish(
        database, {"max_book_notional": 600}, strategy="OTHER_STRATEGY",
        published_at="2026-09-23 12:00:00+00",
    )
    publish(
        database, {"max_book_notional": 700}, book="OTHER_BOOK",
        published_at="2026-09-24 12:00:00+00",
    )

    assert fetch_with_cursor(database) == target


def test_empty_and_missing_table_return_none(database):
    assert fetch_with_cursor(database) is None
    with database.cursor() as cursor:
        cursor.execute("DROP TABLE trading.risk_limits")
    assert fetch_with_cursor(database) is None


def test_public_fetch_uses_same_order_and_closes_borrowed_wrapper(database):
    publish(database, {"max_book_notional": 800})
    expected = {"max_book_notional": 900}
    publish(database, expected)

    class BorrowedConnection:
        def __init__(self, connection):
            self.connection = connection
            self.close_count = 0

        def cursor(self):
            return self.connection.cursor(cursor_factory=RealDictCursor)

        def close(self):
            self.close_count += 1

    borrowed = BorrowedConnection(database)
    repository = PostgresPortfolioRepository(connection_factory=lambda: borrowed)

    assert repository.fetch_risk_envelope(STRATEGY, BOOK) == expected
    assert borrowed.close_count == 1
    assert database.closed == 0
    with database.cursor() as cursor:
        cursor.execute("SELECT 1")
        assert cursor.fetchone() == (1,)
