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


# --- hardening (2026-10-09 spec) ---------------------------------------------

from datetime import datetime, timedelta, timezone  # noqa: E402

from algolens.domain.qt.desk import (  # noqa: E402
    DeskStaleError,
    open_override_request,
    override_payload,
    plan_desk_edit,
    proposal_snapshot,
    snapshot_bytes,
    snapshot_sha256,
)


@pytest.mark.parametrize("value", ["²", "١", "1²", "１", "+", "-", " ", "1 2", "0x1", "1\n2", "9" * 400])
def test_only_ascii_digits_are_contracts(value):
    with pytest.raises(DeskRuleError):
        parse_contracts(value)


def test_snapshot_bytes_and_hash_are_the_contract_ones():
    rows = [
        {"strategy_name": "TF", "symbol": "ZS.v.0", "quantity": Decimal("-2")},
        {"strategy_name": "TF", "symbol": "ZC.v.0", "quantity": Decimal("3.000")},
        {"strategy_name": "A", "symbol": "6E.v.0", "quantity": Decimal("0")},
    ]
    snapshot = proposal_snapshot(rows)
    expected = (
        b'[{"strategy_name":"A","symbol":"6E.v.0","quantity":0},'
        b'{"strategy_name":"TF","symbol":"ZC.v.0","quantity":3},'
        b'{"strategy_name":"TF","symbol":"ZS.v.0","quantity":-2}]'
    )
    assert snapshot_bytes(snapshot) == expected
    assert snapshot_sha256(snapshot) == hashlib.sha256(expected).hexdigest()
    assert override_payload(rows) == {
        "proposal": snapshot,
        "proposal_sha256": hashlib.sha256(expected).hexdigest(),
    }


def test_snapshot_sorts_by_code_point_and_escapes_non_ascii():
    snapshot = proposal_snapshot(
        [
            {"strategy_name": "b", "symbol": "X", "quantity": 1},
            {"strategy_name": "B", "symbol": "X", "quantity": 1},
            {"strategy_name": "é", "symbol": "X", "quantity": 1},
        ]
    )
    assert [r["strategy_name"] for r in snapshot] == ["B", "b", "é"]
    assert b'"\u00e9"' in snapshot_bytes(snapshot)


def test_snapshot_refuses_a_fractional_quantity():
    with pytest.raises(DeskRuleError):
        proposal_snapshot([{"strategy_name": "TF", "symbol": "ZC.v.0", "quantity": Decimal("1.5")}])


def test_empty_snapshot_hash():
    assert snapshot_bytes([]) == b"[]"


def test_edits_carry_the_quantity_shown_and_stale_ones_are_refused():
    current = {"ZC.v.0": Decimal("3"), "ZS.v.0": Decimal("-2")}
    assert plan_desk_edit(
        current,
        [
            {"symbol": "ZC.v.0", "quantity": 1, "expected": 3},
            {"symbol": "6E.v.0", "quantity": 2, "expected": None},
        ],
    ) == [{"symbol": "ZC.v.0", "from": 3, "to": 1}, {"symbol": "6E.v.0", "from": 0, "to": 2}]
    with pytest.raises(DeskStaleError) as stale:
        plan_desk_edit(
            current,
            [
                {"symbol": "ZC.v.0", "quantity": 1, "expected": 4},
                {"symbol": "ZS.v.0", "quantity": 0, "expected": -2},
                {"symbol": "CL.v.0", "quantity": 1, "expected": 2},
            ],
        )
    assert stale.value.symbols == ["ZC.v.0", "CL.v.0"]
    with pytest.raises(DeskRuleError):  # expected is required
        plan_desk_edit(current, [{"symbol": "ZC.v.0", "quantity": 1}])
    with pytest.raises(DeskRuleError):
        plan_desk_edit(current, [{"symbol": "ZC.v.0", "quantity": 1, "expected": "3"}])


NOW = datetime(2026, 10, 8, 15, tzinfo=timezone.utc)


def _request(id_, status, sha="h", expires=NOW + timedelta(hours=1)):
    return {"id": id_, "kind": "override_request", "status": status, "parent_id": None,
            "payload": {"proposal_sha256": sha}, "token_expires_at": expires}


def _decision(parent, status):
    return {"id": 100 + parent, "kind": "override_decision", "status": status, "parent_id": parent}


@pytest.mark.parametrize(
    "commands, open_id",
    [
        ([], None),
        ([_request(1, "pending")], 1),
        ([_request(1, "running", sha="old")], 1),
        ([_request(1, "done")], 1),
        ([_request(1, "done", sha="old")], None),  # the proposal changed since
        ([_request(1, "done", expires=NOW)], None),  # expired
        ([_request(1, "done", expires=None)], None),  # never e-mailed a link
        ([_request(1, "done"), _decision(1, "pending")], None),
        ([_request(1, "done"), _decision(1, "done")], None),
        ([_request(1, "done"), _decision(1, "failed")], 1),  # may be decided again
        ([_request(1, "refused"), _request(2, "failed")], None),
    ],
)
def test_open_override_request(commands, open_id):
    found = open_override_request(commands, NOW, "h")
    assert (found["id"] if found else None) == open_id


def test_a_request_without_a_snapshot_never_matches():
    from algolens.domain.qt.desk import request_matches

    assert request_matches({"payload": {}}, None) is False
    assert request_matches({"payload": {"proposal_sha256": None}}, None) is False
    assert request_matches({"payload": {"proposal_sha256": "h"}}, "h") is True
    assert request_matches({"payload": None}, "h") is False
