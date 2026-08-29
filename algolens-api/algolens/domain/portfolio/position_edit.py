"""Validation and risk evaluation for a manual edit to the qt position stream.

Pure domain logic: no database, no Flask, no serialization. Kept here rather
than in the route so a second caller (a CLI, a batch import) cannot reach the
write path without passing the same guards, and so every rule below is testable
without standing anything up.

Originally written for AlgoLens PRs #31/#32 (F2). Those were closed in August
2026 on the understanding that QT decision-making did not belong in AlgoLens;
that turned out to be a miscommunication, so this restores the design ADR-003
D-5 always described.
"""

from numbers import Real

# Set by the service, never by the caller. See
# test_portfolio_type_cannot_be_overridden_by_the_caller for why this is not
# merely defensive.
QT_STREAM = "qt"

REQUIRED_FIELDS = ("strategy_id", "symbol", "quantity", "reason")


class PositionValidationError(Exception):
    """Bad input from the caller. Maps to HTTP 400."""


def validate_position_payload(payload):
    """Normalize and check a proposed position edit.

    Returns a new dict; does not mutate the input.
    """
    if not isinstance(payload, dict):
        raise PositionValidationError("Request body must be a JSON object")

    if "portfolio_type" in payload:
        raise PositionValidationError(
            "portfolio_type may not be supplied by the caller: this endpoint "
            "writes the qt stream only. Other portfolio types are read-only."
        )

    for field in REQUIRED_FIELDS:
        if field not in payload or payload[field] is None:
            raise PositionValidationError(f"Missing required field: {field}")

    symbol = str(payload["symbol"]).strip().upper()
    if not symbol:
        raise PositionValidationError("Field 'symbol' must not be empty")

    strategy_id = str(payload["strategy_id"]).strip()
    if not strategy_id:
        raise PositionValidationError("Field 'strategy_id' must not be empty")

    reason = str(payload["reason"]).strip()
    if not reason:
        raise PositionValidationError(
            "Field 'reason' must not be empty: an override with no stated reason "
            "is indistinguishable from an accident when read back months later"
        )

    quantity = payload["quantity"]
    # bool is a subclass of int in Python; True would otherwise become 1 contract.
    if isinstance(quantity, bool) or not isinstance(quantity, Real):
        raise PositionValidationError("Field 'quantity' must be a number")

    average_price = payload.get("average_price")
    if average_price is not None:
        if isinstance(average_price, bool) or not isinstance(average_price, Real):
            raise PositionValidationError("Field 'average_price' must be a number")
        if average_price < 0:
            raise PositionValidationError("Field 'average_price' must not be negative")

    return {
        "strategy_id": strategy_id,
        "symbol": symbol,
        "quantity": quantity,
        "average_price": average_price,
        "reason": reason,
        "portfolio_type": QT_STREAM,
    }


def build_after_state(before, normalized):
    """The full position row as it will look after the edit.

    Starts from the existing row so fields this endpoint does not manage --
    realized PnL, timestamps written by the engine -- survive an edit rather
    than being silently blanked.
    """
    after = dict(before) if before else {}
    after["symbol"] = normalized["symbol"]
    after["quantity"] = normalized["quantity"]
    if normalized["average_price"] is not None:
        after["average_price"] = normalized["average_price"]
    return after


# --------------------------------------------------------------------------
# Risk evaluation
#
# This does NO risk math. trade-ngin owns VaR, leverage and correlation; it
# writes the resulting limits to trading.risk_limits and this compares against
# them. Two implementations of risk drift apart, and the wrong one gets believed.
#
# Per DECISION-1 the verdict is advisory -- it never blocks a write. The route
# uses it to force an explicit acknowledgement and to fill risk_check_result in
# the audit trail.
# --------------------------------------------------------------------------


def _notional(position):
    # A None average_price is treated as 0.0, so a position with unknown price
    # contributes nothing to notional limits regardless of its size. This is
    # deliberate: we cannot compute risk for a position we don't know the price of.
    price = position.get("average_price") or 0.0
    return abs(position["quantity"] * price)


def _projected_book(current_book, proposed):
    """The book as it would be after the edit.

    The edited symbol REPLACES its existing row. Adding to it instead would
    double-count every edit and report a breach on almost any change.
    """
    projected = [p for p in current_book if p["symbol"] != proposed["symbol"]]
    if proposed["quantity"] != 0:
        projected.append(proposed)
    return projected


def evaluate_risk(envelope, current_book, proposed):
    """Verdict on a single proposed position change."""
    if not envelope:
        # Explicitly NOT a pass. An unreachable envelope must be visible in the
        # audit trail as "not checked", never as "checked and fine".
        return {"evaluated": False, "passed": True, "breaches": []}

    projected = _projected_book(current_book, proposed)
    breaches = []

    symbol_caps = envelope.get("max_symbol_notional") or {}
    cap = symbol_caps.get(proposed["symbol"])
    if cap is not None:
        actual = _notional(proposed)
        if actual > cap:
            breaches.append(
                {
                    "limit": "max_symbol_notional",
                    "limit_value": cap,
                    "actual": actual,
                    "message": (
                        f"{proposed['symbol']} notional {actual:,.0f} exceeds its cap of {cap:,.0f}"
                    ),
                }
            )

    max_gross = envelope.get("max_gross_notional")
    if max_gross is not None:
        actual = sum(_notional(p) for p in projected)
        if actual > max_gross:
            breaches.append(
                {
                    "limit": "max_gross_notional",
                    "limit_value": max_gross,
                    "actual": actual,
                    "message": (
                        f"Gross notional {actual:,.0f} exceeds the portfolio cap of "
                        f"{max_gross:,.0f}"
                    ),
                }
            )

    max_count = envelope.get("max_position_count")
    if max_count is not None:
        actual = len(projected)
        if actual > max_count:
            breaches.append(
                {
                    "limit": "max_position_count",
                    "limit_value": max_count,
                    "actual": actual,
                    "message": (f"{actual} open positions exceeds the limit of {max_count}"),
                }
            )

    return {"evaluated": True, "passed": not breaches, "breaches": breaches}
