"""Shared exact Decimal8 spelling and boundary vectors."""

import json
from pathlib import Path

import pytest

from algolens.domain.shared.fixed_decimal8 import parse_fixed_decimal8


VECTORS = json.loads(
    (Path(__file__).resolve().parents[2] / "contracts" / "fixed-decimal8-vectors.json")
    .read_text(encoding="utf-8")
)


@pytest.mark.parametrize("case", VECTORS["valid"], ids=lambda case: case["text"])
def test_accepts_canonical_spelling_verbatim(case):
    assert parse_fixed_decimal8(case["text"]) == case["text"]


@pytest.mark.parametrize("case", VECTORS["valid"], ids=lambda case: case["text"])
def test_fixture_scaled_integer_independently_matches_text(case):
    scaled = int(case["scaled"])
    whole, fractional = divmod(abs(scaled), 100_000_000)
    fraction_text = f"{fractional:08d}".rstrip("0")
    expected = ("-" if scaled < 0 else "") + str(whole)
    if fraction_text:
        expected += "." + fraction_text
    assert expected == case["text"]


@pytest.mark.parametrize("case", VECTORS["invalid"], ids=lambda case: case["label"])
def test_rejects_invalid_spelling_or_type_with_fixed_error(case):
    with pytest.raises(ValueError) as exc:
        parse_fixed_decimal8(case["value"])
    assert str(exc.value) == "invalid_fixed_decimal8"


def test_rejects_string_and_numeric_subclasses_without_coercion():
    class StringSubclass(str):
        pass

    class NumericSubclass(int):
        pass

    with pytest.raises(ValueError, match="^invalid_fixed_decimal8$"):
        parse_fixed_decimal8(StringSubclass("1"))
    with pytest.raises(ValueError, match="^invalid_fixed_decimal8$"):
        parse_fixed_decimal8(NumericSubclass(1))


def test_long_input_is_rejected_without_echoing_it():
    value = "9" * 10000
    with pytest.raises(ValueError) as exc:
        parse_fixed_decimal8(value)
    assert str(exc.value) == "invalid_fixed_decimal8"


def test_invalid_call_does_not_change_later_results():
    assert parse_fixed_decimal8("0.00000001") == "0.00000001"
    with pytest.raises(ValueError, match="^invalid_fixed_decimal8$"):
        parse_fixed_decimal8("92233720368.54775808")
    assert parse_fixed_decimal8("-0.00000001") == "-0.00000001"
    assert parse_fixed_decimal8("0.00000001") == "0.00000001"
