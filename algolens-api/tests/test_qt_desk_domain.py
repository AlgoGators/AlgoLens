"""QT desk rules (contract sections 4 and 7; rulings 13, 14, 16)."""

import hashlib
from decimal import Decimal

import pytest

from algolens.domain.qt.desk import (
    DeskRuleError,
    asked_vs_given,
    parse_contracts,
    plan_changes,
    require_reason,
    three_books,
    token_hash,
)


@pytest.mark.parametrize("value, expected", [(3, 3), (-2, -2), (0, 0), (4.0, 4), ("5", 5), (" -7 ", -7), ("+1", 1)])
def test_quantities_are_whole_contracts(value, expected):
    assert parse_contracts(value) == expected


@pytest.mark.parametrize("value", [1.5, "1.5", "", "abc", None, True, [], "1e3", "--1"])
def test_fractional_or_non_numeric_quantity_is_refused(value):
    with pytest.raises(DeskRuleError):
        parse_contracts(value)


def test_absurd_quantity_is_refused():
    with pytest.raises(DeskRuleError):
        parse_contracts(1_000_001)


@pytest.mark.parametrize("reason", [None, "", "   ", 5])
def test_reason_is_required(reason):
    with pytest.raises(DeskRuleError):
        require_reason(reason)


def test_reason_is_trimmed():
    assert require_reason("  rolled early  ") == "rolled early"


def test_plan_records_from_and_to_and_zero_means_flatten():
    current = {"ZC.v.0": Decimal("3"), "ZS.v.0": Decimal("-2"), "CL.v.0": Decimal("1")}
    changes = plan_changes(
        current,
        [
            {"symbol": "ZC.v.0", "quantity": 1},
            {"symbol": "ZS.v.0", "quantity": 0},  # flatten
            {"symbol": "CL.v.0", "quantity": 1},  # unchanged: dropped
            {"symbol": "6E.v.0", "quantity": -4},  # new symbol
        ],
    )
    assert changes == [
        {"symbol": "ZC.v.0", "from": 3, "to": 1},
        {"symbol": "ZS.v.0", "from": -2, "to": 0},
        {"symbol": "6E.v.0", "from": 0, "to": -4},
    ]


def test_plan_without_any_change_is_refused():
    with pytest.raises(DeskRuleError, match="No quantity changed"):
        plan_changes({"ZC.v.0": 3}, [{"symbol": "ZC.v.0", "quantity": 3}])
    with pytest.raises(DeskRuleError):
        plan_changes({}, [{"symbol": "NEW.v.0", "quantity": 0}])


@pytest.mark.parametrize(
    "edits",
    [
        None,
        "ZC",
        {"symbol": "ZC.v.0", "quantity": 1},
        [{"symbol": "", "quantity": 1}],
        [{"quantity": 1}],
        ["ZC.v.0"],
        [{"symbol": "ZC.v.0", "quantity": 1}, {"symbol": "ZC.v.0", "quantity": 2}],
    ],
)
def test_malformed_edits_are_refused(edits):
    with pytest.raises(DeskRuleError):
        plan_changes({"ZC.v.0": 3}, edits)


def test_token_hash_is_sha256_hex():
    assert token_hash("abc") == hashlib.sha256(b"abc").hexdigest()


def test_asked_vs_given_per_symbol_with_moved_by():
    rows = asked_vs_given(
        [{"symbol": "ZC.v.0", "quantity": Decimal("5")}, {"symbol": "ZS.v.0", "quantity": 0}],
        [
            {"symbol": "ZC.v.0", "quantity": Decimal("3"), "moved_by": "cap"},
            {"symbol": "ZS.v.0", "quantity": 0, "moved_by": None},
            {"symbol": "CL.v.0", "quantity": 1, "moved_by": "hold"},
        ],
    )
    assert rows == [
        {"symbol": "CL.v.0", "asked": None, "given": 1, "moved_by": "hold", "differs": True},
        {"symbol": "ZC.v.0", "asked": 5, "given": 3, "moved_by": "cap", "differs": True},
        {"symbol": "ZS.v.0", "asked": 0, "given": 0, "moved_by": None, "differs": False},
    ]


def test_three_books_lines_up_model_request_and_qt():
    rows = three_books(
        [{"symbol": "ZC.v.0", "quantity": 4}],
        [{"symbol": "ZC.v.0", "quantity": 6}, {"symbol": "ZS.v.0", "quantity": 1}],
        [{"symbol": "ZC.v.0", "quantity": 5, "moved_by": "cap"}],
    )
    assert rows == [
        {"symbol": "ZC.v.0", "model": 4, "asked": 6, "given": 5, "moved_by": "cap"},
        {"symbol": "ZS.v.0", "model": None, "asked": 1, "given": None, "moved_by": None},
    ]
