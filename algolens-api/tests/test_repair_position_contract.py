"""User-visible identity, snapshot freshness and strict mutation input regressions."""
from dataclasses import replace
from datetime import date, timedelta

import pytest

from algolens.application.portfolio.use_cases import build_strategy_detail
from algolens.domain.portfolio.calculations import transform_finalized, transform_positions
from algolens.domain.portfolio.position_edit import PositionValidationError, validate_position_payload
from algolens.domain.portfolio.streams import current_utc_date
from tests.test_position_edit_routes import FakeReader, FakeRegistry, _BODY, _patch, _set_jwt_cookie
from tests.test_strategy_detail_book import _Reader, _Registry, PRIMARY


@pytest.fixture(autouse=True)
def no_market_database(monkeypatch):
    import algolens.adapters.http.portfolio as http
    monkeypatch.setattr(http, "create_market_data", lambda: None)
    monkeypatch.setattr(FakeReader, "fetch_summary_row", lambda *args: None, raising=False)
    monkeypatch.setattr(FakeRegistry, "reassign_portfolio", lambda *args: None, raising=False)


def position(name, quantity=2, day=None):
    return dict(symbol="ES", strategy_name=name, quantity=quantity,
                average_price=100, daily_realized_pnl=0, date=day or current_utc_date())


def test_position_identity_survives_display_and_previous_snapshot_comparison():
    current = [position("FAST", 2), position("SLOW", 4)]
    displayed = transform_positions(current, 10000)
    assert [(p.get("strategyName"), p["quantity"]) for p in displayed] == [("FAST", 2), ("SLOW", 4)]
    assert transform_finalized([position("FAST", 2), position("SLOW", 4)], current) == []
    closed = transform_finalized([position("FAST", 2), position("SLOW", 4)], [position("SLOW", 4)])
    assert [(p.get("strategyName"), p["quantity"]) for p in closed] == [("FAST", 2)]


@pytest.mark.parametrize("age,name,editable", [(0, "FAST", True), (3, "FAST", False), (0, None, False)])
def test_detail_discloses_actual_snapshot_and_safe_editability(age, name, editable):
    day = current_utc_date() - timedelta(days=age)
    rows = replace(_Reader().fetch_detail_rows("TREND", PRIMARY), positions=[position(name, day=day)])
    detail = build_strategy_detail(_Registry([PRIMARY]).get("trendfollowing"), rows)
    assert detail.get("positionDate") == day.isoformat()
    assert detail.get("positionsEditable") is editable
    assert bool(detail.get("positionEditUnavailableReason")) is (not editable)


@pytest.mark.parametrize("value", ["false", "true", 1, 0, [1], {}, None])
def test_only_json_boolean_is_a_risk_acknowledgement(client, monkeypatch, value):
    reader = FakeReader(envelope={"max_symbol_position_contracts": {"ES": 1}})
    _patch(monkeypatch, FakeRegistry(), reader)
    csrf = _set_jwt_cookie(client)
    response = client.post("/portfolio/positions", json={**_BODY, "acknowledge_risk": value}, headers={"X-CSRF-TOKEN": csrf})
    assert response.status_code == 400
    assert response.get_json().get("code") == "acknowledgement_not_boolean"
    assert reader.written is None


@pytest.mark.parametrize("sha,expected", [("a" * 40, "a" * 40), ("not-a-sha", None), ("", None)])
def test_version_discloses_only_valid_release_sha_without_database(monkeypatch, sha, expected):
    from algolens.infrastructure.config import app_factory

    def forbidden_database_connection():
        pytest.fail("The release version endpoint must never connect to a database")

    monkeypatch.setattr(app_factory, "get_db_connection", forbidden_database_connection)
    monkeypatch.setenv("APP_RELEASE_SHA", sha)
    app = app_factory.create_app()
    with app.test_client() as client:
        response = client.get("/version")
    assert response.status_code == 200
    assert response.get_json().get("release") == expected
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("path,method", [("/portfolio/positions", "post"), ("/portfolio/books/BOOK/strategies", "post")])
@pytest.mark.parametrize("body", [[1], "text", 1])
def test_non_object_mutation_body_is_400_not_server_error(client, monkeypatch, path, method, body):
    _patch(monkeypatch, FakeRegistry(), FakeReader())
    csrf = _set_jwt_cookie(client)
    response = getattr(client, method)(path, json=body, headers={"X-CSRF-TOKEN": csrf})
    assert response.status_code == 400


@pytest.mark.parametrize("path,method", [("/portfolio/strategies/trendfollowing/portfolio", "put"), ("/portfolio/books/BOOK/strategies/trendfollowing", "delete")])
@pytest.mark.parametrize("value", ["false", [1], 1, None])
def test_book_acknowledgements_reject_non_booleans_before_mutation(client, monkeypatch, path, method, value):
    _patch(monkeypatch, FakeRegistry(), FakeReader())
    csrf = _set_jwt_cookie(client)
    response = getattr(client, method)(path, json={"portfolio_id": "BOOK", "reason": "move", "acknowledge": value}, headers={"X-CSRF-TOKEN": csrf})
    assert response.status_code == 400
    assert response.get_json().get("code") == "acknowledgement_not_boolean"


@pytest.mark.parametrize("key", ["date", "position_date", "positionDate"])
def test_caller_cannot_select_a_historical_position_write_date(key):
    with pytest.raises(PositionValidationError) as exc:
        validate_position_payload({**_BODY, key: "2020-01-01"})
    assert exc.value.code == "position_date_forbidden"


def test_empty_utc_snapshot_is_editable_even_when_the_server_local_day_differs(monkeypatch):
    import algolens.application.portfolio.use_cases as use_cases

    utc_day = date(2099, 1, 2)
    monkeypatch.setattr(use_cases, "current_utc_date", lambda: utc_day, raising=False)
    rows = replace(_Reader().fetch_detail_rows("TREND", PRIMARY), positions=[],
                   position_date=utc_day, position_strategy_names=("FAST",))
    detail = build_strategy_detail(_Registry([PRIMARY]).get("trendfollowing"), rows)
    assert detail["positionDate"] == "2099-01-02"
    assert detail["positionsEditable"] is True
    assert detail["positionStrategyNames"] == ["FAST"]


def test_snapshot_engine_names_are_explicit_unique_and_not_guessed():
    rows = replace(_Reader().fetch_detail_rows("TREND", PRIMARY), positions=[],
                   position_date=current_utc_date(), position_strategy_names=("FAST", "SLOW", "FAST"))
    cfg = _Registry([PRIMARY]).get("trendfollowing")
    assert build_strategy_detail(cfg, rows)["positionStrategyNames"] == ["FAST", "SLOW"]
    unknown = replace(rows, position_strategy_names=())
    detail = build_strategy_detail(cfg, unknown)
    assert detail["positionStrategyNames"] == []
    assert detail["positionsEditable"] is False


def test_unknown_stream_and_date_are_readable_but_not_editable():
    rows = replace(_Reader().fetch_detail_rows("TREND", PRIMARY), positions=[position("FAST")],
                   position_stream=None, executions_available=False)
    detail = build_strategy_detail(_Registry([PRIMARY]).get("trendfollowing"), rows)
    assert detail["positions"]
    assert detail["positionsEditable"] is False
    assert detail["executionsAvailable"] is False
    assert detail["metrics"]["executionsToday"] is None
    assert detail["executionUnavailableReason"]


def test_model_positions_keep_qt_financials_without_cross_stream_closes():
    base = _Reader().fetch_detail_rows("TREND", PRIMARY)
    qt_today = [position("QT_DESK", 17)]
    rows = replace(
        base,
        positions=[position("MODEL_FAST", 2), position("MODEL_SLOW", 5)],
        position_stream="system",
        qt_positions=qt_today,
        yesterday_positions=[position("QT_DESK", 17, current_utc_date() - timedelta(days=1))],
        activity_stream="qt",
        finalized_positions_available=True,
    )

    detail = build_strategy_detail(_Registry([PRIMARY]).get("trendfollowing"), rows)

    assert detail["positionStream"] == "system"
    assert detail["activityStream"] == "qt"
    assert detail["finalizedPositionsAvailable"] is True
    assert detail["finalizedPositions"] == []
    assert detail["positionEditUnavailableReason"] and "model" in detail["positionEditUnavailableReason"].lower()
    assert [p["percentOfTotal"] for p in detail["positions"]] == [None, None]
    assert detail["currentValue"] == float(base.latest["current_portfolio_value"])


def test_qt_closed_book_requires_a_valid_comparison_even_when_fills_exist():
    base = _Reader().fetch_detail_rows("TREND", PRIMARY)
    previous = [position("QT_DESK", 17, current_utc_date() - timedelta(days=1))]
    rows = replace(
        base, positions=[], position_date=current_utc_date(),
        position_strategy_names=("QT_DESK",), position_stream="qt",
        qt_positions=[], yesterday_positions=previous,
        activity_stream="qt", finalized_positions_available=True,
    )
    cfg = _Registry([PRIMARY]).get("trendfollowing")
    known_empty = build_strategy_detail(cfg, rows)
    assert known_empty["finalizedPositionsAvailable"] is True
    assert [(p["strategyName"], p["quantity"]) for p in known_empty["finalizedPositions"]] == [("QT_DESK", 17.0)]

    absent = build_strategy_detail(cfg, replace(rows, position_date=None,
                                                finalized_positions_available=False))
    assert absent["finalizedPositionsAvailable"] is False
    assert absent["finalizedPositions"] == []
    assert absent["activityStream"] == "qt"
    assert absent["executions"] == known_empty["executions"]


@pytest.mark.parametrize("positions", [[position("FAST")], []])
def test_detail_preserves_today_qt_snapshot_without_financial_result(positions):
    rows = replace(
        _Reader().fetch_detail_rows("TREND", PRIMARY),
        latest=None,
        positions=positions,
        position_date=current_utc_date(),
        position_strategy_names=("FAST",),
        position_stream="qt",
        execution_date=None,
        executions_available=False,
    )
    detail = build_strategy_detail(_Registry([PRIMARY]).get("trendfollowing"), rows,
                                   prices={"ES": 125}, multipliers={"ES": 50})
    assert detail is not None
    assert detail["positionsEditable"] is True
    assert detail["positionDate"] == current_utc_date().isoformat()
    assert detail["positionStrategyNames"] == ["FAST"]
    assert detail["dataAvailable"] is False
    assert detail["resultSource"] == "qt"
    assert detail["resultDate"] is None
    assert detail["currentValue"] is None
    assert detail["return"] is None
    assert detail["metrics"]["currentPortfolioValue"] is None
    assert detail["metrics"]["executionsToday"] is None
    assert detail["executionsAvailable"] is False
    if positions:
        assert detail["positions"][0]["notional"] == 12500
        assert detail["positions"][0]["percentOfTotal"] is None
    else:
        assert detail["positions"] == []


def test_missing_result_does_not_make_old_or_unknown_snapshot_editable():
    base = _Reader().fetch_detail_rows("TREND", PRIMARY)
    cfg = _Registry([PRIMARY]).get("trendfollowing")
    for day, names in ((current_utc_date() - timedelta(days=1), ("FAST",)),
                       (current_utc_date(), ())):
        rows = replace(base, latest=None, positions=[], position_date=day,
                       position_strategy_names=names, position_stream="qt")
        detail = build_strategy_detail(cfg, rows)
        assert detail is not None
        assert detail["positionsEditable"] is False
        assert detail["positionEditUnavailableReason"]


def test_empty_book_without_result_or_qt_snapshot_remains_no_data():
    rows = replace(_Reader().fetch_detail_rows("TREND", PRIMARY), latest=None,
                   positions=[], position_date=None, position_strategy_names=(),
                   equity_curve=[], equity_by_stream={}, yesterday_positions=[])
    assert build_strategy_detail(_Registry([PRIMARY]).get("trendfollowing"), rows) is None


def test_older_qt_result_date_remains_distinct_from_today_position_snapshot():
    base = _Reader().fetch_detail_rows("TREND", PRIMARY)
    result_day = current_utc_date() - timedelta(days=5)
    rows = replace(base, latest={**base.latest, "date": result_day},
                   positions=[position("FAST")], position_date=current_utc_date(),
                   position_strategy_names=("FAST",), position_stream="qt")
    detail = build_strategy_detail(_Registry([PRIMARY]).get("trendfollowing"), rows)
    assert detail["dataAvailable"] is True
    assert detail["resultSource"] == "qt"
    assert detail["resultDate"] == result_day.isoformat()
    assert detail["positionDate"] == current_utc_date().isoformat()
    assert detail["positionsEditable"] is True
