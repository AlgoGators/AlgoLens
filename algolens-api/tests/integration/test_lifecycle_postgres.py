"""Real-transaction coverage for lifecycle closure and position eligibility."""

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from datetime import date

import pytest

from tests.integration.conftest import claim_schema, require_test_dsn

psycopg2 = pytest.importorskip("psycopg2")
pytest.importorskip("psycopg2.extras")
import psycopg2.extras

from algolens.application.portfolio.ports import IncubationError, IncubationStorageError
from algolens.domain.portfolio.position_edit import PositionValidationError
from algolens.infrastructure.portfolio.repositories import PostgresPortfolioRepository
from algolens.infrastructure.portfolio.strategy_registry import PostgresStrategyRegistry

pytestmark = pytest.mark.integration

STRATEGY_ID = "lifecycle_trend"
STRATEGY_TYPE = "LIFECYCLE_TREND"
BOOK_A = "BOOK_A"
BOOK_B = "BOOK_B"
ENGINE_A = "Engine A"


@pytest.fixture()
def db():
    dsn = require_test_dsn()
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    with conn.cursor() as cursor:
        claim_schema(cursor)
        cursor.execute(
            """
            CREATE TABLE trading.strategy_registry (
                id TEXT PRIMARY KEY, strategy_type TEXT NOT NULL,
                portfolio_id TEXT NOT NULL, name TEXT NOT NULL,
                lifecycle TEXT NOT NULL DEFAULT 'live', mock_capital NUMERIC,
                incubation_started_at TIMESTAMPTZ,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            -- Lifecycle tests target the explicitly disabled legacy writer.
            CREATE TABLE trading.qt_workflow_capabilities (
                book_id TEXT PRIMARY KEY, enabled BOOLEAN NOT NULL,
                version INTEGER NOT NULL CHECK (version > 0)
            );
            INSERT INTO trading.qt_workflow_capabilities
                VALUES ('BOOK_A', false, 1), ('BOOK_B', false, 1);
            CREATE TABLE trading.strategy_lifecycle_log (
                id BIGSERIAL PRIMARY KEY,
                strategy_id TEXT NOT NULL REFERENCES trading.strategy_registry(id),
                before_state TEXT NOT NULL, after_state TEXT NOT NULL,
                reason TEXT NOT NULL CHECK (reason <> 'force audit failure'),
                user_id TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            CREATE TABLE trading.strategy_book_memberships (
                strategy_id TEXT NOT NULL, portfolio_id TEXT NOT NULL,
                PRIMARY KEY (strategy_id, portfolio_id)
            );
            CREATE TABLE trading.portfolio_assignments (
                id BIGSERIAL PRIMARY KEY, strategy_id TEXT NOT NULL,
                user_id TEXT, from_portfolio_id TEXT, to_portfolio_id TEXT,
                lifecycle_at_move TEXT, reason TEXT,
                consequences JSONB NOT NULL DEFAULT '[]'::jsonb,
                acknowledged BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            CREATE TABLE trading.positions (
                symbol TEXT NOT NULL, quantity NUMERIC NOT NULL,
                average_price NUMERIC NOT NULL,
                daily_unrealized_pnl NUMERIC NOT NULL DEFAULT 0,
                daily_realized_pnl NUMERIC NOT NULL DEFAULT 0,
                last_update TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                strategy_id TEXT NOT NULL, strategy_name TEXT NOT NULL,
                date DATE NOT NULL, portfolio_id TEXT NOT NULL,
                portfolio_type TEXT NOT NULL,
                PRIMARY KEY
                    (portfolio_id, strategy_id, strategy_name, date, symbol, portfolio_type)
            );
            CREATE TABLE trading.risk_limits (
                id BIGSERIAL PRIMARY KEY, strategy_id TEXT NOT NULL,
                portfolio_id TEXT NOT NULL, limits JSONB NOT NULL,
                published_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            CREATE TABLE trading.position_overrides (
                id BIGSERIAL PRIMARY KEY, portfolio_id TEXT NOT NULL,
                user_id INTEGER NOT NULL, source_app TEXT NOT NULL,
                strategy_id TEXT NOT NULL, symbol TEXT NOT NULL,
                before_state JSONB NOT NULL, after_state JSONB NOT NULL,
                reason TEXT NOT NULL, risk_check_result JSONB NOT NULL,
                overrode_risk BOOLEAN NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            CREATE TABLE trading.position_override_legacy_scopes (
                override_id BIGINT PRIMARY KEY, portfolio_id TEXT NOT NULL
            );
            INSERT INTO trading.strategy_registry
                (id, strategy_type, portfolio_id, name)
            VALUES ('lifecycle_trend', 'LIFECYCLE_TREND', 'BOOK_A', 'Trend');
            INSERT INTO trading.strategy_book_memberships (strategy_id, portfolio_id)
            VALUES ('lifecycle_trend', 'BOOK_A'), ('lifecycle_trend', 'BOOK_B');
            """
        )
    conn.close()

    def factory():
        return psycopg2.connect(
            dsn, cursor_factory=psycopg2.extras.RealDictCursor
        )

    yield factory

    cleanup = psycopg2.connect(dsn)
    cleanup.autocommit = True
    with cleanup.cursor() as cursor:
        cursor.execute("DROP SCHEMA IF EXISTS trading CASCADE")
    cleanup.close()


def _repo(db):
    return PostgresPortfolioRepository(connection_factory=db)


def _position(db, *, book=BOOK_A, stream="qt", symbol="ES", quantity=0,
              strategy_name=ENGINE_A, position_date=None):
    conn = db()
    try:
        with conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO trading.positions
                        (portfolio_id, strategy_id, strategy_name, date, symbol,
                         portfolio_type, quantity, average_price)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 100)
                    """,
                    (
                        book,
                        STRATEGY_TYPE,
                        strategy_name,
                        position_date or date.today(),
                        symbol,
                        stream,
                        quantity,
                    ),
                )
    finally:
        conn.close()


def _lifecycle_state(db):
    conn = db()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT lifecycle FROM trading.strategy_registry WHERE id = %s",
                (STRATEGY_ID,),
            )
            return cursor.fetchone()["lifecycle"]
    finally:
        conn.close()


def _audit_count(db):
    conn = db()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT count(*) AS count FROM trading.strategy_lifecycle_log")
            return cursor.fetchone()["count"]
    finally:
        conn.close()


def test_same_day_explicit_qt_zero_overrides_nonzero_system_proposal(db):
    _position(db, stream="system", quantity=12)
    _position(db, stream="qt", quantity=0)

    _repo(db).retire_strategy(STRATEGY_ID, "review", "1")

    assert _lifecycle_state(db) == "retired"
    assert _audit_count(db) == 1


def test_nonzero_position_in_another_book_blocks_retirement_without_mutation(db):
    _position(db, book=BOOK_A, stream="qt", quantity=0)
    _position(db, book=BOOK_B, stream="qt", symbol="NQ", quantity=-2)

    with pytest.raises(IncubationError) as exc:
        _repo(db).retire_strategy(STRATEGY_ID, "review", "1")

    assert getattr(exc.value, "code", None) == "open_positions"
    assert _lifecycle_state(db) == "live"
    assert _audit_count(db) == 0


def _remove_membership(db, portfolio_id):
    PostgresStrategyRegistry(connection_factory=db).remove_membership(
        STRATEGY_ID,
        portfolio_id,
        {
            "strategy_id": STRATEGY_ID,
            "user_id": "1",
            "from_portfolio_id": portfolio_id,
            "to_portfolio_id": None,
            "lifecycle_at_move": "live",
            "reason": "remove historical book",
            "consequences": [],
            "acknowledged": True,
        },
    )


@pytest.mark.parametrize("transition", ["retire", "restart"])
@pytest.mark.parametrize(
    ("removed_book", "open_book", "closed_book"),
    [
        pytest.param(BOOK_B, BOOK_B, BOOK_A, id="removed-secondary"),
        pytest.param(BOOK_A, BOOK_A, BOOK_B, id="moved-primary"),
    ],
)
def test_removed_book_with_persisted_nonzero_position_still_blocks_lifecycle_close(
    db, transition, removed_book, open_book, closed_book
):
    _position(db, book=open_book, stream="qt", quantity=5)
    _position(db, book=closed_book, stream="qt", quantity=0)
    _remove_membership(db, removed_book)

    with pytest.raises(IncubationError) as exc:
        if transition == "retire":
            _repo(db).retire_strategy(STRATEGY_ID, "review", "1")
        else:
            _repo(db).start_incubation(STRATEGY_ID, 100_000, "restart", "1")

    assert getattr(exc.value, "code", None) == "open_positions"
    assert _lifecycle_state(db) == "live"
    assert _audit_count(db) == 0


def test_latest_date_is_selected_per_full_engine_identity_without_offsetting(db):
    _position(db, stream="qt", symbol="ES", quantity=8,
              position_date=date(2026, 9, 20))
    _position(db, stream="qt", symbol="ES", quantity=0,
              position_date=date(2026, 9, 21))
    _position(db, stream="qt", symbol="NQ", quantity=-8,
              position_date=date(2026, 9, 20))

    with pytest.raises(IncubationError) as exc:
        _repo(db).retire_strategy(STRATEGY_ID, "review", "1")

    assert getattr(exc.value, "code", None) == "open_positions"
    assert _lifecycle_state(db) == "live"


def test_live_strategy_without_reliable_position_evidence_fails_closed(db):
    with pytest.raises(IncubationError) as exc:
        _repo(db).retire_strategy(STRATEGY_ID, "review", "1")

    assert getattr(exc.value, "code", None) == "positions_unavailable"
    assert _lifecycle_state(db) == "live"
    assert _audit_count(db) == 0


def test_nonzero_system_without_matching_qt_is_not_flat_evidence(db):
    _position(db, stream="system", quantity=12)

    with pytest.raises(IncubationError) as exc:
        _repo(db).retire_strategy(STRATEGY_ID, "review", "1")

    assert getattr(exc.value, "code", None) == "positions_unavailable"
    assert _lifecycle_state(db) == "live"


def test_never_live_incubating_strategy_can_retire_without_position_rows(db):
    conn = db()
    try:
        with conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE trading.strategy_registry SET lifecycle = 'incubating'"
                )
    finally:
        conn.close()

    _repo(db).retire_strategy(STRATEGY_ID, "trial ended", "1")

    assert _lifecycle_state(db) == "retired"


def test_lifecycle_history_makes_a_restarted_live_strategy_fail_closed(db):
    conn = db()
    try:
        with conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE trading.strategy_registry SET lifecycle = 'incubating'"
                )
                cursor.execute(
                    """
                    INSERT INTO trading.strategy_lifecycle_log
                        (strategy_id, before_state, after_state, reason, user_id)
                    VALUES (%s, 'incubating', 'live', 'previous launch', '1')
                    """,
                    (STRATEGY_ID,),
                )
    finally:
        conn.close()

    with pytest.raises(IncubationError) as exc:
        _repo(db).retire_strategy(STRATEGY_ID, "review", "1")

    assert getattr(exc.value, "code", None) == "positions_unavailable"
    assert _lifecycle_state(db) == "incubating"
    assert _audit_count(db) == 1


def test_live_to_incubating_restart_cannot_bypass_open_position_guard(db):
    _position(db, stream="qt", quantity=1)

    with pytest.raises(IncubationError) as exc:
        _repo(db).start_incubation(STRATEGY_ID, 100_000, "restart", "1")

    assert getattr(exc.value, "code", None) == "open_positions"
    assert _lifecycle_state(db) == "live"
    assert _audit_count(db) == 0


def test_audit_failure_rolls_back_the_lifecycle_update(db):
    _position(db, stream="qt", quantity=0)

    with pytest.raises(IncubationStorageError):
        _repo(db).retire_strategy(STRATEGY_ID, "force audit failure", "1")

    assert _lifecycle_state(db) == "live"
    assert _audit_count(db) == 0


def test_already_retired_is_a_noop_without_a_repeated_audit_event(db):
    conn = db()
    try:
        with conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE trading.strategy_registry SET lifecycle = 'retired'"
                )
                cursor.execute(
                    """
                    INSERT INTO trading.strategy_lifecycle_log
                        (strategy_id, before_state, after_state, reason, user_id)
                    VALUES (%s, 'live', 'retired', 'first', '1')
                    """,
                    (STRATEGY_ID,),
                )
    finally:
        conn.close()

    _repo(db).retire_strategy(STRATEGY_ID, "second", "1")

    assert _lifecycle_state(db) == "retired"
    assert _audit_count(db) == 1


def test_history_is_bounded_and_deterministic(db):
    conn = db()
    try:
        with conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO trading.strategy_lifecycle_log
                        (strategy_id, before_state, after_state, reason, user_id, created_at)
                    VALUES
                        (%s, 'live', 'incubating', 'older', '1', '2026-09-21T00:00:00Z'),
                        (%s, 'incubating', 'live', 'same-a', '1', '2026-09-22T00:00:00Z'),
                        (%s, 'live', 'retired', 'same-b', '1', '2026-09-22T00:00:00Z')
                    """,
                    (STRATEGY_ID, STRATEGY_ID, STRATEGY_ID),
                )
    finally:
        conn.close()

    rows = _repo(db).list_lifecycle_history(STRATEGY_ID, limit=2)

    assert [row["reason"] for row in rows] == ["same-b", "same-a"]


def test_position_edit_queued_on_registry_lock_cannot_reopen_retired_strategy(db):
    _position(db, stream="qt", quantity=0)
    locker = db()
    locker.autocommit = False
    with locker.cursor() as cursor:
        cursor.execute(
            "SELECT lifecycle FROM trading.strategy_registry WHERE id = %s FOR UPDATE",
            (STRATEGY_ID,),
        )

    normalized = {
        "strategy_id": STRATEGY_ID,
        "strategy_name": ENGINE_A,
        "symbol": "ES",
        "quantity": 1.0,
        "average_price": 100.0,
        "reason": "queued edit",
    }

    def write():
        return _repo(db).write_qt_position(
            STRATEGY_TYPE,
            BOOK_A,
            normalized,
            "1",
            lambda *_: {"evaluated": True, "passed": True, "breaches": []},
        )

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(write)
        with pytest.raises(FutureTimeoutError):
            future.result(timeout=0.2)
        with locker.cursor() as cursor:
            cursor.execute(
                "UPDATE trading.strategy_registry SET lifecycle = 'retired' WHERE id = %s",
                (STRATEGY_ID,),
            )
        locker.commit()
        with pytest.raises(PositionValidationError) as exc:
            future.result(timeout=5)

    locker.close()
    assert exc.value.code == "strategy_retired"

    conn = db()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT quantity FROM trading.positions WHERE portfolio_type = 'qt'"
            )
            assert [float(row["quantity"]) for row in cursor.fetchall()] == [0.0]
            cursor.execute("SELECT count(*) AS count FROM trading.position_overrides")
            assert cursor.fetchone()["count"] == 0
    finally:
        conn.close()
