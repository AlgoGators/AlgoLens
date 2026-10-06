"""Exact position transport at the domain and detail response boundaries."""

from decimal import Decimal
from fractions import Fraction

import pytest

from algolens.domain.portfolio.calculations import transform_positions
from algolens.domain.portfolio.position_edit import (
    PositionValidationError,
    validate_position_payload,
)


def _payload(**changes):
    return {
        "strategy_id": "trendfollowing",
        "symbol": "ES",
        "quantity": "92233720368.12345678",
        "average_price": "5280.12345678",
        "reason": "exact transport",
        **changes,
    }


def test_canonical_strings_become_exact_decimal_values_for_storage():
    normalized = validate_position_payload(_payload())
    assert normalized["quantity"] == Decimal("92233720368.12345678")
    assert normalized["average_price"] == Decimal("5280.12345678")
    assert isinstance(normalized["quantity"], Decimal)
    assert isinstance(normalized["average_price"], Decimal)


@pytest.mark.parametrize("quantity", [
    "92233720368.54775807", "-92233720368.54775808", "0", "-0.00000001",
])
def test_signed_decimal8_quantity_boundaries_are_accepted(quantity):
    assert validate_position_payload(_payload(quantity=quantity))["quantity"] == Decimal(quantity)


@pytest.mark.parametrize("quantity", [
    "92233720368.54775808", "-92233720368.54775809", "1.000000001",
    "NaN", "Infinity", "1e100000000000000000", "1" * 300,
])
def test_unrepresentable_string_quantities_are_rejected(quantity):
    with pytest.raises(PositionValidationError):
        validate_position_payload(_payload(quantity=quantity))


@pytest.mark.parametrize("value,expected", [
    (1, Decimal("1")),
    (1.25, Decimal("1.25")),
    (Decimal("1.25"), Decimal("1.25")),
    ("1.25", Decimal("1.25")),
])
def test_direct_position_numbers_accept_supported_types(value, expected):
    assert validate_position_payload(_payload(quantity=value))["quantity"] == expected


@pytest.mark.parametrize("value", [
    True,
    Fraction(1, 2),
    type("IntSubclass", (int,), {})(1),
    type("FloatSubclass", (float,), {})(1.25),
])
def test_direct_position_numbers_reject_unsupported_types(value):
    with pytest.raises(PositionValidationError) as exc:
        validate_position_payload(_payload(quantity=value))
    assert exc.value.code == "quantity_not_a_number"


def test_average_price_accepts_maximum_and_zero():
    for price in ("92233720368.54775807", "0"):
        assert validate_position_payload(_payload(average_price=price))["average_price"] == Decimal(price)


@pytest.mark.parametrize("price,code", [
    ("92233720368.54775808", "price_not_representable"),
    ("1.000000001", "price_not_representable"),
    ("-0.00000001", "price_negative"),
])
def test_average_price_rejects_overflow_excess_precision_and_negative(price, code):
    with pytest.raises(PositionValidationError) as exc:
        validate_position_payload(_payload(average_price=price))
    assert exc.value.code == code


def test_detail_companions_precede_legacy_float_projection():
    row = transform_positions([{
        "symbol": "ES", "strategy_name": "Trend",
        "quantity": Decimal("92233720368.12345678"),
        "average_price": Decimal("5280.12345678"),
    }], None)[0]
    assert row["quantity_exact"] == "92233720368.12345678"
    assert row["average_price_exact"] == "5280.12345678"
    assert isinstance(row["quantity"], float)
    assert isinstance(row["costBasis"], float)


def test_detail_rejects_unrepresentable_source_evidence():
    with pytest.raises(ValueError):
        transform_positions([{
            "symbol": "ES", "strategy_name": "Trend",
            "quantity": Decimal("1.000000001"), "average_price": Decimal("3"),
        }], None)


def test_detail_preserves_genuinely_unknown_basis_as_null():
    row = transform_positions([{
        "symbol": "ES", "strategy_name": "Trend",
        "quantity": Decimal("1"), "average_price": None,
    }], None)[0]
    assert row["average_price_exact"] is None
    assert row["costBasis"] is None
