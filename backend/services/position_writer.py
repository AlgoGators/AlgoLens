"""Writes to the qt position stream, paired with an audit row.

Validation lives here rather than in the route so it can be tested without a
Flask app or a database, and so a second caller (a CLI, a batch import) cannot
reach the write path without passing the same checks.
"""

from numbers import Real

# Set by the service, never by the caller. See test_portfolio_type_cannot_be_
# overridden_by_the_caller for why this is not merely defensive.
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
            "writes the 'qt' stream only. The 'system' and 'benchmark' streams "
            "are the baseline QT is measured against and are not editable."
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
