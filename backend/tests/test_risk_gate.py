"""The gate compares a proposed book against limits trade-ngin published.

It deliberately does no risk math of its own. If a test here starts needing a
covariance matrix, the design has gone wrong -- that belongs in the engine.
"""

from services.risk_gate import evaluate

ENVELOPE = {
    "max_gross_notional": 1_000_000.0,
    "max_symbol_notional": {"ES": 300_000.0},
    "max_position_count": 3,
}

BOOK = [
    {"symbol": "ES", "quantity": 10, "average_price": 5_000.0},  # 50,000
    {"symbol": "NQ", "quantity": 4, "average_price": 18_000.0},  # 72,000
]


def test_absent_envelope_is_reported_as_unevaluated_not_as_a_pass():
    """A missing envelope must never look like a clean bill of health."""
    v = evaluate(None, BOOK, {"symbol": "ES", "quantity": 11, "average_price": 5_000.0})
    assert v["evaluated"] is False
    assert v["breaches"] == []


def test_a_position_within_every_limit_passes():
    v = evaluate(
        ENVELOPE, BOOK, {"symbol": "ES", "quantity": 11, "average_price": 5_000.0}
    )
    assert v["evaluated"] is True
    assert v["passed"] is True
    assert v["breaches"] == []


def test_breaching_the_per_symbol_cap_is_reported():
    v = evaluate(
        ENVELOPE, BOOK, {"symbol": "ES", "quantity": 100, "average_price": 5_000.0}
    )
    assert v["passed"] is False
    assert [b["limit"] for b in v["breaches"]] == ["max_symbol_notional"]
    assert v["breaches"][0]["actual"] == 500_000.0


def test_the_edited_symbol_replaces_its_old_row_rather_than_adding_to_it():
    """Raising ES from 10 to 11 must count as 55,000 of ES, not 105,000. Getting
    this wrong makes every edit look like a breach."""
    v = evaluate(
        ENVELOPE, BOOK, {"symbol": "ES", "quantity": 11, "average_price": 5_000.0}
    )
    gross = [b for b in v["breaches"] if b["limit"] == "max_gross_notional"]
    assert gross == []


def test_gross_notional_uses_absolute_value_so_shorts_add_risk():
    v = evaluate(
        ENVELOPE, BOOK, {"symbol": "ES", "quantity": -200, "average_price": 5_000.0}
    )
    assert v["passed"] is False
    assert "max_gross_notional" in [b["limit"] for b in v["breaches"]]


def test_a_new_symbol_can_breach_the_position_count():
    v = evaluate(ENVELOPE, BOOK, {"symbol": "CL", "quantity": 1, "average_price": 70.0})
    assert "max_position_count" in [b["limit"] for b in v["breaches"]]


def test_closing_to_zero_removes_the_symbol_from_the_count():
    """Flattening a position must never be reported as a breach."""
    v = evaluate(
        ENVELOPE, BOOK, {"symbol": "ES", "quantity": 0, "average_price": 5_000.0}
    )
    assert v["passed"] is True


def test_multiple_simultaneous_breaches_are_all_reported():
    v = evaluate(
        ENVELOPE, BOOK, {"symbol": "ES", "quantity": 1_000, "average_price": 5_000.0}
    )
    limits = {b["limit"] for b in v["breaches"]}
    assert limits == {"max_symbol_notional", "max_gross_notional"}
