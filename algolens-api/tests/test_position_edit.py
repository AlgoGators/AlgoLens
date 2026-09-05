"""Manual qt position edit: validation, risk verdict, and the write use case.

No-DB tests. The domain rules are pure functions; the use case is exercised
with small fakes standing in for the registry and the repository.

Ported from AlgoLens PR #31 (closed August 2026 on a miscommunication) onto the
layered package.
"""

import pytest

from algolens.application.portfolio.ports import RiskAcknowledgementRequired
from algolens.application.portfolio.use_cases import (
    ListPositionOverrides,
    StrategyNotFound,
    UpsertQtPosition,
)
from algolens.domain.portfolio.position_edit import (
    PositionValidationError,
    build_after_state,
    evaluate_risk,
    validate_position_payload,
)


def _payload(**overrides):
    base = {
        "strategy_id": "trendfollowing",
        "symbol": "es",
        "quantity": 3,
        "reason": "hedging the roll",
    }
    base.update(overrides)
    return base


# --- validation --------------------------------------------------------------


def test_symbol_is_upper_cased_and_trimmed():
    assert validate_position_payload(_payload(symbol="  es  "))["symbol"] == "ES"


def test_portfolio_type_cannot_be_overridden_by_the_caller():
    """The endpoint writes the qt stream only.

    Accepting portfolio_type from the body would let a caller write the
    'system' stream, which is the engine's own record of what it decided --
    silently rewriting history the attribution report is computed from.
    """
    with pytest.raises(PositionValidationError, match="portfolio_type"):
        validate_position_payload(_payload(portfolio_type="system"))


def test_validated_payload_always_carries_the_qt_stream():
    assert validate_position_payload(_payload())["portfolio_type"] == "qt"


@pytest.mark.parametrize("missing", ["strategy_id", "symbol", "quantity", "reason"])
def test_required_fields_are_required(missing):
    payload = _payload()
    del payload[missing]
    with pytest.raises(PositionValidationError, match=missing):
        validate_position_payload(payload)


def test_blank_reason_is_refused():
    with pytest.raises(PositionValidationError, match="reason"):
        validate_position_payload(_payload(reason="   "))


def test_boolean_quantity_is_not_a_number():
    """bool subclasses int in Python, so True would silently become 1 contract."""
    with pytest.raises(PositionValidationError, match="quantity"):
        validate_position_payload(_payload(quantity=True))


def test_negative_average_price_is_refused():
    with pytest.raises(PositionValidationError, match="average_price"):
        validate_position_payload(_payload(average_price=-1))


def test_body_must_be_an_object():
    with pytest.raises(PositionValidationError, match="JSON object"):
        validate_position_payload(["not", "a", "dict"])


def test_quantity_of_zero_is_valid_because_it_closes_a_position():
    assert validate_position_payload(_payload(quantity=0))["quantity"] == 0


# --- after-state -------------------------------------------------------------


def test_fields_the_endpoint_does_not_manage_survive_an_edit():
    before = {"symbol": "ES", "quantity": 1, "daily_realized_pnl": 42.0}
    after = build_after_state(before, validate_position_payload(_payload(quantity=5)))
    assert after["quantity"] == 5
    assert after["daily_realized_pnl"] == 42.0


def test_average_price_is_left_alone_when_not_supplied():
    before = {"symbol": "ES", "quantity": 1, "average_price": 5000.0}
    after = build_after_state(before, validate_position_payload(_payload()))
    assert after["average_price"] == 5000.0


# --- risk verdict ------------------------------------------------------------


def test_missing_envelope_is_reported_as_not_evaluated_not_as_a_pass():
    verdict = evaluate_risk(None, [], {"symbol": "ES", "quantity": 1})
    assert verdict["evaluated"] is False
    assert verdict["breaches"] == []


def test_symbol_notional_breach_is_reported():
    envelope = {"max_symbol_notional": {"ES": 1000.0}}
    proposed = {"symbol": "ES", "quantity": 10, "average_price": 500.0}
    verdict = evaluate_risk(envelope, [], proposed)
    assert verdict["passed"] is False
    assert verdict["breaches"][0]["limit"] == "max_symbol_notional"


def test_the_edited_symbol_replaces_its_row_rather_than_adding_to_it():
    """Adding would double-count and report a breach on almost any edit."""
    envelope = {"max_gross_notional": 6000.0}
    book = [{"symbol": "ES", "quantity": 10, "average_price": 500.0}]
    proposed = {"symbol": "ES", "quantity": 1, "average_price": 500.0}
    assert evaluate_risk(envelope, book, proposed)["passed"] is True


def test_closing_a_position_removes_it_from_the_projected_book():
    envelope = {"max_position_count": 1}
    book = [
        {"symbol": "ES", "quantity": 1, "average_price": 1.0},
        {"symbol": "NQ", "quantity": 1, "average_price": 1.0},
    ]
    proposed = {"symbol": "NQ", "quantity": 0, "average_price": 1.0}
    assert evaluate_risk(envelope, book, proposed)["passed"] is True


def test_unknown_price_contributes_nothing_to_notional():
    envelope = {"max_gross_notional": 1.0}
    proposed = {"symbol": "ES", "quantity": 10_000, "average_price": None}
    assert evaluate_risk(envelope, [], proposed)["passed"] is True


# --- use case ----------------------------------------------------------------


class _Registry:
    def __init__(self, strategy=None):
        self._strategy = strategy

    def get(self, strategy_id):
        return self._strategy

    def list(self, active_only=True):
        return [self._strategy] if self._strategy else []


class _Reader:
    def __init__(self, envelope=None, book=None):
        self.envelope = envelope
        self.book = book or []
        self.written = None

    def fetch_risk_envelope(self, strategy_type, portfolio_id):
        return self.envelope

    def fetch_qt_book(self, strategy_type, portfolio_id):
        return self.book

    def write_qt_position(self, **kwargs):
        self.written = kwargs
        return {"position": {"symbol": kwargs["normalized"]["symbol"]}, "override_id": 1}

    def fetch_overrides(self, strategy_type, limit=100):
        return [{"id": 1, "strategy_id": strategy_type}]


_STRATEGY = {
    "id": "trendfollowing",
    "strategy_type": "LIVE_TREND_FOLLOWING",
    "portfolio_id": "BASE_PORTFOLIO",
}


def test_unknown_strategy_is_not_found():
    with pytest.raises(StrategyNotFound):
        UpsertQtPosition(_Registry(None), _Reader()).execute(_payload(), user_id="7")


def test_a_clean_edit_is_written_with_its_verdict():
    reader = _Reader()
    result = UpsertQtPosition(_Registry(_STRATEGY), reader).execute(_payload(), user_id="7")
    assert result["risk_check"]["evaluated"] is False
    assert reader.written["overrode_risk"] is False
    assert reader.written["user_id"] == "7"


def test_a_breach_is_refused_until_it_is_acknowledged():
    reader = _Reader(envelope={"max_symbol_notional": {"ES": 1.0}})
    with pytest.raises(RiskAcknowledgementRequired) as excinfo:
        UpsertQtPosition(_Registry(_STRATEGY), reader).execute(
            _payload(average_price=500.0), user_id="7"
        )
    assert excinfo.value.verdict["breaches"]
    assert reader.written is None, "a refused edit must not reach the database"


def test_an_acknowledged_breach_is_written_and_recorded_as_an_override():
    reader = _Reader(envelope={"max_symbol_notional": {"ES": 1.0}})
    UpsertQtPosition(_Registry(_STRATEGY), reader).execute(
        _payload(average_price=500.0), user_id="7", acknowledge_risk=True
    )
    assert reader.written["overrode_risk"] is True
    assert reader.written["verdict"]["passed"] is False


def test_the_write_always_targets_the_qt_stream():
    reader = _Reader()
    UpsertQtPosition(_Registry(_STRATEGY), reader).execute(_payload(), user_id="7")
    assert reader.written["normalized"]["portfolio_type"] == "qt"


def test_overrides_are_listed_by_the_engine_strategy_type_not_the_display_id():
    reader = _Reader()
    rows = ListPositionOverrides(_Registry(_STRATEGY), reader).execute("trendfollowing")
    assert rows[0]["strategy_id"] == "LIVE_TREND_FOLLOWING"


def test_overrides_for_an_unknown_strategy_are_not_found():
    with pytest.raises(StrategyNotFound):
        ListPositionOverrides(_Registry(None), _Reader()).execute("nope")
