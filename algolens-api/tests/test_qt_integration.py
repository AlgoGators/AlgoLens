"""Postgres-backed tests of the QT desk reads and writes.

Opt-in: see tests/qt_fixture.py (ALGOLENS_TEST_DATABASE_URL, localhost only).
The schema is new_algo_data's after migrations 021 (emulated), 022 and 023.
"""

from datetime import date, datetime, timedelta, timezone

import psycopg2
import psycopg2.errors
import psycopg2.extras
import pytest

from algolens.application.qt.ports import (
    DeskConflict,
    DeskForbidden,
    DeskGone,
    DeskNotSeeded,
)
from algolens.application.qt.use_cases import (
    DecideOverride,
    GetDeskState,
    ListSymbolChoices,
    LookupApproval,
    PublishDesk,
    RequestOverride,
    SaveDeskEdit,
)
from algolens.domain.portfolio.registry import portfolio_entries
from algolens.domain.qt.desk import DeskRuleError, token_hash
from qt_fixture import qt_db, requires_db  # noqa: F401  (fixture)

pytestmark = requires_db

QT = "QT_CONSERVATIVE_PORTFOLIO"
MODEL = "QT_CONSERVATIVE_MODEL_PORTFOLIO"
STRATEGY = "LIVE_TREND_FOLLOWING"
SLEEVE = "TREND_FOLLOWING"
D1, D2 = date(2026, 10, 7), date(2026, 10, 8)


def _exec(factory, sql, params=()):
    with factory.setup.cursor() as cur:
        cur.execute(sql, params)
        try:
            return cur.fetchall()
        except Exception:
            return None


def add_position(factory, book, day, symbol, qty, price=100.0, portfolio=QT, sleeve=SLEEVE,
                 moved_by=None):
    _exec(
        factory,
        """
        INSERT INTO trading.positions
            (symbol, quantity, average_price, daily_unrealized_pnl, daily_realized_pnl,
             last_update, updated_at, strategy_id, strategy_name, date, portfolio_id,
             portfolio_type, moved_by)
        VALUES (%s, %s, %s, 5, 1, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (symbol, qty, price, datetime(day.year, day.month, day.day, 18, tzinfo=timezone.utc),
         datetime(day.year, day.month, day.day, 18, tzinfo=timezone.utc), STRATEGY, sleeve,
         day, portfolio, book, moved_by),
    )


def add_results(factory, book, day, value, portfolio=QT):
    _exec(
        factory,
        """
        INSERT INTO trading.live_results
            (strategy_id, portfolio_id, date, config, current_portfolio_value,
             total_annualized_return, volatility, portfolio_type)
        VALUES (%s, %s, %s, %s, %s, 1, 10, %s)
        """,
        (STRATEGY, portfolio, day, '{"strategy_type": "%s"}' % STRATEGY, value, book),
    )


def add_execution(factory, book, day, exec_id, symbol, portfolio=QT):
    _exec(
        factory,
        """
        INSERT INTO trading.executions
            (portfolio_id, strategy_id, strategy_name, date, exec_id, symbol, side,
             quantity, price, execution_time, commissions_fees, portfolio_type)
        VALUES (%s, %s, %s, %s, %s, %s, 'BUY', 1, 100, %s, 1, %s)
        """,
        (portfolio, STRATEGY, SLEEVE, day, exec_id, symbol,
         datetime(day.year, day.month, day.day, 18, tzinfo=timezone.utc), book),
    )


def repo(factory):
    from algolens.infrastructure.portfolio.repositories import PostgresPortfolioRepository

    return PostgresPortfolioRepository(connection_factory=factory)


def registry(factory):
    from algolens.infrastructure.portfolio.strategy_registry import PostgresStrategyRegistry

    return PostgresStrategyRegistry(connection_factory=factory)


# --- A2: registry and portfolio-id reads -------------------------------------


def test_registry_carries_the_two_qt_portfolios_from_migration_023(qt_db):
    from algolens.domain.portfolio.registry import group_portfolios

    groups = group_portfolios(registry(qt_db).list(active_only=True))

    qt_group = next(g for g in groups if g["group"] == "qt_conservative")
    assert [(p["portfolio_id"], p["desk_editable"]) for p in qt_group["portfolios"]] == [
        (QT, True),
        (MODEL, False),
    ]
    equity = next(g for g in groups if g["group"] == "EQUITY_MR_PORTFOLIO")
    assert equity["portfolios"][0]["asset_class"] == "equity"
    assert equity["portfolios"][0]["desk_editable"] is False


def test_portfolio_read_serves_each_book_on_its_latest_date(qt_db):
    add_results(qt_db, "system", D2, 501000)
    add_results(qt_db, "qt", D2, 502000)
    add_position(qt_db, "system", D2, "ZC.v.0", 3)
    add_position(qt_db, "qt_proposal", D2, "ZC.v.0", 2)
    add_position(qt_db, "qt", D1, "ZC.v.0", 9)
    add_position(qt_db, "qt", D2, "ZC.v.0", 1, moved_by="cap")

    by_book = {
        book: repo(qt_db).fetch_portfolio_rows(QT, book=book, allow_fallback=False)
        for book in ("system", "qt_proposal", "qt")
    }

    assert {b: [float(p["quantity"]) for p in r.positions] for b, r in by_book.items()} == {
        "system": [3.0],
        "qt_proposal": [2.0],
        "qt": [1.0],
    }
    assert float(by_book["qt"].latest["current_portfolio_value"]) == 502000
    # qt_proposal has no results row of its own: the system row's numbers.
    assert float(by_book["qt_proposal"].latest["current_portfolio_value"]) == 501000


def test_portfolio_read_nets_sleeves_and_hides_flattened_symbols(qt_db):
    add_results(qt_db, "qt", D2, 500000)
    add_position(qt_db, "qt", D2, "ZC.v.0", 2, price=400, sleeve="A")
    add_position(qt_db, "qt", D2, "ZC.v.0", 1, price=430, sleeve="B")
    add_position(qt_db, "qt", D2, "ZS.v.0", 0)

    rows = repo(qt_db).fetch_portfolio_rows(QT, book="qt", allow_fallback=False)

    assert [(p["symbol"], float(p["quantity"]), float(p["average_price"])) for p in rows.positions] == [
        ("ZC.v.0", 3.0, 410.0)
    ]


def test_portfolio_read_falls_back_to_system_only_when_unnamed(qt_db):
    add_results(qt_db, "system", D2, 500000, portfolio=MODEL)
    add_position(qt_db, "system", D2, "ZC.v.0", 3, portfolio=MODEL)
    add_position(qt_db, "qt", D2, "ZC.v.0", 1, portfolio=QT)  # another portfolio's qt

    fallback = repo(qt_db).fetch_portfolio_rows(MODEL)
    exact = repo(qt_db).fetch_portfolio_rows(MODEL, book="qt", allow_fallback=False)

    assert (fallback.book, fallback.fell_back) == ("system", True)
    assert [p["symbol"] for p in fallback.positions] == ["ZC.v.0"]
    assert (exact.book, exact.fell_back, exact.positions) == ("qt", False, [])


def test_portfolio_read_scopes_executions_to_the_book(qt_db):
    add_results(qt_db, "qt", D2, 500000)
    add_position(qt_db, "qt", D2, "ZC.v.0", 1)
    add_execution(qt_db, "system", D2, "e1", "ZC.v.0")
    add_execution(qt_db, "qt", D2, "e1", "ZS.v.0")

    rows = repo(qt_db).fetch_portfolio_rows(QT, book="qt", allow_fallback=False)

    assert [e["symbol"] for e in rows.executions] == ["ZS.v.0"]


def test_portfolio_read_ignores_strategy_id(qt_db):
    # A book is found by its portfolio id; the strategy id is a description.
    add_results(qt_db, "qt", D2, 500000)
    _exec(
        qt_db,
        "UPDATE trading.live_results SET strategy_id = 'RENAMED', config = '{}'",
    )
    add_position(qt_db, "qt", D2, "ZC.v.0", 1)

    rows = repo(qt_db).fetch_portfolio_rows(QT, book="qt", allow_fallback=False)

    assert rows.latest is not None
    assert [p["symbol"] for p in rows.positions] == ["ZC.v.0"]


# --- A3-A6: the desk against the real command log ----------------------------


class NullAgent:
    """The engine is down: every call is lost, nothing may fail."""

    def __init__(self):
        self.calls = []

    def _lost(self, *args):
        self.calls.append(args)
        return "not delivered (UNAVAILABLE)"

    def run_desk(self, command):
        return self._lost(command)

    def request_override(self, command):
        return self._lost(command)

    def publish(self, command):
        return self._lost(command)

    def record_decision(self, decision, token):
        return self._lost(decision, token)


def desk_repo(factory):
    from algolens.infrastructure.qt.repositories import PostgresDeskRepository

    return PostgresDeskRepository(connection_factory=factory)


def entry(factory, portfolio_id=QT):
    cfg = registry(factory).get_portfolio(portfolio_id)
    return portfolio_entries([cfg])[0]


def seed_day(factory, day=D2, proposal=True):
    """The model run's day: system, a qt_proposal copy and a qt copy."""
    for symbol, qty, price in (("ZC.v.0", 3, 400.0), ("ZS.v.0", -2, 1000.0)):
        add_position(factory, "system", day, symbol, qty, price)
        if proposal:
            add_position(factory, "qt_proposal", day, symbol, qty, price)
        add_position(factory, "qt", day, symbol, qty, price)


def add_market(factory):
    _exec(
        factory,
        """
        INSERT INTO metadata.contract_metadata
            ("Databento Symbol", "IB Symbol", "Name", "Exchange", "Asset Type", "Sector", "Contract Size")
        VALUES ('6E', 'M6E', 'EUR/USD', 'CME', 'Futures', 'FX', '125000'),
               ('ES', 'ES', 'E-mini S&P', 'CME', 'Futures', 'Equity', '50'),
               ('NODATA', 'X', 'No data', 'CME', 'Futures', 'FX', '1'),
               ('AAPL', 'AAPL', 'Apple', 'NASDAQ', 'Equity', 'Tech', '1')
        """,
    )
    # A duplicated (symbol, time) bar: the higher-volume copy is the one the
    # engine keeps, so it is the price.
    _exec(
        factory,
        """
        INSERT INTO futures_data.ohlcv_1d (time, symbol, open, high, low, close, volume) VALUES
            ('2026-10-06', '6E.v.0', 1, 1, 1, 1.10, 100),
            ('2026-10-07', '6E.v.0', 1, 1, 1, 1.17, 50),
            ('2026-10-07', '6E.v.0', 1, 1, 1, 1.15, 900),
            ('2026-10-07', 'ES.v.0', 1, 1, 1, 5000, 10)
        """,
    )


def proposal_rows(factory, day=D2):
    return {
        r["symbol"]: r
        for r in _exec(
            factory,
            "SELECT * FROM trading.positions WHERE portfolio_id = %s AND date = %s "
            "AND portfolio_type = 'qt_proposal'",
            (QT, day),
        )
    }


def commands(factory):
    return _exec(factory, "SELECT * FROM trading.position_overrides ORDER BY id")


def engine_finishes(factory, command_id, status="done", **columns):
    """The engine (desk-agent) runs a command: pending -> running -> status
    (C4), setting engine-owned columns on the final move."""
    _exec(
        factory,
        "UPDATE trading.position_overrides SET status = 'running', started_at = now() "
        "WHERE id = %s",
        (command_id,),
    )
    sets = ", ".join(f"{name} = %s" for name in columns)
    _exec(
        factory,
        "UPDATE trading.position_overrides SET status = %s, finished_at = now()"
        + (", " + sets if sets else "")
        + " WHERE id = %s",
        (status, *columns.values(), command_id),
    )


def test_save_is_one_transaction_upserting_the_proposal_and_logging_the_save(qt_db):
    seed_day(qt_db)
    add_market(qt_db)
    agent = NullAgent()

    result = SaveDeskEdit(desk_repo(qt_db), agent).execute(
        entry(qt_db),
        [
            {"symbol": "ZC.v.0", "quantity": 0, "expected": 3},  # flatten: a zero-quantity row
            {"symbol": "ZS.v.0", "quantity": -1, "expected": -2},
            {"symbol": "6E.v.0", "quantity": 2, "expected": None},  # new: priced from market data
        ],
        "desk view on corn",
        "desk@x.com",
    )

    rows = proposal_rows(qt_db)
    assert float(rows["ZC.v.0"]["quantity"]) == 0  # stored, not deleted (ruling 16)
    assert float(rows["ZS.v.0"]["quantity"]) == -1
    new = rows["6E.v.0"]
    assert float(new["quantity"]) == 2
    assert float(new["average_price"]) == 1.15  # latest close, engine's keep order
    assert float(new["daily_unrealized_pnl"]) == 0 and float(new["daily_realized_pnl"]) == 0
    assert (new["strategy_id"], new["strategy_name"]) == (STRATEGY, SLEEVE)
    assert float(rows["ZS.v.0"]["daily_unrealized_pnl"]) == 0
    system = _exec(
        qt_db,
        "SELECT symbol, quantity FROM trading.positions WHERE portfolio_type = 'system' ORDER BY symbol",
    )
    assert [(r["symbol"], float(r["quantity"])) for r in system] == [("ZC.v.0", 3.0), ("ZS.v.0", -2.0)]

    [save] = commands(qt_db)
    assert (save["kind"], save["status"], save["date"], save["requested_by"]) == (
        "save", "pending", D2, "desk@x.com")
    assert save["payload"] == {"changes": [
        {"symbol": "ZC.v.0", "from": 3, "to": 0},
        {"symbol": "ZS.v.0", "from": -2, "to": -1},
        {"symbol": "6E.v.0", "from": 0, "to": 2},
    ]}
    assert result["command"]["id"] == save["id"]
    assert len(agent.calls) == 1  # the lost call did not fail the save


def test_saves_are_repeatable_and_read_the_latest_proposal(qt_db):
    seed_day(qt_db)
    use_case = SaveDeskEdit(desk_repo(qt_db), NullAgent())
    use_case.execute(entry(qt_db), [{"symbol": "ZC.v.0", "quantity": 1, "expected": 3}], "a", "d@x.com")
    use_case.execute(entry(qt_db), [{"symbol": "ZC.v.0", "quantity": 5, "expected": 1}], "b", "d@x.com")

    assert float(proposal_rows(qt_db)["ZC.v.0"]["quantity"]) == 5
    assert [c["payload"]["changes"][0]["from"] for c in commands(qt_db)] == [3, 1]


def test_a_failed_save_leaves_nothing_behind(qt_db):
    seed_day(qt_db)
    add_market(qt_db)
    with pytest.raises(DeskRuleError):
        SaveDeskEdit(desk_repo(qt_db), NullAgent()).execute(
            entry(qt_db),
            [{"symbol": "ZC.v.0", "quantity": 1, "expected": 3}, {"symbol": "NODATA.v.0", "quantity": 1, "expected": None}],
            "r",
            "d@x.com",
        )
    assert float(proposal_rows(qt_db)["ZC.v.0"]["quantity"]) == 3  # rolled back
    assert commands(qt_db) == []


def test_save_before_the_day_is_seeded_is_refused(qt_db):
    seed_day(qt_db, day=D1)
    seed_day(qt_db, day=D2, proposal=False)  # today's model run, no proposal yet

    with pytest.raises(DeskNotSeeded):
        SaveDeskEdit(desk_repo(qt_db), NullAgent()).execute(
            entry(qt_db), [{"symbol": "ZC.v.0", "quantity": 1, "expected": 3}], "r", "d@x.com"
        )
    assert float(proposal_rows(qt_db, D1)["ZC.v.0"]["quantity"]) == 3  # yesterday untouched
    assert commands(qt_db) == []


def test_save_on_a_portfolio_with_no_book_at_all_is_refused(qt_db):
    with pytest.raises(DeskNotSeeded):
        SaveDeskEdit(desk_repo(qt_db), NullAgent()).execute(
            entry(qt_db), [{"symbol": "ZC.v.0", "quantity": 1, "expected": 3}], "r", "d@x.com"
        )


def test_the_model_twin_and_equity_books_are_not_editable(qt_db):
    seed_day(qt_db)
    for portfolio_id in (MODEL, "EQUITY_MR_PORTFOLIO"):
        with pytest.raises(DeskForbidden):
            SaveDeskEdit(desk_repo(qt_db), NullAgent()).execute(
                entry(qt_db, portfolio_id), [{"symbol": "ZC.v.0", "quantity": 1, "expected": 3}], "r", "d@x.com"
            )


def test_reason_is_required_by_the_use_case_and_by_the_table(qt_db):
    seed_day(qt_db)
    with pytest.raises(DeskRuleError):
        SaveDeskEdit(desk_repo(qt_db), NullAgent()).execute(
            entry(qt_db), [{"symbol": "ZC.v.0", "quantity": 1, "expected": 3}], "  ", "d@x.com"
        )
    with pytest.raises(psycopg2.errors.CheckViolation):
        _exec(
            qt_db,
            "INSERT INTO trading.position_overrides (portfolio_id, date, kind, requested_by, reason) "
            "VALUES (%s, %s, 'save', 'd@x.com', '  ')",
            (QT, D2),
        )


def test_symbol_choices_come_from_contract_metadata_with_latest_close(qt_db):
    add_market(qt_db)
    choices = ListSymbolChoices(desk_repo(qt_db)).execute(entry(qt_db))
    # ES (full-size, outside the engine's universe), NODATA (no bars) and
    # AAPL (not futures) are not offered.
    assert [(c["symbol"], c["price"]) for c in choices] == [("6E.v.0", 1.15)]


def test_desk_state_compares_asked_and_given_with_moved_by(qt_db):
    seed_day(qt_db)
    _exec(
        qt_db,
        "UPDATE trading.positions SET quantity = 1, moved_by = 'cap' "
        "WHERE portfolio_type = 'qt' AND symbol = 'ZC.v.0'",
    )
    SaveDeskEdit(desk_repo(qt_db), NullAgent()).execute(
        entry(qt_db), [{"symbol": "ZC.v.0", "quantity": 5, "expected": 3}], "r", "d@x.com"
    )
    # The engine finishes the save.
    engine_finishes(
        qt_db,
        commands(qt_db)[-1]["id"],
        message="one pass ran",
        result=psycopg2.extras.Json({"book_source": "desk"}),
    )

    state = GetDeskState(desk_repo(qt_db)).execute(entry(qt_db))

    assert state["date"] == D2.isoformat() and state["seeded"] is True
    zc = next(r for r in state["comparison"] if r["symbol"] == "ZC.v.0")
    assert (zc["asked"], zc["given"], zc["moved_by"], zc["differs"]) == (5, 1, "cap", True)
    assert state["latestSave"]["status"] == "done"
    assert state["latestSave"]["message"] == "one pass ran"


def _emailed(factory, requested_by="desk@x.com", expires_in=timedelta(hours=48)):
    """A request whose link the engine has e-mailed (token_hash is engine-owned)."""
    seed_day(factory)
    result = RequestOverride(desk_repo(factory), NullAgent()).execute(
        entry(factory), "breach on purpose", requested_by
    )
    expires = _exec(factory, "SELECT now() + %s AS at", (expires_in,))[0]["at"]
    engine_finishes(
        factory,
        result["command"]["id"],
        token_hash=token_hash("tok-123"),
        token_expires_at=expires,
    )
    return result["command"]["id"]


def test_override_decision_is_recorded_once(qt_db):
    request_id = _emailed(qt_db)
    agent = NullAgent()

    page = LookupApproval(desk_repo(qt_db)).execute("tok-123")
    assert page["request"]["id"] == request_id
    assert {r["symbol"] for r in page["table"]} == {"ZC.v.0", "ZS.v.0"}

    DecideOverride(desk_repo(qt_db), agent).execute("tok-123", True, "p@x.com", "president", "fine")
    decision = commands(qt_db)[-1]
    assert (decision["kind"], decision["parent_id"], decision["approver_role"], decision["payload"]) == (
        "override_decision", request_id, "president", {"approved": True})
    assert decision["requested_by"] == "p@x.com"
    assert len(agent.calls) == 1

    with pytest.raises(DeskConflict):
        DecideOverride(desk_repo(qt_db), agent).execute("tok-123", False, "vp@x.com", "vp")
    assert len(commands(qt_db)) == 2


def test_override_decision_refusals(qt_db):
    _emailed(qt_db, requested_by="VP@x.com")
    decide = DecideOverride(desk_repo(qt_db), NullAgent())
    with pytest.raises(DeskForbidden):
        decide.execute("tok-123", True, "random@x.com", None)  # not an approver
    with pytest.raises(DeskForbidden):
        decide.execute("tok-123", True, "vp@x.com", "vp")  # own request
    assert [c["kind"] for c in commands(qt_db)] == ["override_request"]


def test_expired_approval_link(qt_db):
    _emailed(qt_db, expires_in=timedelta(seconds=-1))
    with pytest.raises(DeskGone):
        LookupApproval(desk_repo(qt_db)).execute("tok-123")
    with pytest.raises(DeskGone):
        DecideOverride(desk_repo(qt_db), NullAgent()).execute("tok-123", True, "p@x.com", "president")


def test_publish_row_and_publish_state(qt_db):
    seed_day(qt_db)
    PublishDesk(desk_repo(qt_db), NullAgent()).execute(entry(qt_db), "desk@x.com")
    [publish] = commands(qt_db)
    assert (publish["kind"], publish["status"], publish["date"]) == ("publish", "pending", D2)
    with pytest.raises(DeskConflict):
        PublishDesk(desk_repo(qt_db), NullAgent()).execute(entry(qt_db), "desk@x.com")

    # The engine publishes: the row is done and live_run_metadata carries who/when.
    engine_finishes(qt_db, publish["id"])
    _exec(
        qt_db,
        "INSERT INTO trading.live_run_metadata "
        "(date, strategy_id, portfolio_id, published_by, published_at) "
        "VALUES (%s, %s, %s, 'desk@x.com', '2026-10-08T21:00:00Z')",
        (D2, STRATEGY, QT),
    )
    state = GetDeskState(desk_repo(qt_db)).execute(entry(qt_db))
    assert state["published"]["published_by"] == "desk@x.com"
    assert state["publish"]["status"] == "done"

    with pytest.raises(DeskConflict):  # a published day takes no more edits
        SaveDeskEdit(desk_repo(qt_db), NullAgent()).execute(
            entry(qt_db), [{"symbol": "ZC.v.0", "quantity": 1, "expected": 3}], "r", "d@x.com"
        )


def test_command_rows_cannot_be_deleted(qt_db):
    seed_day(qt_db)
    PublishDesk(desk_repo(qt_db), NullAgent()).execute(entry(qt_db), "desk@x.com")
    with pytest.raises(psycopg2.Error):
        _exec(qt_db, "DELETE FROM trading.position_overrides")


# --- hardening (2026-10-09 spec: C1, C2, C3, optimistic save) -----------------


def publish_on_live_run_metadata(factory, day=D2, by="system:non-trading-day"):
    """The engine marks the day published (also its own non-trading-day
    publish, with no publish command row at all)."""
    _exec(
        factory,
        "INSERT INTO trading.live_run_metadata "
        "(date, strategy_id, portfolio_id, published_by, published_at) "
        "VALUES (%s, %s, %s, %s, now())",
        (day, STRATEGY, QT, by),
    )


SNAPSHOT_BYTES = (
    b'[{"strategy_name":"TREND_FOLLOWING","symbol":"ZC.v.0","quantity":3},'
    b'{"strategy_name":"TREND_FOLLOWING","symbol":"ZS.v.0","quantity":-2}]'
)


def test_override_request_snapshots_the_proposal_and_its_hash(qt_db):
    import hashlib

    seed_day(qt_db)
    RequestOverride(desk_repo(qt_db), NullAgent()).execute(entry(qt_db), "breach", "d@x.com")

    [request] = commands(qt_db)
    assert request["payload"]["proposal"] == [
        {"strategy_name": SLEEVE, "symbol": "ZC.v.0", "quantity": 3},
        {"strategy_name": SLEEVE, "symbol": "ZS.v.0", "quantity": -2},
    ]
    assert request["payload"]["proposal_sha256"] == hashlib.sha256(SNAPSHOT_BYTES).hexdigest()


def test_snapshot_keeps_zero_rows_and_sorts_by_sleeve_then_symbol(qt_db):
    seed_day(qt_db)
    add_position(qt_db, "qt_proposal", D2, "6E.v.0", 0, sleeve="A_SLEEVE")
    RequestOverride(desk_repo(qt_db), NullAgent()).execute(entry(qt_db), "breach", "d@x.com")
    proposal = commands(qt_db)[0]["payload"]["proposal"]
    assert [(r["strategy_name"], r["symbol"], r["quantity"]) for r in proposal] == [
        ("A_SLEEVE", "6E.v.0", 0),
        (SLEEVE, "ZC.v.0", 3),
        (SLEEVE, "ZS.v.0", -2),
    ]


def test_one_open_override_request_a_day(qt_db):
    seed_day(qt_db)
    request = RequestOverride(desk_repo(qt_db), NullAgent())
    first = request.execute(entry(qt_db), "breach", "d@x.com")["command"]
    with pytest.raises(DeskConflict):  # pending
        request.execute(entry(qt_db), "again", "d@x.com")

    expires = _exec(qt_db, "SELECT now() + interval '2 days' AS at")[0]["at"]
    engine_finishes(qt_db, first["id"], token_hash=token_hash("t1"), token_expires_at=expires)
    with pytest.raises(DeskConflict):  # e-mailed, undecided, still the same book
        request.execute(entry(qt_db), "again", "d@x.com")

    # The desk saves again: the old request can never be approved, so a new
    # one is allowed.
    SaveDeskEdit(desk_repo(qt_db), NullAgent()).execute(
        entry(qt_db), [{"symbol": "ZC.v.0", "quantity": 4, "expected": 3}], "r", "d@x.com"
    )
    second = request.execute(entry(qt_db), "new book", "d@x.com")["command"]
    assert second["payload"]["proposal_sha256"] != first["payload"]["proposal_sha256"]


def test_a_rejected_request_frees_the_day_for_a_new_one(qt_db):
    _emailed(qt_db)
    DecideOverride(desk_repo(qt_db), NullAgent()).execute("tok-123", False, "p@x.com", "president")
    RequestOverride(desk_repo(qt_db), NullAgent()).execute(entry(qt_db), "again", "d@x.com")
    assert [c["kind"] for c in commands(qt_db)] == [
        "override_request", "override_decision", "override_request"]


def test_approval_of_a_changed_proposal_is_refused_but_rejection_is_not(qt_db):
    _emailed(qt_db)
    SaveDeskEdit(desk_repo(qt_db), NullAgent()).execute(
        entry(qt_db), [{"symbol": "ZC.v.0", "quantity": 9, "expected": 3}], "r", "d@x.com"
    )
    page = LookupApproval(desk_repo(qt_db)).execute("tok-123")
    assert page["snapshotMatches"] is False
    assert page["snapshot"][0]["quantity"] == 3

    with pytest.raises(DeskConflict, match="proposal changed after the override was requested"):
        DecideOverride(desk_repo(qt_db), NullAgent()).execute("tok-123", True, "p@x.com", "president")
    DecideOverride(desk_repo(qt_db), NullAgent()).execute("tok-123", False, "p@x.com", "president")
    assert commands(qt_db)[-1]["payload"] == {"approved": False}


def test_approval_page_shows_the_snapshot(qt_db):
    _emailed(qt_db)
    page = LookupApproval(desk_repo(qt_db)).execute("tok-123")
    assert page["snapshotMatches"] is True
    assert [(r["symbol"], r["quantity"]) for r in page["snapshot"]] == [("ZC.v.0", 3), ("ZS.v.0", -2)]


def test_a_failed_decision_can_be_retried_but_a_live_one_cannot(qt_db):
    request_id = _emailed(qt_db)
    decide = DecideOverride(desk_repo(qt_db), NullAgent())
    first = decide.execute("tok-123", True, "p@x.com", "president")["command"]
    with pytest.raises(DeskConflict):
        decide.execute("tok-123", True, "vp@x.com", "vp")
    engine_finishes(qt_db, first["id"], status="failed", message="smtp down")
    decide.execute("tok-123", True, "vp@x.com", "vp")
    assert [c["parent_id"] for c in commands(qt_db) if c["kind"] == "override_decision"] == [
        request_id, request_id]


def test_a_request_not_yet_emailed_cannot_be_decided(qt_db):
    seed_day(qt_db)
    command = RequestOverride(desk_repo(qt_db), NullAgent()).execute(
        entry(qt_db), "breach", "d@x.com")["command"]
    with pytest.raises(DeskConflict):
        desk_repo(qt_db).insert_decision(command["id"], True, "p@x.com", "president", None)


def test_a_published_day_is_frozen_even_without_a_publish_row(qt_db):
    _emailed(qt_db)
    publish_on_live_run_metadata(qt_db)
    repo = desk_repo(qt_db)

    with pytest.raises(DeskConflict, match="published"):
        SaveDeskEdit(repo, NullAgent()).execute(
            entry(qt_db), [{"symbol": "ZC.v.0", "quantity": 1, "expected": 3}], "r", "d@x.com")
    with pytest.raises(DeskConflict, match="published"):
        RequestOverride(repo, NullAgent()).execute(entry(qt_db), "breach", "d@x.com")
    with pytest.raises(DeskConflict, match="published"):
        DecideOverride(repo, NullAgent()).execute("tok-123", True, "p@x.com", "president")
    with pytest.raises(DeskConflict, match="published"):
        PublishDesk(repo, NullAgent()).execute(entry(qt_db), "d@x.com")
    assert [c["kind"] for c in commands(qt_db)] == ["override_request"]
    assert float(proposal_rows(qt_db)["ZC.v.0"]["quantity"]) == 3

    state = GetDeskState(repo).execute(entry(qt_db))
    assert state["locked"] == "published"
    assert state["published"]["published_by"] == "system:non-trading-day"


def test_save_and_override_are_refused_while_a_publish_is_open(qt_db):
    seed_day(qt_db)
    repo = desk_repo(qt_db)
    PublishDesk(repo, NullAgent()).execute(entry(qt_db), "d@x.com")
    with pytest.raises(DeskConflict, match="publish"):
        SaveDeskEdit(repo, NullAgent()).execute(
            entry(qt_db), [{"symbol": "ZC.v.0", "quantity": 1, "expected": 3}], "r", "d@x.com")
    with pytest.raises(DeskConflict, match="publish"):
        RequestOverride(repo, NullAgent()).execute(entry(qt_db), "breach", "d@x.com")
    assert GetDeskState(repo).execute(entry(qt_db))["locked"] == "publishing"


def test_a_stale_save_is_refused_and_lists_the_changed_symbols(qt_db):
    from algolens.domain.qt.desk import DeskStaleError

    seed_day(qt_db)
    save = SaveDeskEdit(desk_repo(qt_db), NullAgent())
    save.execute(entry(qt_db), [{"symbol": "ZC.v.0", "quantity": 1, "expected": 3}], "a", "a@x.com")
    with pytest.raises(DeskStaleError) as stale:  # b still saw 3
        save.execute(
            entry(qt_db),
            [{"symbol": "ZC.v.0", "quantity": 7, "expected": 3},
             {"symbol": "ZS.v.0", "quantity": 0, "expected": -2}],
            "b",
            "b@x.com",
        )
    assert stale.value.symbols == ["ZC.v.0"]
    assert float(proposal_rows(qt_db)["ZC.v.0"]["quantity"]) == 1
    assert float(proposal_rows(qt_db)["ZS.v.0"]["quantity"]) == -2
    assert len(commands(qt_db)) == 1


def test_writers_of_a_day_wait_for_each_other(qt_db):
    """Two publishes at once: the second waits on the day lock, then sees the
    first one's row and is refused (no double publish)."""
    import threading
    import time

    seed_day(qt_db)
    holder = qt_db()
    cursor = holder.cursor()
    cursor.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
        (f"algolens.qt_desk|{QT}|{D2.isoformat()}",),
    )
    outcome = {}

    def second_publish():
        try:
            PublishDesk(desk_repo(qt_db), NullAgent()).execute(entry(qt_db), "b@x.com")
            outcome["result"] = "inserted"
        except DeskConflict as exc:
            outcome["result"] = str(exc)

    thread = threading.Thread(target=second_publish)
    thread.start()
    for _ in range(50):
        waiting = _exec(
            qt_db,
            "SELECT count(*) AS n FROM pg_locks WHERE locktype = 'advisory' AND NOT granted",
        )[0]["n"]
        if waiting:
            break
        time.sleep(0.1)
    assert waiting == 1 and "result" not in outcome
    # The first publish lands while the second waits.
    cursor.execute(
        "INSERT INTO trading.position_overrides (portfolio_id, date, kind, requested_by) "
        "VALUES (%s, %s, 'publish', 'a@x.com')",
        (QT, D2),
    )
    holder.commit()
    holder.close()
    thread.join(10)
    assert "already pending" in outcome["result"]
    assert len(commands(qt_db)) == 1


def test_a_unique_violation_from_025_is_a_409(qt_db, monkeypatch):
    if qt_db.version != "025":
        pytest.skip("the unique partial indexes are 025's")
    from algolens.infrastructure.qt.repositories import PostgresDeskRepository

    seed_day(qt_db)
    PublishDesk(desk_repo(qt_db), NullAgent()).execute(entry(qt_db), "a@x.com")
    # Without AlgoLens' own check the index still refuses a second open publish.
    monkeypatch.setattr(PostgresDeskRepository, "_guard_day", lambda *a, **k: None)
    with pytest.raises(DeskConflict, match="already open"):
        PublishDesk(desk_repo(qt_db), NullAgent()).execute(entry(qt_db), "b@x.com")
    assert len(commands(qt_db)) == 1


def test_after_025_algolens_only_inserts_into_the_command_log(qt_db):
    seed_day(qt_db)
    PublishDesk(desk_repo(qt_db), NullAgent()).execute(entry(qt_db), "a@x.com")
    conn = qt_db()
    try:
        with conn.cursor() as cur:
            if qt_db.version == "025":
                with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                    cur.execute("UPDATE trading.position_overrides SET message = 'x'")
            else:
                cur.execute("SELECT 1")
    finally:
        conn.rollback()
        conn.close()


def test_desk_state_reports_the_open_override_request(qt_db):
    request_id = _emailed(qt_db)
    state = GetDeskState(desk_repo(qt_db)).execute(entry(qt_db))
    assert state["openOverrideRequestId"] == request_id
    assert state["locked"] is None
    assert state["overrideRequests"][0]["payload"]["proposal_sha256"]


# --- A7: desk settings as strategy_config versions ---------------------------

RUN_CONFIG = {
    "capital": 500000,
    "risk": {"max_leverage": 2.0, "max_drawdown": 0.3},
    "strategies": {"tf": {"lookbacks": [16, 32]}},
}


def report_settings(factory, day, version, config=RUN_CONFIG, portfolio=QT):
    """A live run of the 022 binary writing settings_used."""
    _exec(
        factory,
        "INSERT INTO trading.live_run_metadata (date, strategy_id, portfolio_id, settings_used) "
        "VALUES (%s, %s, %s, %s)",
        (day, STRATEGY, portfolio,
         psycopg2.extras.Json({"strategy_config_version": version, "config": config})),
    )


def config_rows(factory, portfolio=QT):
    return _exec(
        factory,
        "SELECT version, overrides, is_active, reason, created_by FROM trading.strategy_config "
        "WHERE portfolio_id = %s ORDER BY version",
        (portfolio,),
    )


def test_settings_versions_keep_exactly_one_active(qt_db):
    from algolens.application.qt.settings_use_cases import (
        GetSettings,
        RevertSettings,
        SaveSettings,
    )

    report_settings(qt_db, D1, None)
    repo = desk_repo(qt_db)

    SaveSettings(repo).execute(
        entry(qt_db), [{"path": ["risk", "max_leverage"], "value": 1.5}], "less risk", "d@x.com"
    )
    SaveSettings(repo).execute(
        entry(qt_db), [{"path": ["strategies", "tf", "lookbacks"], "value": [8, 16]}], "faster", "d@x.com"
    )

    rows = config_rows(qt_db)
    assert [(r["version"], r["is_active"]) for r in rows] == [(1, False), (2, True)]
    assert rows[1]["overrides"] == {"risk": {"max_leverage": 1.5}, "strategies": {"tf": {"lookbacks": [8, 16]}}}
    assert (rows[1]["reason"], rows[1]["created_by"]) == ("faster", "d@x.com")

    view = GetSettings(repo).execute(entry(qt_db))
    assert view["running"]["version"] is None and view["pending"] is True
    lev = next(f for f in view["fields"] if f["path"] == ["risk", "max_leverage"])
    assert (lev["value"], lev["pending"]) == (2.0, 1.5)

    # The next run picked version 2 up: running == active, nothing pending.
    report_settings(qt_db, D2, 2, config={**RUN_CONFIG, "risk": {"max_leverage": 1.5, "max_drawdown": 0.3}})
    assert GetSettings(repo).execute(entry(qt_db))["pending"] is False

    RevertSettings(repo).execute(entry(qt_db), 1, "undo faster", "d@x.com")
    rows = config_rows(qt_db)
    assert [(r["version"], r["is_active"]) for r in rows] == [(1, False), (2, False), (3, True)]
    assert rows[2]["overrides"] == {"risk": {"max_leverage": 1.5}}

    # The database itself refuses a second active version.
    with pytest.raises(psycopg2.errors.UniqueViolation):
        _exec(qt_db, "UPDATE trading.strategy_config SET is_active = true WHERE version = 1")


def test_settings_refuse_unknown_keys_and_hidden_sections(qt_db):
    from algolens.application.qt.settings_use_cases import SaveSettings
    from algolens.domain.qt.settings import SettingsRuleError

    report_settings(qt_db, D1, None)
    for change in (
        {"path": ["risk", "invented"], "value": 1.0},
        {"path": ["database", "host"], "value": "x"},
    ):
        with pytest.raises(SettingsRuleError):
            SaveSettings(desk_repo(qt_db)).execute(entry(qt_db), [change], "r", "d@x.com")
    assert config_rows(qt_db) == []


def test_settings_save_detects_a_concurrent_change(qt_db):
    report_settings(qt_db, D1, None)
    repo = desk_repo(qt_db)
    repo.insert_config_version(QT, {"capital": 1}, "first", "a@x.com", None)
    with pytest.raises(DeskConflict):
        repo.insert_config_version(QT, {"capital": 2}, "stale", "b@x.com", None)
    assert [r["version"] for r in config_rows(qt_db)] == [1]
