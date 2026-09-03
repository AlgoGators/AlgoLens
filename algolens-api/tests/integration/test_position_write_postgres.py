"""The position write path, against a real Postgres.

This file exists because the unit suite was 120+ green while the core QT feature
was completely broken. Three separate defects lived entirely in the gap between
a Python float and a Postgres NUMERIC, and no test with float fixtures can see
any of them:

  * ``Decimal + float`` raised TypeError inside ``evaluate_risk``, so every edit
    returned 500.
  * A quantity-only edit sends no price. The risk check was handed the raw
    proposal, priced the position at zero notional, and passed everything.
  * The INSERT wrote the raw proposal rather than the after-state, wiping
    ``average_price`` off the book on every such edit.

Each assertion below fails against the code as it stood before those fixes.

Skipped unless ``ALGOLENS_TEST_DB`` names a reachable database. CI provides one.
Locally, name a database of its own on the throwaway cluster -- NOT the demo
database. Every test here drops and recreates the ``trading`` schema, so the
fixture refuses to start if that schema already holds tables it did not create.
Pointing this at ``algolens_demo`` once wiped the seeded demo mid-session.

    createdb -h 127.0.0.1 -p 55432 -U algolens algolens_test
    ALGOLENS_TEST_DB=postgresql://algolens@127.0.0.1:55432/algolens_test pytest tests/integration
"""

import os
from decimal import Decimal

import pytest

psycopg2 = pytest.importorskip("psycopg2")
pytest.importorskip("psycopg2.extras")
import psycopg2.extras

from algolens.application.portfolio.ports import RiskAcknowledgementRequired
from algolens.application.portfolio.use_cases import UpsertQtPosition
from algolens.infrastructure.portfolio.repositories import PostgresPortfolioRepository

pytestmark = pytest.mark.integration

STRATEGY_ID = "itest_trend"
STRATEGY_TYPE = "ITEST_TREND_FOLLOWING"
PORTFOLIO_ID = "ITEST_BOOK"
STRATEGY_NAME = "Integration Trend"

# 12 lots at 5280.25 is 63,363 -- inside the cap. 20 lots is 105,605 -- over it.
# The gap between the two is the whole point: a quantity-only edit has to be
# priced from the existing row to land on the wrong side of this number.
ES_PRICE = Decimal("5280.25")
ES_CAP = 70000


def _dsn():
    dsn = os.getenv("ALGOLENS_TEST_DB")
    if not dsn:
        pytest.skip("ALGOLENS_TEST_DB not set; integration tests skipped")
    return dsn


# The fixture marks the schema it builds so it can tell its own leftovers from
# a schema somebody else populated. A crashed run leaves the marker behind; a
# seeded demo, a migration test bed, or production never carries it.
_OWNERSHIP_MARK = "owned by tests/integration; safe to drop"


def _refuse_to_clobber_a_real_schema(cur):
    cur.execute(
        "SELECT obj_description(oid, 'pg_namespace') FROM pg_namespace "
        "WHERE nspname = 'trading'"
    )
    row = cur.fetchone()
    if row is None or row[0] == _OWNERSHIP_MARK:
        return
    cur.execute(
        "SELECT count(*) FROM pg_tables WHERE schemaname = 'trading'"
    )
    tables = cur.fetchone()[0]
    if tables == 0:
        return
    pytest.fail(
        f"ALGOLENS_TEST_DB points at a database whose trading schema already "
        f"holds {tables} table(s) this suite did not create. These tests DROP "
        f"that schema. Name a disposable database instead (see module docstring)."
    )


@pytest.fixture()
def db(monkeypatch):
    """A connection factory pointed at a ``trading`` schema this test owns.

    The application's SQL names ``trading.`` explicitly, so the schema cannot be
    renamed per test; it is dropped and recreated instead. That makes the target
    database disposable by definition, and the guard below is what stops the
    drop from landing on one that is not.
    """
    conn = psycopg2.connect(_dsn())
    conn.autocommit = True
    with conn.cursor() as cur:
        _refuse_to_clobber_a_real_schema(cur)
        cur.execute("DROP SCHEMA IF EXISTS trading CASCADE")
        cur.execute("CREATE SCHEMA trading")
        cur.execute("COMMENT ON SCHEMA trading IS %s", (_OWNERSHIP_MARK,))
        cur.execute(
            """
            CREATE TABLE trading.strategy_registry (
                id TEXT PRIMARY KEY, strategy_type TEXT NOT NULL,
                portfolio_id TEXT NOT NULL, name TEXT NOT NULL,
                description TEXT, initial_equity NUMERIC, managers TEXT[],
                is_active BOOLEAN DEFAULT TRUE, lifecycle TEXT DEFAULT 'live',
                sort_order INT DEFAULT 0, mock_capital NUMERIC,
                incubation_started_at TIMESTAMPTZ,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            CREATE TABLE trading.positions (
                id BIGSERIAL PRIMARY KEY, strategy_id TEXT NOT NULL,
                strategy_name TEXT, portfolio_id TEXT NOT NULL,
                portfolio_type TEXT NOT NULL DEFAULT 'qt',
                date DATE NOT NULL DEFAULT CURRENT_DATE, symbol TEXT NOT NULL,
                quantity NUMERIC NOT NULL, average_price NUMERIC,
                daily_unrealized_pnl NUMERIC DEFAULT 0,
                daily_realized_pnl NUMERIC DEFAULT 0,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            CREATE UNIQUE INDEX positions_book_row_uq ON trading.positions
                (portfolio_id, strategy_id, strategy_name, date, symbol, portfolio_type);
            CREATE TABLE trading.risk_limits (
                id BIGSERIAL PRIMARY KEY, strategy_id TEXT NOT NULL,
                portfolio_id TEXT NOT NULL, limits JSONB NOT NULL,
                published_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            -- As migration 004 defines it, constraints included, so a write
            -- production would refuse is refused here too.
            CREATE TABLE trading.position_overrides (
                id BIGSERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                source_app TEXT NOT NULL
                    CHECK (source_app IN ('algolens', 'manual_db_edit')),
                strategy_id TEXT NOT NULL, symbol TEXT NOT NULL,
                before_state JSONB NOT NULL, after_state JSONB NOT NULL,
                reason TEXT NOT NULL CHECK (length(btrim(reason)) > 0),
                risk_check_result JSONB NOT NULL,
                overrode_risk BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            -- As migration 009 defines them, for the book tests below.
            CREATE TABLE trading.portfolios (
                portfolio_id TEXT PRIMARY KEY, name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '', created_by TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            CREATE TABLE trading.strategy_book_memberships (
                strategy_id TEXT NOT NULL, portfolio_id TEXT NOT NULL,
                added_by TEXT, added_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (strategy_id, portfolio_id)
            );
            CREATE TABLE trading.portfolio_assignments (
                id BIGSERIAL PRIMARY KEY, strategy_id TEXT NOT NULL,
                user_id TEXT, from_portfolio_id TEXT, to_portfolio_id TEXT,
                lifecycle_at_move TEXT, reason TEXT,
                consequences JSONB NOT NULL DEFAULT '[]'::jsonb,
                acknowledged BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT portfolio_assignments_has_a_side
                    CHECK (from_portfolio_id IS NOT NULL OR to_portfolio_id IS NOT NULL)
            );
            """
        )
        cur.execute(
            "INSERT INTO trading.strategy_registry"
            " (id, strategy_type, portfolio_id, name, initial_equity)"
            " VALUES (%s, %s, %s, %s, 500000)",
            (STRATEGY_ID, STRATEGY_TYPE, PORTFOLIO_ID, "Integration Trend"),
        )
        # Written the way the engine writes it: NUMERIC, so it reads back Decimal.
        cur.execute(
            "INSERT INTO trading.positions"
            " (strategy_id, strategy_name, portfolio_id, portfolio_type, symbol,"
            "  quantity, average_price)"
            " VALUES (%s, %s, %s, 'qt', 'ES', 12, %s)",
            (STRATEGY_TYPE, STRATEGY_NAME, PORTFOLIO_ID, ES_PRICE),
        )
        cur.execute(
            "INSERT INTO trading.risk_limits (strategy_id, portfolio_id, limits)"
            " VALUES (%s, %s, %s::jsonb)",
            (STRATEGY_TYPE, PORTFOLIO_ID, '{"max_symbol_notional": {"ES": %d}}' % ES_CAP),
        )
    conn.close()

    def factory():
        c = psycopg2.connect(_dsn(), cursor_factory=psycopg2.extras.RealDictCursor)
        return c

    yield factory

    cleanup = psycopg2.connect(_dsn())
    cleanup.autocommit = True
    with cleanup.cursor() as cur:
        cur.execute("DROP SCHEMA IF EXISTS trading CASCADE")
    cleanup.close()


class _Registry:
    def get(self, strategy_id):
        if strategy_id != STRATEGY_ID:
            return None
        return {
            "id": STRATEGY_ID,
            "strategy_type": STRATEGY_TYPE,
            "portfolio_id": PORTFOLIO_ID,
            "name": "Integration Trend",
            "lifecycle": "live",
        }


def _use_case(db):
    return UpsertQtPosition(_Registry(), PostgresPortfolioRepository(connection_factory=db))


def _row(db, symbol="ES"):
    conn = db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT quantity, average_price FROM trading.positions"
                " WHERE symbol = %s AND portfolio_type = 'qt'"
                " ORDER BY updated_at DESC LIMIT 1",
                (symbol,),
            )
            return cur.fetchone()
    finally:
        conn.close()


def test_a_quantity_only_edit_is_priced_from_the_book_and_trips_the_cap(db):
    """The single most common edit, end to end.

    Before the fixes this raised TypeError (Decimal + float). After only a
    partial fix it returned 201 with passed=True, because the blank price made
    the position worth nothing.
    """
    with pytest.raises(RiskAcknowledgementRequired) as exc:
        _use_case(db).execute(
            {
                "strategy_id": STRATEGY_ID,
                "symbol": "ES",
                "quantity": 20,
                "reason": "integration: quantity only",
            },
            user_id="1",
        )

    verdict = exc.value.verdict
    assert verdict["evaluated"] is True
    assert verdict["passed"] is False
    breach = verdict["breaches"][0]
    assert breach["limit"] == "max_symbol_notional"
    # 20 * 5280.25, priced from the existing row rather than treated as zero.
    assert breach["actual"] == pytest.approx(105605.0)

    # Nothing was written: the gate stopped before the write.
    assert float(_row(db)["quantity"]) == 12.0


def test_acknowledging_writes_the_position_and_keeps_the_existing_price(db):
    result = _use_case(db).execute(
        {
            "strategy_id": STRATEGY_ID,
            "symbol": "ES",
            "quantity": 20,
            "reason": "integration: acknowledged",
        },
        user_id="1",
        acknowledge_risk=True,
    )

    # The response must carry numbers, not the strings jsonify makes of Decimal.
    assert isinstance(result["position"]["quantity"], float)
    assert isinstance(result["position"]["average_price"], float)

    row = _row(db)
    assert float(row["quantity"]) == 20.0
    # The blank price meant "keep it". Writing the raw proposal wiped it.
    assert float(row["average_price"]) == pytest.approx(float(ES_PRICE))


def test_the_audit_row_records_the_override_and_the_carried_price(db):
    _use_case(db).execute(
        {
            "strategy_id": STRATEGY_ID,
            "symbol": "ES",
            "quantity": 20,
            "reason": "integration: audit",
        },
        user_id="42",
        acknowledge_risk=True,
    )

    conn = db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT user_id, source_app, overrode_risk, before_state, after_state,"
                "       risk_check_result"
                " FROM trading.position_overrides ORDER BY created_at DESC LIMIT 1"
            )
            audit = cur.fetchone()
    finally:
        conn.close()

    # INTEGER in the real schema, so it comes back as one.
    assert audit["user_id"] == 42
    assert audit["source_app"] == "algolens"
    assert audit["overrode_risk"] is True
    assert audit["risk_check_result"]["passed"] is False
    assert float(audit["before_state"]["quantity"]) == 12.0
    assert float(audit["after_state"]["quantity"]) == 20.0
    # The price survives into both sides of the record.
    assert float(audit["after_state"]["average_price"]) == pytest.approx(float(ES_PRICE))


def test_an_edit_inside_the_cap_needs_no_acknowledgement(db):
    result = _use_case(db).execute(
        {
            "strategy_id": STRATEGY_ID,
            "symbol": "ES",
            "quantity": 5,
            "reason": "integration: within cap",
        },
        user_id="1",
    )
    assert result["risk_check"]["evaluated"] is True
    assert result["risk_check"]["passed"] is True
    assert float(_row(db)["quantity"]) == 5.0


# ---------------------------------------------------------------------------
# Books. These need the real tables because the rules live partly in SQL: what
# "in this book" means to delete_book, and where the primary goes on removal.
# ---------------------------------------------------------------------------

from algolens.application.portfolio.ports import BookNotEmpty  # noqa: E402
from algolens.domain.portfolio.portfolio_assignment import build_membership_audit  # noqa: E402
from algolens.infrastructure.portfolio.strategy_registry import PostgresStrategyRegistry  # noqa: E402


def _put_in_two_books(db, primary):
    conn = db()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO trading.portfolios (portfolio_id, name) VALUES (%s, %s)",
                    ("MACRO_BOOK", "Macro"),
                )
                cur.executemany(
                    "INSERT INTO trading.strategy_book_memberships (strategy_id, portfolio_id)"
                    " VALUES (%s, %s)",
                    [(STRATEGY_ID, primary), (STRATEGY_ID, "MACRO_BOOK")],
                )
    finally:
        conn.close()


def test_a_book_holding_a_non_primary_member_cannot_be_deleted(db):
    registry = PostgresStrategyRegistry(connection_factory=db)
    primary = registry.get_any(STRATEGY_ID)["portfolio_id"]
    assert primary != "MACRO_BOOK"
    _put_in_two_books(db, primary)

    # The strategy's primary is elsewhere. It is still IN MACRO_BOOK, with rows
    # keyed on that pairing; the first version only counted primaries and
    # would have deleted the book out from under them.
    with pytest.raises(BookNotEmpty):
        registry.delete_book("MACRO_BOOK")
    assert "MACRO_BOOK" in registry.books_for_strategy(STRATEGY_ID)


def test_removing_the_primary_book_repoints_it_and_says_so(db):
    registry = PostgresStrategyRegistry(connection_factory=db)
    strategy = registry.get_any(STRATEGY_ID)
    primary = strategy["portfolio_id"]
    _put_in_two_books(db, primary)

    audit = build_membership_audit(
        strategy, primary, "remove", user_id="1", reason="consolidating", acknowledged=True
    )
    outcome = registry.remove_membership(STRATEGY_ID, primary, audit)

    assert outcome["primary_portfolio_id"] == "MACRO_BOOK"
    assert registry.get_any(STRATEGY_ID)["portfolio_id"] == "MACRO_BOOK"
    assert registry.books_for_strategy(STRATEGY_ID) == ["MACRO_BOOK"]


def test_removing_a_non_primary_book_leaves_the_primary_alone(db):
    registry = PostgresStrategyRegistry(connection_factory=db)
    strategy = registry.get_any(STRATEGY_ID)
    primary = strategy["portfolio_id"]
    _put_in_two_books(db, primary)

    audit = build_membership_audit(
        strategy, "MACRO_BOOK", "remove", user_id="1", reason="done", acknowledged=True
    )
    outcome = registry.remove_membership(STRATEGY_ID, "MACRO_BOOK", audit)

    assert outcome["primary_portfolio_id"] is None
    assert registry.get_any(STRATEGY_ID)["portfolio_id"] == primary
