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

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from decimal import Decimal
from threading import Barrier

import pytest

from tests.integration.conftest import claim_schema, require_test_dsn

psycopg2 = pytest.importorskip("psycopg2")
pytest.importorskip("psycopg2.extras")
import psycopg2.extras

from algolens.application.portfolio.ports import RiskAcknowledgementRequired
from algolens.application.portfolio.use_cases import UpsertQtPosition
from algolens.domain.portfolio.position_edit import PositionValidationError
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
# In CONTRACTS, which is the unit the engine publishes caps in. This used to
# be a dollar cap under a key trade-ngin never writes, so these tests proved
# the gate worked against a limit that does not exist in production.
ES_CAP = 10


def _dsn():
    return require_test_dsn()


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
        claim_schema(cur)
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
            -- The shape trade-ngin ships (its own test_001_migration.sh
            -- baseline, plus migrations 001 and 003). The looser invention this
            -- replaced is what let a write path that cannot insert into the
            -- real table pass every test in this file.
            CREATE TABLE trading.positions (
                symbol VARCHAR NOT NULL, quantity NUMERIC NOT NULL,
                average_price NUMERIC NOT NULL,
                daily_unrealized_pnl NUMERIC NOT NULL,
                daily_realized_pnl NUMERIC NOT NULL,
                last_update TIMESTAMPTZ NOT NULL,
                updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                strategy_id VARCHAR NOT NULL, strategy_name VARCHAR NOT NULL,
                date DATE NOT NULL, portfolio_id VARCHAR NOT NULL,
                portfolio_type TEXT NOT NULL DEFAULT 'system',
                CONSTRAINT positions_portfolio_type_check
                    CHECK (portfolio_type IN ('system','qt','benchmark',
                                              'benchmark_rebench','benchmark_frozen_shadow')),
                CONSTRAINT positions_pkey PRIMARY KEY
                    (portfolio_id, strategy_id, strategy_name, date, symbol, portfolio_type)
            );
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
            -- Migration 012 is deliberately additive: legacy rows stay
            -- immutable and unscoped, while every new AlgoLens write must
            -- name its book.  Keep this disposable fixture at that exact
            -- post-migration contract; without the column all current writer
            -- tests fail before they exercise their intended behavior.
            ALTER TABLE trading.position_overrides
                ADD COLUMN portfolio_id TEXT;
            ALTER TABLE trading.position_overrides
                ADD CONSTRAINT position_overrides_new_rows_require_portfolio
                CHECK (portfolio_id IS NOT NULL) NOT VALID;
            CREATE TABLE trading.position_override_legacy_scopes (
                override_id BIGINT PRIMARY KEY
                    REFERENCES trading.position_overrides(id),
                portfolio_id TEXT NOT NULL,
                inference_basis JSONB NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            CREATE INDEX idx_position_overrides_portfolio_strategy_created
                ON trading.position_overrides
                   (portfolio_id, strategy_id, created_at DESC);
            CREATE RULE position_overrides_no_update AS
                ON UPDATE TO trading.position_overrides DO INSTEAD NOTHING;
            CREATE RULE position_overrides_no_delete AS
                ON DELETE TO trading.position_overrides DO INSTEAD NOTHING;
            CREATE RULE position_override_legacy_scopes_no_update AS
                ON UPDATE TO trading.position_override_legacy_scopes DO INSTEAD NOTHING;
            CREATE RULE position_override_legacy_scopes_no_delete AS
                ON DELETE TO trading.position_override_legacy_scopes DO INSTEAD NOTHING;
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
            "  quantity, average_price, daily_unrealized_pnl, daily_realized_pnl,"
            "  date, last_update)"
            " VALUES (%s, %s, %s, 'qt', 'ES', 12, %s, 0, 0, CURRENT_DATE, now())",
            (STRATEGY_TYPE, STRATEGY_NAME, PORTFOLIO_ID, ES_PRICE),
        )
        cur.execute(
            "INSERT INTO trading.risk_limits (strategy_id, portfolio_id, limits)"
            " VALUES (%s, %s, %s::jsonb)",
            (STRATEGY_TYPE, PORTFOLIO_ID,
             '{"max_symbol_position_contracts": {"ES": %d}}' % ES_CAP),
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
    assert breach["limit"] == "max_symbol_position_contracts"
    # 20 contracts against a cap of 10. The unit is contracts, because that is
    # the unit the engine publishes the cap in.
    assert breach["actual"] == pytest.approx(20.0)
    assert breach["limit_value"] == pytest.approx(float(ES_CAP))

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


def test_concurrent_different_symbol_edits_recheck_the_serialized_book(db):
    """Only one unacknowledged edit may cross a book-wide position-count cap."""
    conn = db()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE trading.positions SET quantity = 0 "
                    "WHERE strategy_id = %s AND portfolio_id = %s AND symbol = 'ES'",
                    (STRATEGY_TYPE, PORTFOLIO_ID),
                )
                cur.execute(
                    """
                    INSERT INTO trading.positions
                        (strategy_id, strategy_name, portfolio_id, portfolio_type,
                         symbol, quantity, average_price, daily_unrealized_pnl,
                         daily_realized_pnl, date, last_update)
                    VALUES (%s, %s, %s, 'qt', 'NQ', 0, 100, 0, 0,
                            CURRENT_DATE, now())
                    """,
                    (STRATEGY_TYPE, STRATEGY_NAME, PORTFOLIO_ID),
                )
                cur.execute(
                    "UPDATE trading.risk_limits "
                    "SET limits = '{\"max_position_count\": 1}'::jsonb "
                    "WHERE strategy_id = %s AND portfolio_id = %s",
                    (STRATEGY_TYPE, PORTFOLIO_ID),
                )
    finally:
        conn.close()
    start = Barrier(2)
    stale_read = Barrier(2)

    class SynchronizeOldReadRepository(PostgresPortfolioRepository):
        def fetch_qt_book(self, strategy_type, portfolio_id):
            book = super().fetch_qt_book(strategy_type, portfolio_id)
            stale_read.wait(timeout=5)
            return book

    def edit(symbol):
        start.wait(timeout=5)
        use_case = UpsertQtPosition(
            _Registry(), SynchronizeOldReadRepository(connection_factory=db)
        )
        try:
            result = use_case.execute(
                {
                    "strategy_id": STRATEGY_ID,
                    "strategy_name": STRATEGY_NAME,
                    "symbol": symbol,
                    "quantity": 1,
                    "average_price": 100,
                    "reason": f"concurrent open {symbol}",
                },
                user_id="1",
            )
            return "written", result["risk_check"]
        except RiskAcknowledgementRequired as exc:
            return "refused", exc.verdict

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(edit, ("ES", "NQ")))

    assert sorted(status for status, _ in outcomes) == ["refused", "written"]
    refused = next(verdict for status, verdict in outcomes if status == "refused")
    assert refused["passed"] is False
    assert refused["breaches"] == [
        {
            "limit": "max_position_count",
            "limit_value": 1.0,
            "actual": 2,
            "message": "2 open positions exceeds the cap of 1",
        }
    ]

    conn = db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) AS count FROM trading.positions "
                "WHERE strategy_id = %s AND portfolio_id = %s "
                "AND portfolio_type = 'qt' AND date = CURRENT_DATE "
                "AND quantity <> 0",
                (STRATEGY_TYPE, PORTFOLIO_ID),
            )
            assert cur.fetchone()["count"] == 1
            cur.execute("SELECT count(*) AS count FROM trading.position_overrides")
            assert cur.fetchone()["count"] == 1
    finally:
        conn.close()


def test_write_revalidates_current_book_membership_inside_its_transaction(db):
    """A stale registry read cannot authorize a write after membership changed."""
    conn = db()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE trading.strategy_registry SET portfolio_id = 'OTHER_BOOK' "
                    "WHERE id = %s",
                    (STRATEGY_ID,),
                )
    finally:
        conn.close()

    with pytest.raises(PositionValidationError) as excinfo:
        _use_case(db).execute(
            {
                "strategy_id": STRATEGY_ID,
                "strategy_name": STRATEGY_NAME,
                "symbol": "ES",
                "quantity": 5,
                "reason": "stale membership must not authorize this edit",
            },
            user_id="1",
        )

    assert excinfo.value.code == "not_a_member_of_book"
    conn = db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) AS count FROM trading.position_overrides")
            assert cur.fetchone()["count"] == 0
    finally:
        conn.close()


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


def test_membership_removal_waits_for_the_same_book_transaction_lock(db):
    registry = PostgresStrategyRegistry(connection_factory=db)
    strategy = registry.get_any(STRATEGY_ID)
    primary = strategy["portfolio_id"]
    _put_in_two_books(db, primary)
    audit = build_membership_audit(
        strategy,
        primary,
        "remove",
        user_id="1",
        reason="serialize against a concurrent edit",
        acknowledged=True,
    )

    control = db()
    future = None
    try:
        with control.cursor() as cur:
            cur.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"algolens:qt-book:{primary}",),
            )
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                registry.remove_membership, STRATEGY_ID, primary, audit
            )
            with pytest.raises(FutureTimeoutError):
                future.result(timeout=0.25)
            control.rollback()
            outcome = future.result(timeout=5)
    finally:
        control.rollback()
        control.close()

    assert outcome["primary_portfolio_id"] == "MACRO_BOOK"
