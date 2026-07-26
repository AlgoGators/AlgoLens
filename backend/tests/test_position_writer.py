"""Validation is the only thing standing between a fat finger and the book.

These are pure-function tests: no database, no Flask. If they need either,
the separation between validation and I/O has been broken.
"""

import pytest

from services.position_writer import (
    PositionValidationError,
    build_after_state,
    validate_position_payload,
)


def _valid():
    return {
        "strategy_id": "trendfollowing",
        "symbol": "ES",
        "quantity": 12,
        "average_price": 5200.25,
        "reason": "Trimming index exposure ahead of CPI",
    }


def test_accepts_a_well_formed_payload():
    out = validate_position_payload(_valid())
    assert out["symbol"] == "ES"
    assert out["quantity"] == 12
    assert out["average_price"] == pytest.approx(5200.25)


def test_symbol_is_uppercased_and_trimmed():
    p = _valid() | {"symbol": "  es  "}
    assert validate_position_payload(p)["symbol"] == "ES"


@pytest.mark.parametrize("missing", ["strategy_id", "symbol", "quantity", "reason"])
def test_required_fields_are_required(missing):
    p = _valid()
    del p[missing]
    with pytest.raises(PositionValidationError, match=missing):
        validate_position_payload(p)


def test_reason_of_only_whitespace_is_rejected():
    """The DB CHECK would catch this, but as an IntegrityError with no useful
    message. Reject it here so the user is told what is wrong."""
    p = _valid() | {"reason": "    "}
    with pytest.raises(PositionValidationError, match="reason"):
        validate_position_payload(p)


def test_quantity_must_be_a_number_not_a_numeric_string():
    p = _valid() | {"quantity": "twelve"}
    with pytest.raises(PositionValidationError, match="quantity"):
        validate_position_payload(p)


def test_zero_quantity_is_allowed_because_it_means_close_the_position():
    assert validate_position_payload(_valid() | {"quantity": 0})["quantity"] == 0


def test_negative_quantity_is_allowed_because_short_is_a_position():
    assert validate_position_payload(_valid() | {"quantity": -4})["quantity"] == -4


def test_negative_average_price_is_rejected():
    with pytest.raises(PositionValidationError, match="average_price"):
        validate_position_payload(_valid() | {"average_price": -1})


def test_portfolio_type_cannot_be_overridden_by_the_caller():
    """The single most important guard in this file. A caller who can name the
    stream can rewrite the benchmark, which is the yardstick QT is measured
    against."""
    with pytest.raises(PositionValidationError, match="portfolio_type"):
        validate_position_payload(_valid() | {"portfolio_type": "benchmark"})


def test_build_after_state_on_a_new_position_has_an_empty_before():
    after = build_after_state(None, validate_position_payload(_valid()))
    assert after["quantity"] == 12
    assert after["symbol"] == "ES"


def test_build_after_state_preserves_untouched_fields_from_before():
    before = {
        "symbol": "ES",
        "quantity": 5,
        "average_price": 5100.0,
        "daily_realized_pnl": 42.0,
    }
    after = build_after_state(before, validate_position_payload(_valid()))
    assert after["quantity"] == 12
    assert after["daily_realized_pnl"] == 42.0, "unrelated fields must survive an edit"
