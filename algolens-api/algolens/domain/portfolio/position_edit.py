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
from algolens.domain.portfolio.portfolio_assignment import match_book

QT_STREAM = "qt"

# Raised when an edit does not say which book it means and the strategy is in
# more than one. See resolve_target_book.
class AmbiguousBook(Exception):
    """The edit could land in more than one book, so it lands in none.

    A strategy in several books has a separate set of positions, a separate risk
    envelope and possibly a different universe in each. Defaulting to the
    primary book silently wrote to the wrong one: a symbol that existed only in
    another book was created fresh in the primary, checked against the primary's
    envelope, and recorded as passed.
    """

    def __init__(self, strategy_id, books):
        super().__init__(
            f"{strategy_id} belongs to {len(books)} books; the edit must say which"
        )
        self.strategy_id = strategy_id
        self.books = list(books)


def resolve_target_book(strategy_id, requested, books, primary):
    """Which book this edit is for.

    Named explicitly wins, provided the strategy is actually in it. Otherwise a
    strategy in exactly one book needs no ceremony. A strategy in several and no
    stated book is refused rather than guessed -- the guess is unobservable in
    the response and permanent in the ledger.
    """
    known = list(books) or ([primary] if primary else [])
    if not known:
        # A registry row with a blank primary and no memberships. There is no
        # candidate at all, which is a different failure from too many: the
        # client cannot fix it by naming one.
        raise PositionValidationError(
            "strategy_has_no_book",
            f"{strategy_id} is not in any book, so there is nothing to write into",
        )
    if requested is not None:
        found = match_book(requested, known)
        if found is None:
            raise PositionValidationError(
                "not_a_member_of_book",
                f"{strategy_id} does not belong to {requested}",
            )
        return found
    if len(known) == 1:
        return known[0]
    raise AmbiguousBook(strategy_id, known)

REQUIRED_FIELDS = ("strategy_id", "symbol", "quantity", "reason")


class PositionValidationError(Exception):
    """Bad input from the caller. Maps to HTTP 400.

    Carries a stable `code` as well as the human message. The HTTP adapter
    renders the response from the code rather than from this exception, so no
    exception text ever reaches a client -- see VALIDATION_MESSAGES there.
    """

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def validate_position_payload(payload):
    """Normalize and check a proposed position edit.

    Returns a new dict; does not mutate the input.
    """
    if not isinstance(payload, dict):
        raise PositionValidationError(
            "not_an_object", "Request body must be a JSON object"
        )

    if "portfolio_type" in payload:
        raise PositionValidationError(
            "portfolio_type_forbidden",
            "portfolio_type may not be supplied by the caller: this endpoint "
            "writes the qt stream only. Other portfolio types are read-only.",
        )

    for field in REQUIRED_FIELDS:
        if field not in payload or payload[field] is None:
            raise PositionValidationError(
                f"missing_{field}", f"Missing required field: {field}"
            )

    symbol = str(payload["symbol"]).strip().upper()
    if not symbol:
        raise PositionValidationError(
            "empty_symbol", "Field 'symbol' must not be empty"
        )

    strategy_id = str(payload["strategy_id"]).strip()
    if not strategy_id:
        raise PositionValidationError(
            "empty_strategy_id", "Field 'strategy_id' must not be empty"
        )

    reason = str(payload["reason"]).strip()
    if not reason:
        raise PositionValidationError(
            "empty_reason",
            "Field 'reason' must not be empty: an override with no stated reason "
            "is indistinguishable from an accident when read back months later",
        )

    quantity = payload["quantity"]
    # bool is a subclass of int in Python; True would otherwise become 1 contract.
    if isinstance(quantity, bool) or not isinstance(quantity, Real):
        raise PositionValidationError(
            "quantity_not_a_number", "Field 'quantity' must be a number"
        )

    # Optional, and only meaningful once a strategy can be in several books.
    # Validated here so a malformed value is rejected the same way as any other
    # field rather than reaching a query.
    raw_book = payload.get("portfolio_id")
    portfolio_id = None
    if raw_book is not None:
        if not isinstance(raw_book, str):
            raise PositionValidationError(
                "portfolio_id_not_a_string", "Field 'portfolio_id' must be a string"
            )
        portfolio_id = raw_book.strip().upper()
        if not portfolio_id:
            raise PositionValidationError(
                "empty_portfolio_id", "Field 'portfolio_id' must not be empty"
            )

    average_price = payload.get("average_price")
    if average_price is not None:
        if isinstance(average_price, bool) or not isinstance(average_price, Real):
            raise PositionValidationError(
                "price_not_a_number", "Field 'average_price' must be a number"
            )
        if average_price < 0:
            raise PositionValidationError(
                "price_negative", "Field 'average_price' must not be negative"
            )

    return {
        "strategy_id": strategy_id,
        "symbol": symbol,
        "quantity": quantity,
        "average_price": average_price,
        "reason": reason,
        "portfolio_id": portfolio_id,
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
    elif before is None:
        # Opening a position with no cost basis. "Leave the price alone" has
        # nothing to leave alone here, and average_price is NOT NULL in the
        # schema the engine ships -- so this reached the database as a
        # constraint violation and a 500. Refuse it where it can be explained.
        raise PositionValidationError(
            "price_required_for_new_position",
            "A new position needs an average price; there is no existing one to keep",
        )
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
    # deliberate: we cannot compute risk for a position we do not know the price of.
    #
    # Coerced to float on purpose. Rows read from Postgres NUMERIC columns arrive
    # as decimal.Decimal, the proposed position arrives as float, and Decimal
    # refuses to add to float. That combination only appears against a real
    # database, which is exactly where this must not fail.
    price = float(position.get("average_price") or 0.0)
    return abs(float(position["quantity"]) * price)


def with_known_price(current_book, proposed):
    """The proposal as the risk check must see it.

    A blank average_price on an edit means "leave it alone" (see
    build_after_state), and the write path honours that. But the risk check was
    handed the raw proposal, so a blank price became a notional of zero and the
    most common edit of all -- change the quantity, keep the price -- sailed
    through every cap unchecked. The price is not unknown; it is on the
    existing row. Use it.
    """
    if proposed.get("average_price") is not None:
        return proposed
    existing = next((p for p in current_book if p["symbol"] == proposed["symbol"]), None)
    if not existing or existing.get("average_price") is None:
        return proposed
    return {**proposed, "average_price": existing["average_price"]}


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
    if envelope is None:
        # Explicitly NOT a pass. An unreachable envelope must be visible in the
        # audit trail as "not checked", never as "checked and fine".
        #
        # `is None`, not falsiness: a published envelope with no limits in it
        # ({}) IS reachable and IS a check, one that finds nothing to breach.
        # Recording that as "not checked" would misreport a deliberate
        # no-limits configuration as an outage.
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
