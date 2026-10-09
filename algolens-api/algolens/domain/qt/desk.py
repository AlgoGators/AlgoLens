"""QT desk rules: the command log and the desk's quantity edits.

Pure rules from docs/design/qt-contract.md (trade-ngin) sections 4 and 7 and
the master rulings 13, 14 and 16. No database, no HTTP.
"""

import hashlib
from collections.abc import Iterable, Mapping
from decimal import Decimal, InvalidOperation
from numbers import Integral
from typing import Any

# trading.position_overrides (migration 023).
SAVE = "save"
OVERRIDE_REQUEST = "override_request"
OVERRIDE_DECISION = "override_decision"
PUBLISH = "publish"
COMMAND_KINDS = (SAVE, OVERRIDE_REQUEST, OVERRIDE_DECISION, PUBLISH)

PENDING = "pending"
RUNNING = "running"
DONE = "done"
REFUSED = "refused"
FAILED = "failed"
COMMAND_STATUSES = (PENDING, RUNNING, DONE, REFUSED, FAILED)
OPEN_STATUSES = (PENDING, RUNNING)
FINAL_STATUSES = (DONE, REFUSED, FAILED)

# Largest absolute contract count the desk may type. A guard against a typo
# (an extra zero or three), not a risk limit: the engine's one pass sizes.
MAX_ABS_CONTRACTS = 100_000

MAX_REASON_LENGTH = 2000


class DeskRuleError(ValueError):
    """A desk request breaks a rule; the message says which, for the user."""


def require_reason(reason: Any) -> str:
    """The written reason every desk change carries (contract section 4)."""
    if not isinstance(reason, str) or not reason.strip():
        raise DeskRuleError("A reason is required")
    reason = reason.strip()
    if len(reason) > MAX_REASON_LENGTH:
        raise DeskRuleError(f"The reason is longer than {MAX_REASON_LENGTH} characters")
    return reason


def parse_contracts(value: Any) -> int:
    """A quantity in whole contracts, signed. 0 means flatten (ruling 16)."""
    if isinstance(value, bool):
        raise DeskRuleError("Quantity must be a whole number of contracts")
    if isinstance(value, Integral):
        quantity = int(value)
    elif isinstance(value, float):
        if not value.is_integer():
            raise DeskRuleError("Quantity must be a whole number of contracts")
        quantity = int(value)
    elif isinstance(value, str) and value.strip():
        text = value.strip()
        sign = text[0] in "+-"
        if not text[1 if sign else 0:].isdigit():
            raise DeskRuleError("Quantity must be a whole number of contracts")
        quantity = int(text)
    else:
        raise DeskRuleError("Quantity must be a whole number of contracts")
    if abs(quantity) > MAX_ABS_CONTRACTS:
        raise DeskRuleError(f"Quantity {quantity} is larger than {MAX_ABS_CONTRACTS} contracts")
    return quantity


def as_number(value: Any) -> int | float:
    """A stored quantity as JSON-friendly int (whole) or float."""
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return 0
    return int(number) if number == number.to_integral_value() else float(number)


def plan_changes(
    current: Mapping[str, Any], edits: Iterable[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """The desk's edits as {"symbol", "from", "to"} changes to the proposal.

    `current` maps each symbol of the seeded qt_proposal book to its quantity.
    An edit to the quantity a symbol already has is dropped; a new symbol at
    zero is dropped (there is nothing to flatten). No change at all refuses.
    """
    if edits is None or isinstance(edits, (str, bytes, Mapping)):
        raise DeskRuleError("changes must be a list of {symbol, quantity}")
    changes: list[dict[str, Any]] = []
    seen: set[str] = set()
    for edit in edits:
        if not isinstance(edit, Mapping):
            raise DeskRuleError("Each change must be an object with symbol and quantity")
        symbol = edit.get("symbol")
        if not isinstance(symbol, str) or not symbol.strip():
            raise DeskRuleError("Each change needs a symbol")
        symbol = symbol.strip()
        if symbol in seen:
            raise DeskRuleError(f"{symbol} is changed twice")
        seen.add(symbol)
        to = parse_contracts(edit.get("quantity"))
        held = symbol in current
        before = as_number(current[symbol]) if held else 0
        if to == before:
            continue
        changes.append({"symbol": symbol, "from": before, "to": to})
    if not changes:
        raise DeskRuleError("No quantity changed")
    return changes


def token_hash(token: str) -> str:
    """sha256 hex of a one-time approval token, as the engine stores it."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def asked_vs_given(
    proposal: Iterable[Mapping[str, Any]], qt: Iterable[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Per symbol: what the desk asked (qt_proposal) against what the engine
    gave back (qt), with the step that moved it (positions.moved_by)."""
    asked = {row["symbol"]: row for row in proposal}
    given = {row["symbol"]: row for row in qt}
    rows = []
    for symbol in sorted(set(asked) | set(given)):
        a = as_number(asked[symbol]["quantity"]) if symbol in asked else None
        g = as_number(given[symbol]["quantity"]) if symbol in given else None
        moved_by = given[symbol].get("moved_by") if symbol in given else None
        rows.append(
            {
                "symbol": symbol,
                "asked": a,
                "given": g,
                "moved_by": moved_by,
                "differs": (a or 0) != (g or 0),
            }
        )
    return rows


def three_books(
    system: Iterable[Mapping[str, Any]],
    proposal: Iterable[Mapping[str, Any]],
    qt: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Per symbol: the model book (system), the desk's request (qt_proposal)
    and the current qt book, for the override approval page."""
    books = [{row["symbol"]: row for row in rows} for rows in (system, proposal, qt)]
    rows = []
    for symbol in sorted(set().union(*books)):
        model, asked, given = (
            as_number(b[symbol]["quantity"]) if symbol in b else None for b in books
        )
        rows.append(
            {
                "symbol": symbol,
                "model": model,
                "asked": asked,
                "given": given,
                "moved_by": books[2][symbol].get("moved_by") if symbol in books[2] else None,
            }
        )
    return rows
