"""N5 r2/r3 (F1, "block demotion first"): no lifecycle change away from live while a desk day awaits finalization.

An unfinalized QT desk day is a processed desk decision whose accounting (trading.desk_run_results) has no
trading.qt_desk_finalizations row yet AND that the shipped next-day finalizer can still finalize: its date is
today or yesterday (UTC) by the database clock (r3, review N1). Older pending days can never be finalized and
never block. Desk days are dated relative to the database clock. The two relations carry the exact columns the
guard reads from the engine's 017/018 DDL. The lifecycle fixture is test_lifecycle_postgres's own (no desk
relations there, so every existing lifecycle case is the "desk tables absent" case and keeps passing).
"""
import pytest

from tests.conftest import client, current_users  # noqa: F401  (fixtures; location-independent)
from tests.integration.test_lifecycle_postgres import (  # noqa: F401  (db is a fixture)
    BOOK_A, BOOK_B, STRATEGY_ID, _audit_count, _lifecycle_state, _position, _repo, db)
from algolens.application.portfolio.ports import IncubationError

pytestmark = pytest.mark.integration

DECISION = "c0000000-0000-4000-8000-000000000001"
OTHER_DECISION = "c0000000-0000-4000-8000-000000000002"
DESK_DDL = """
CREATE TABLE IF NOT EXISTS trading.desk_run_results (
    decision_id uuid PRIMARY KEY, input_id uuid NOT NULL UNIQUE, portfolio_id text NOT NULL,
    date date NOT NULL, content_digest text NOT NULL, payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp());
CREATE TABLE IF NOT EXISTS trading.qt_desk_finalizations (
    finalization_id uuid PRIMARY KEY,
    decision_id uuid NOT NULL UNIQUE REFERENCES trading.desk_run_results(decision_id),
    book_id text NOT NULL, source_day date NOT NULL,
    valuation_day date NOT NULL CHECK (valuation_day > source_day));
"""


def _sql(db, statement, params=()):
    conn = db()
    try:
        with conn:
            with conn.cursor() as cursor:
                cursor.execute(statement, params)
                return cursor.fetchone() if cursor.description else None
    finally:
        conn.close()


def _desk_day(db, *, decision=DECISION, book=BOOK_A, days_ago=0, finalization_table=True):
    """A processed desk day dated days_ago before the database's UTC today; returns that date as text."""
    _sql(db, DESK_DDL if finalization_table else DESK_DDL.split("CREATE TABLE IF NOT EXISTS trading.qt_desk_finalizations")[0])
    row = _sql(db, "INSERT INTO trading.desk_run_results (decision_id,input_id,portfolio_id,date,content_digest,payload)"
                   " VALUES (%s, gen_random_uuid(), %s, (clock_timestamp() AT TIME ZONE 'UTC')::date - %s,"
                   " repeat('a',64), '{}') RETURNING date::text AS day", (decision, book, days_ago))
    return row["day"]


def _finalize(db, *, decision=DECISION):
    _sql(db, "INSERT INTO trading.qt_desk_finalizations (finalization_id,decision_id,book_id,source_day,valuation_day)"
             " SELECT gen_random_uuid(), decision_id, portfolio_id, date, date + 1"
             " FROM trading.desk_run_results WHERE decision_id = %s", (decision,))


def _flat(db):
    # Effective flatness evidence for a live strategy: an explicit qt zero in each member book.
    _position(db, book=BOOK_A, stream="qt", quantity=0)
    _position(db, book=BOOK_B, stream="qt", quantity=0)


def _incubate(db):
    _repo(db).start_incubation(STRATEGY_ID, 250000.0, "Move to incubation", "7")


def test_live_to_incubating_waits_for_the_desk_days_next_day_finalization(db):
    _flat(db)
    day = _desk_day(db)
    with pytest.raises(IncubationError) as refused:
        _incubate(db)
    assert getattr(refused.value, "code", None) == "desk_finalization_pending"
    assert f"BOOK_A {day}" in str(refused.value)
    assert (_lifecycle_state(db), _audit_count(db)) == ("live", 0)
    _finalize(db)
    _incubate(db)
    assert (_lifecycle_state(db), _audit_count(db)) == ("incubating", 1)


@pytest.mark.parametrize("days_ago", [0, 1])
def test_pending_days_dated_today_and_yesterday_block(db, days_ago):
    """r3 (N1): the days the shipped next-day finalizer can still finalize."""
    _flat(db)
    day = _desk_day(db, days_ago=days_ago)
    with pytest.raises(IncubationError, match=f"BOOK_A {day}"):
        _incubate(db)
    assert (_lifecycle_state(db), _audit_count(db)) == ("live", 0)


@pytest.mark.parametrize("days_ago", [2, 30])
def test_pending_day_older_than_yesterday_never_blocks(db, days_ago):
    """r3 (N1): the finalizer can never finalize it, so it must not block the demotion forever."""
    _flat(db)
    _desk_day(db, days_ago=days_ago)
    _incubate(db)
    assert (_lifecycle_state(db), _audit_count(db)) == ("incubating", 1)


def test_live_to_retired_waits_for_the_desk_days_next_day_finalization(db):
    _flat(db)
    day = _desk_day(db, book=BOOK_B, days_ago=1)
    with pytest.raises(IncubationError, match=f"BOOK_B {day}"):
        _repo(db).retire_strategy(STRATEGY_ID, "Retire", "7")
    assert (_lifecycle_state(db), _audit_count(db)) == ("live", 0)
    _finalize(db)
    _repo(db).retire_strategy(STRATEGY_ID, "Retire", "7")
    assert (_lifecycle_state(db), _audit_count(db)) == ("retired", 1)


def test_retired_to_incubating_also_waits(db):
    _sql(db, "UPDATE trading.strategy_registry SET lifecycle='retired' WHERE id=%s", (STRATEGY_ID,))
    _desk_day(db)
    with pytest.raises(IncubationError, match="awaiting next-day finalization"):
        _incubate(db)
    assert _lifecycle_state(db) == "retired"
    _finalize(db)
    _incubate(db)
    assert _lifecycle_state(db) == "incubating"


def test_every_pending_day_is_named_and_one_finalized_day_is_not_enough(db):
    _flat(db)
    _desk_day(db, days_ago=1)
    today = _desk_day(db, decision=OTHER_DECISION, book=" book_a ", days_ago=0)
    _finalize(db)
    with pytest.raises(IncubationError, match=f"book_a  {today}"):
        _incubate(db)
    _finalize(db, decision=OTHER_DECISION)
    _incubate(db)
    assert _lifecycle_state(db) == "incubating"


def test_desk_day_of_an_unrelated_book_does_not_block(db):
    _flat(db)
    _desk_day(db, book="UNRELATED_BOOK")
    _incubate(db)
    assert _lifecycle_state(db) == "incubating"


def test_accounting_without_the_finalization_relation_fails_closed(db):
    _flat(db)
    _desk_day(db, finalization_table=False)
    with pytest.raises(IncubationError, match="awaiting next-day finalization"):
        _incubate(db)
    assert _lifecycle_state(db) == "live"


def test_promotion_to_live_is_not_blocked(db):
    _flat(db)
    _desk_day(db)
    _finalize(db)
    _incubate(db)
    _desk_day(db, decision=OTHER_DECISION, days_ago=0)
    _repo(db).promote_to_live(STRATEGY_ID, "Promote", "7")
    assert _lifecycle_state(db) == "live"


def test_http_refusal_is_a_409_with_the_reason(db, client, monkeypatch):
    from algolens.infrastructure.config.dependencies import create_portfolio_dependencies
    from tests.test_incubation_routes import _set_jwt_cookie
    import algolens.adapters.http.portfolio as portfolio_http
    monkeypatch.setattr(portfolio_http, "create_portfolio_dependencies",
                        lambda: create_portfolio_dependencies(connection_factory=db))
    _flat(db)
    day = _desk_day(db)
    csrf = _set_jwt_cookie(client, role="admin", identity="7")
    response = client.post(f"/portfolio/incubation/{STRATEGY_ID}/start",
                           json={"mock_capital": 250000, "reason": "Move to incubation"},
                           headers={"X-CSRF-TOKEN": csrf})
    assert response.status_code == 409, response.get_json()
    body = response.get_json()
    assert body["error"] == "desk_finalization_pending"
    assert f"BOOK_A {day}" in body["reason"] and "finalization" in body["reason"]
    assert _lifecycle_state(db) == "live"
    _finalize(db)
    response = client.post(f"/portfolio/incubation/{STRATEGY_ID}/start",
                           json={"mock_capital": 250000, "reason": "Move to incubation"},
                           headers={"X-CSRF-TOKEN": csrf})
    assert response.status_code == 201, response.get_json()
    assert _lifecycle_state(db) == "incubating"
