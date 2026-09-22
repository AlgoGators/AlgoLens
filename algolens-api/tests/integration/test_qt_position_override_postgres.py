"""QT position overrides against migration-012-shaped Postgres tables.

The unit suite cannot prove a PostgreSQL transaction rolls back both writes, or
that the audit history stays segregated after ``portfolio_id`` became required.
This module uses only ``ALGOLENS_TEST_DB`` and the shared destructive-schema
guard; it never connects to a deployed database.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier, Event
from time import monotonic

import pytest

from tests.integration.conftest import claim_schema, require_test_dsn

psycopg2 = pytest.importorskip("psycopg2")
pytest.importorskip("psycopg2.extras")
from psycopg2.extras import RealDictCursor

from algolens.infrastructure.portfolio.repositories import PostgresPortfolioRepository


pytestmark = pytest.mark.integration

STRATEGY = "ITEST_QT"
BOOK_A = "BOOK_A"
BOOK_B = "BOOK_B"
SYMBOL = "ES"


@pytest.fixture()
def test_dsn():
    return require_test_dsn()


@pytest.fixture()
def repository(test_dsn):
    dsn = test_dsn
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    with conn.cursor() as cursor:
        claim_schema(cursor)
        cursor.execute(
            """
            CREATE TABLE trading.strategy_registry (
                id TEXT PRIMARY KEY, strategy_type TEXT NOT NULL,
                portfolio_id TEXT NOT NULL,
                lifecycle TEXT NOT NULL DEFAULT 'live'
            );
            CREATE TABLE trading.strategy_book_memberships (
                strategy_id TEXT NOT NULL, portfolio_id TEXT NOT NULL,
                PRIMARY KEY (strategy_id, portfolio_id)
            );
            CREATE TABLE trading.positions (
                symbol TEXT NOT NULL, quantity NUMERIC NOT NULL,
                average_price NUMERIC NOT NULL,
                daily_unrealized_pnl NUMERIC NOT NULL,
                daily_realized_pnl NUMERIC NOT NULL,
                last_update TIMESTAMPTZ NOT NULL,
                updated_at TIMESTAMPTZ DEFAULT now(),
                strategy_id TEXT NOT NULL, strategy_name TEXT NOT NULL,
                date DATE NOT NULL, portfolio_id TEXT NOT NULL,
                portfolio_type TEXT NOT NULL,
                PRIMARY KEY (portfolio_id, strategy_id, strategy_name, date, symbol, portfolio_type)
            );
            -- Migration 004 followed by migration 012, including the
            -- append-only rules that production uses for audit evidence.
            CREATE TABLE trading.position_overrides (
                id BIGSERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                source_app TEXT NOT NULL CHECK (source_app IN ('algolens', 'manual_db_edit')),
                strategy_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                before_state JSONB NOT NULL,
                after_state JSONB NOT NULL,
                reason TEXT NOT NULL CHECK (length(btrim(reason)) > 0),
                risk_check_result JSONB NOT NULL,
                overrode_risk BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                portfolio_id TEXT
            );
            ALTER TABLE trading.position_overrides
                ADD CONSTRAINT position_overrides_new_rows_require_portfolio
                CHECK (portfolio_id IS NOT NULL) NOT VALID;
            CREATE TABLE trading.position_override_legacy_scopes (
                override_id BIGINT PRIMARY KEY REFERENCES trading.position_overrides(id),
                portfolio_id TEXT NOT NULL,
                inference_basis JSONB NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            CREATE INDEX idx_position_overrides_portfolio_strategy_created
                ON trading.position_overrides (portfolio_id, strategy_id, created_at DESC);
            CREATE RULE position_overrides_no_update AS
                ON UPDATE TO trading.position_overrides DO INSTEAD NOTHING;
            CREATE RULE position_overrides_no_delete AS
                ON DELETE TO trading.position_overrides DO INSTEAD NOTHING;
            CREATE RULE position_override_legacy_scopes_no_update AS
                ON UPDATE TO trading.position_override_legacy_scopes DO INSTEAD NOTHING;
            CREATE RULE position_override_legacy_scopes_no_delete AS
                ON DELETE TO trading.position_override_legacy_scopes DO INSTEAD NOTHING;
            """
        )
        cursor.execute(
            "INSERT INTO trading.strategy_registry (id, strategy_type, portfolio_id) "
            "VALUES (%s, %s, %s)",
            (STRATEGY, STRATEGY, BOOK_A),
        )
        cursor.executemany(
            "INSERT INTO trading.strategy_book_memberships (strategy_id, portfolio_id) "
            "VALUES (%s, %s)",
            ((STRATEGY, BOOK_A), (STRATEGY, BOOK_B)),
        )
        cursor.executemany(
            """
            INSERT INTO trading.positions
                (portfolio_id, strategy_id, strategy_name, date, symbol, portfolio_type,
                 quantity, average_price, daily_unrealized_pnl, daily_realized_pnl,
                 last_update)
            VALUES (%s, %s, 'QT Integration', %s, %s, 'qt', %s, 100, 0, 0, now())
            """,
            [(BOOK_A, STRATEGY, date.today(), SYMBOL, 5),
             (BOOK_B, STRATEGY, date.today(), SYMBOL, 9)],
        )
    conn.close()

    yield PostgresPortfolioRepository(
        connection_factory=lambda: psycopg2.connect(dsn, cursor_factory=RealDictCursor)
    )

    cleanup = psycopg2.connect(dsn)
    cleanup.autocommit = True
    with cleanup.cursor() as cursor:
        cursor.execute("DROP SCHEMA IF EXISTS trading CASCADE")
    cleanup.close()


def _write(repository, book, quantity, reason, symbol=SYMBOL):
    return repository.write_qt_position(
        strategy_type=STRATEGY,
        portfolio_id=book,
        normalized={
            "strategy_id": STRATEGY,
            "symbol": symbol,
            "quantity": quantity,
            "average_price": 100,
            "reason": reason,
        },
        user_id=42,
        risk_check=lambda *_: {
            "evaluated": True,
            "passed": True,
            "breaches": [],
            "checked": [],
        },
    )


def _position_quantity(repository, book):
    conn = repository.connection_factory()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT quantity FROM trading.positions
                WHERE portfolio_id = %s AND strategy_id = %s AND symbol = %s
                  AND portfolio_type = 'qt' AND date = %s
                """,
                (book, STRATEGY, SYMBOL, date.today()),
            )
            return float(cursor.fetchone()["quantity"])
    finally:
        conn.close()


def test_zero_close_writes_an_audited_override_only_in_its_book(repository):
    result = _write(repository, BOOK_A, 0, "close the desk position")

    assert float(result["position"]["quantity"]) == 0.0
    assert _position_quantity(repository, BOOK_A) == 0.0
    assert _position_quantity(repository, BOOK_B) == 9.0

    own_history = repository.fetch_overrides(STRATEGY, BOOK_A)
    other_history = repository.fetch_overrides(STRATEGY, BOOK_B)
    assert len(own_history) == 1
    assert other_history == []
    assert own_history[0]["id"] == result["override_id"]
    assert float(own_history[0]["after_state"]["quantity"]) == 0.0


def test_audit_insert_failure_rolls_back_the_position_write(repository):
    conn = repository.connection_factory()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                ALTER TABLE trading.position_overrides
                    ADD CONSTRAINT reject_rollback_probe
                    CHECK (reason <> 'force audit failure')
                """
            )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(psycopg2.IntegrityError):
        _write(repository, BOOK_A, 11, "force audit failure")

    assert _position_quantity(repository, BOOK_A) == 5.0
    assert repository.fetch_overrides(STRATEGY, BOOK_A) == []


def test_audit_insert_failure_rolls_back_a_new_identity_reservation(repository):
    """The insert-or-lock reservation must not survive without its audit row."""
    conn = repository.connection_factory()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                ALTER TABLE trading.position_overrides
                    ADD CONSTRAINT reject_new_identity_rollback_probe
                    CHECK (reason <> 'force new identity audit failure')
                """
            )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(psycopg2.IntegrityError):
        _write(repository, BOOK_A, 11, "force new identity audit failure", "NQ")

    conn = repository.connection_factory()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT count(*) AS count FROM trading.positions
                WHERE portfolio_id = %s AND strategy_id = %s AND symbol = 'NQ'
                  AND portfolio_type = 'qt' AND date = %s
                """,
                (BOOK_A, STRATEGY, date.today()),
            )
            assert cursor.fetchone()["count"] == 0
    finally:
        conn.close()
    assert repository.fetch_overrides(STRATEGY, BOOK_A) == []


def _wait_until_writers_are_serialized(control_connection):
    """Observe one trigger waiter and one registry-row waiter without sleeping."""
    deadline = monotonic() + 5
    waiter = Event()
    while monotonic() < deadline:
        with control_connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    count(*) FILTER (
                        WHERE locks.locktype = 'advisory' AND NOT locks.granted
                    ) AS trigger_waiters,
                    count(*) FILTER (
                        WHERE locks.locktype = 'transactionid' AND NOT locks.granted
                    ) AS registry_waiters
                FROM pg_locks AS locks
                JOIN pg_stat_activity AS activity USING (pid)
                WHERE activity.application_name = 'algolens-qt-contention-test'
                """
            )
            waiters = cursor.fetchone()
            if waiters["trigger_waiters"] == 1 and waiters["registry_waiters"] == 1:
                return
        waiter.wait(0.01)
    pytest.fail("writers did not serialize at the registry row before INSERT")


def test_concurrent_new_identity_preserves_the_second_audit_before_state(
    repository, test_dsn
):
    """The registry-row lock must serialize writers before either snapshot lies.

    The trigger blocks the first INSERT on a session lock while the second
    transaction waits for that writer's registry-row lock. Releasing the
    trigger lets the first writer commit; only then may the second writer
    acquire eligibility and snapshot the committed position as before_state.
    """
    lock_key = 812_045_117
    setup = repository.connection_factory()
    try:
        with setup.cursor() as cursor:
            cursor.execute(
                """
                CREATE FUNCTION trading.block_new_nq_position() RETURNS trigger
                LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.symbol = 'NQ' THEN
                        PERFORM pg_advisory_xact_lock(812045117);
                    END IF;
                    RETURN NEW;
                END;
                $$;
                CREATE TRIGGER block_new_nq_position
                    BEFORE INSERT ON trading.positions
                    FOR EACH ROW EXECUTE FUNCTION trading.block_new_nq_position();
                """
            )
        setup.commit()
    finally:
        setup.close()

    control = psycopg2.connect(test_dsn, cursor_factory=RealDictCursor)
    # The controller observes worker sessions through pg_stat_activity. Each
    # poll needs a fresh READ COMMITTED snapshot; a session advisory lock stays
    # held in autocommit mode until it is explicitly released below.
    control.autocommit = True
    try:
        with control.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_lock(%s)", (lock_key,))

        def contention_connection():
            connection = psycopg2.connect(
                test_dsn,
                cursor_factory=RealDictCursor,
                application_name="algolens-qt-contention-test",
            )
            # If a harness regression skips the controller release, surface a
            # bounded database error rather than leaving an integration worker
            # blocked indefinitely. The repository still owns an ordinary
            # transaction for the position/audit pair.
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '5s'")
                cursor.execute("SET statement_timeout = '10s'")
            connection.commit()
            return connection

        contender = PostgresPortfolioRepository(connection_factory=contention_connection)
        started = Barrier(3)

        def write(quantity):
            started.wait()
            return _write(contender, BOOK_A, quantity, f"concurrent write {quantity}", "NQ")

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(write, 13)
            second = pool.submit(write, 17)
            try:
                started.wait()
                _wait_until_writers_are_serialized(control)
            finally:
                # A failing wait must release the sessions before the executor
                # joins them. Otherwise its workers remain blocked forever in
                # the trigger and hide the actual assertion failure.
                with control.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_unlock(%s)", (lock_key,))
            first.result(timeout=5)
            second.result(timeout=5)

        entries = [
            entry
            for entry in repository.fetch_overrides(STRATEGY, BOOK_A)
            if entry["symbol"] == "NQ"
        ]
        assert len(entries) == 2
        # Exactly one transaction created the position. The other must have
        # waited on lifecycle eligibility and audited the winning row as before.
        before_quantities = [entry["before_state"].get("quantity") for entry in entries]
        assert before_quantities.count(None) == 1
        assert {float(quantity) for quantity in before_quantities if quantity is not None} <= {
            13.0,
            17.0,
        }
        assert all(float(entry["after_state"]["average_price"]) == 100.0 for entry in entries)
    finally:
        control.close()
