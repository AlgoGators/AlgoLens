"""Postgres-backed tests of the QT desk reads and writes.

Opt-in: see tests/qt_fixture.py (ALGOLENS_TEST_DATABASE_URL, localhost only).
The schema is new_algo_data's after migrations 021 (emulated), 022 and 023.
"""

from datetime import date, datetime, timedelta, timezone

import psycopg2
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


def test_save_is_one_transaction_upserting_the_proposal_and_logging_the_save(qt_db):
    seed_day(qt_db)
    add_market(qt_db)
    agent = NullAgent()

    result = SaveDeskEdit(desk_repo(qt_db), agent).execute(
        entry(qt_db),
        [
            {"symbol": "ZC.v.0", "quantity": 0},  # flatten: a zero-quantity row
            {"symbol": "ZS.v.0", "quantity": -1},
            {"symbol": "6E.v.0", "quantity": 2},  # new: priced from market data
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
    use_case.execute(entry(qt_db), [{"symbol": "ZC.v.0", "quantity": 1}], "a", "d@x.com")
    use_case.execute(entry(qt_db), [{"symbol": "ZC.v.0", "quantity": 5}], "b", "d@x.com")

    assert float(proposal_rows(qt_db)["ZC.v.0"]["quantity"]) == 5
    assert [c["payload"]["changes"][0]["from"] for c in commands(qt_db)] == [3, 1]


def test_a_failed_save_leaves_nothing_behind(qt_db):
    seed_day(qt_db)
    add_market(qt_db)
    with pytest.raises(DeskRuleError):
        SaveDeskEdit(desk_repo(qt_db), NullAgent()).execute(
            entry(qt_db),
            [{"symbol": "ZC.v.0", "quantity": 1}, {"symbol": "NODATA.v.0", "quantity": 1}],
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
            entry(qt_db), [{"symbol": "ZC.v.0", "quantity": 1}], "r", "d@x.com"
        )
    assert float(proposal_rows(qt_db, D1)["ZC.v.0"]["quantity"]) == 3  # yesterday untouched
    assert commands(qt_db) == []


def test_save_on_a_portfolio_with_no_book_at_all_is_refused(qt_db):
    with pytest.raises(DeskNotSeeded):
        SaveDeskEdit(desk_repo(qt_db), NullAgent()).execute(
            entry(qt_db), [{"symbol": "ZC.v.0", "quantity": 1}], "r", "d@x.com"
        )


def test_the_model_twin_and_equity_books_are_not_editable(qt_db):
    seed_day(qt_db)
    for portfolio_id in (MODEL, "EQUITY_MR_PORTFOLIO"):
        with pytest.raises(DeskForbidden):
            SaveDeskEdit(desk_repo(qt_db), NullAgent()).execute(
                entry(qt_db, portfolio_id), [{"symbol": "ZC.v.0", "quantity": 1}], "r", "d@x.com"
            )


def test_reason_is_required_by_the_use_case_and_by_the_table(qt_db):
    seed_day(qt_db)
    with pytest.raises(DeskRuleError):
        SaveDeskEdit(desk_repo(qt_db), NullAgent()).execute(
            entry(qt_db), [{"symbol": "ZC.v.0", "quantity": 1}], "  ", "d@x.com"
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
        entry(qt_db), [{"symbol": "ZC.v.0", "quantity": 5}], "r", "d@x.com"
    )
    # The engine finishes the save.
    _exec(
        qt_db,
        "UPDATE trading.position_overrides SET status = 'done', message = 'one pass ran', "
        "result = %s, finished_at = now()",
        (psycopg2.extras.Json({"book_source": "desk"}),),
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
    _exec(
        factory,
        "UPDATE trading.position_overrides SET token_hash = %s, token_expires_at = now() + %s, "
        "status = 'done' WHERE id = %s",
        (token_hash("tok-123"), expires_in, result["command"]["id"]),
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
    _exec(qt_db, "UPDATE trading.position_overrides SET status = 'done'")
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
            entry(qt_db), [{"symbol": "ZC.v.0", "quantity": 1}], "r", "d@x.com"
        )


def test_command_rows_cannot_be_deleted(qt_db):
    seed_day(qt_db)
    PublishDesk(desk_repo(qt_db), NullAgent()).execute(entry(qt_db), "desk@x.com")
    with pytest.raises(psycopg2.Error):
        _exec(qt_db, "DELETE FROM trading.position_overrides")
