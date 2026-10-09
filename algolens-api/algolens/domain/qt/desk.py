"""QT desk rules: the command log and the desk's quantity edits.

Pure rules from docs/design/qt-contract.md (trade-ngin) sections 4 and 7 and
the master rulings 13, 14 and 16. No database, no HTTP.
"""

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from datetime import datetime
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


# A typed quantity: ASCII digits with an optional sign. str.isdigit() also
# accepts "²" and other Unicode digits that int() then refuses; the length cap
# keeps int() far from its digit limit.
_WHOLE_CONTRACTS = re.compile(r"[+-]?[0-9]{1,15}")


class DeskRuleError(ValueError):
    """A desk request breaks a rule; the message says which, for the user."""


class DeskStaleError(Exception):
    """The proposal changed since the desk loaded it (optimistic concurrency).
    `symbols` lists the symbols whose quantity is no longer what was shown."""

    def __init__(self, symbols: list[str]):
        self.symbols = list(symbols)
        super().__init__(
            "The proposal changed since you loaded it ("
            + ", ".join(self.symbols)
            + "); reload and edit again"
        )


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
    elif isinstance(value, str) and _WHOLE_CONTRACTS.fullmatch(value.strip()):
        quantity = int(value.strip())
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


def _shown_quantity(symbol: str, value: Any) -> Decimal:
    if value is None:
        return Decimal(0)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DeskRuleError(f"{symbol}: expected must be the quantity shown (a number) or null")
    return Decimal(str(value))


def stale_symbols(current: Mapping[str, Any], edits: Iterable[Mapping[str, Any]]) -> list[str]:
    """Symbols whose proposal quantity is no longer the one the desk was shown.

    Every edit carries `expected`: the quantity the form showed for that
    symbol (null, or 0, for a symbol not in the proposal). A symbol missing
    from `current` counts as 0.
    """
    stale = []
    for edit in edits:
        if not isinstance(edit, Mapping) or not isinstance(edit.get("symbol"), str):
            continue  # plan_changes reports the shape error
        symbol = edit["symbol"].strip()
        if "expected" not in edit:
            raise DeskRuleError(f"{symbol}: the quantity shown (expected) is required")
        shown = _shown_quantity(symbol, edit["expected"])
        now = Decimal(str(current.get(symbol, 0)))
        if now != shown:
            stale.append(symbol)
    return stale


def plan_desk_edit(
    current: Mapping[str, Any], edits: Iterable[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """plan_changes, after refusing (DeskStaleError) an edit made against
    quantities that have changed since the desk loaded them."""
    if edits is None or isinstance(edits, (str, bytes, Mapping)):
        raise DeskRuleError("changes must be a list of {symbol, quantity, expected}")
    edits = list(edits)
    stale = stale_symbols(current, edits)
    if stale:
        raise DeskStaleError(stale)
    return plan_changes(current, edits)


# --- the override snapshot (contract C1) --------------------------------------


def proposal_snapshot(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Every qt_proposal row of a day (zero rows included) as
    {"strategy_name", "symbol", "quantity"}, keys in that order, quantity an
    integer, sorted by (strategy_name, symbol) (quantity breaks a tie, which
    the table's key otherwise allows across strategy_ids)."""
    snapshot = []
    for row in rows:
        try:
            quantity = Decimal(str(row["quantity"]))
        except (InvalidOperation, ValueError):
            raise DeskRuleError(f"{row['symbol']} has no numeric quantity") from None
        if not quantity.is_finite() or quantity != quantity.to_integral_value():
            raise DeskRuleError(f"{row['symbol']} holds a fractional quantity ({row['quantity']})")
        snapshot.append(
            {
                "strategy_name": str(row["strategy_name"]),
                "symbol": str(row["symbol"]),
                "quantity": int(quantity),
            }
        )
    snapshot.sort(key=lambda r: (r["strategy_name"], r["symbol"], r["quantity"]))
    return snapshot


def snapshot_bytes(snapshot: list[dict[str, Any]]) -> bytes:
    """The exact bytes the engine hashes too: no spaces, ASCII-escaped."""
    return json.dumps(snapshot, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def snapshot_sha256(snapshot: list[dict[str, Any]]) -> str:
    return hashlib.sha256(snapshot_bytes(snapshot)).hexdigest()


def override_payload(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """payload of an override_request: the snapshot and its hash."""
    snapshot = proposal_snapshot(rows)
    return {"proposal": snapshot, "proposal_sha256": snapshot_sha256(snapshot)}


def request_matches(request: Mapping[str, Any], current_sha256: str | None) -> bool:
    """Whether a request's snapshot is the proposal as it is now. A request
    without a snapshot (made before C1) never matches."""
    payload = request.get("payload")
    recorded = payload.get("proposal_sha256") if isinstance(payload, Mapping) else None
    return isinstance(recorded, str) and recorded == current_sha256


# A decision in one of these states settles its request (C2).
DECIDING_STATUSES = (PENDING, RUNNING, DONE)


def open_override_request(
    commands: Iterable[Mapping[str, Any]], now: datetime, current_sha256: str | None
) -> Mapping[str, Any] | None:
    """The day's override request still in play, or None (C2).

    A request is open while it is pending or running, and once e-mailed
    (done) while its link is valid, nobody has decided it and it still
    describes the current proposal. A request whose snapshot no longer
    matches the proposal can never be approved, so it does not block a new one.
    """
    commands = list(commands)
    deciding = {
        c.get("parent_id")
        for c in commands
        if c["kind"] == OVERRIDE_DECISION and c["status"] in DECIDING_STATUSES
    }
    for command in commands:
        if command["kind"] != OVERRIDE_REQUEST:
            continue
        if command["status"] in OPEN_STATUSES:
            return command
        expires = command.get("token_expires_at")
        if (
            command["status"] == DONE
            and command["id"] not in deciding
            and expires is not None
            and expires > now
            and request_matches(command, current_sha256)
        ):
            return command
    return None


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
