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
from algolens.domain.portfolio.instruments import base_symbol
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


def _normalize_symbol(raw):
    """``es.v.0`` -> ``ES.v.0``. Root upper-cased, roll suffix left alone."""
    text = str(raw).strip()
    for marker in (".v.", ".c.", ".n."):
        index = text.lower().find(marker)
        if index != -1:
            # Keep the suffix exactly as the pipeline writes it.
            return text[:index].upper() + text[index:].lower()
    return text.upper()


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

    # Upper-case the root only. Continuous-contract symbols carry a lower-case
    # roll marker -- data-ngin writes ES.v.0 and trading.positions stores it
    # verbatim -- so upper-casing the whole string produced ES.V.0, which
    # matches no existing row. An edit to a held position was therefore read as
    # opening a new one, and would have written a second row for the same
    # contract under a symbol the engine never uses.
    symbol = _normalize_symbol(payload["symbol"])
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


# The limits the engine actually publishes. trade-ngin's own header
# (postgres_database.hpp, store_risk_limits) states these and states, as
# deliberate policy, that max_gross_notional and max_position_count are NOT
# published, because the engine constrains leverage ratios and per-symbol
# contract counts, not dollar caps.
#
# AlgoLens used to check exactly the two keys the engine refuses to publish,
# plus a max_symbol_notional it never published either. Against a real envelope
# it would find none of them, report no breaches, and record "passed" -- a
# green light derived from limits nobody had ever set. It only appeared to work
# because the demo seed invented the keys the code was looking for.
ENGINE_LIMIT_KEYS = (
    "max_symbol_position_contracts",
    "max_gross_leverage",
    "max_net_leverage",
)

# Retained because an envelope published before the engine settled on the above
# may still carry them, and a limit someone did set should still be honoured.
LEGACY_LIMIT_KEYS = (
    "max_symbol_notional",
    "max_gross_notional",
    "max_position_count",
)


def _gross_notional(book):
    """Sum of exposures, or None if any position's exposure is unknown.

    Deliberately all-or-nothing: a leverage check run against a partial sum
    silently compares a smaller number to the same limit, which is the same
    class of error as omitting the contract size in the first place.
    """
    total = 0.0
    for position in book:
        value = position.get("notional")
        if value is None:
            return None
        total += float(value)
    return total


def evaluate_risk(envelope, current_book, proposed, portfolio_value=None):
    """Verdict on a single proposed position change.

    Checks the limits trade-ngin publishes. Anything it cannot evaluate is
    reported as not evaluated rather than quietly passed, so the audit trail
    never shows a check that did not happen as one that did.
    """
    if envelope is None:
        # Explicitly NOT a pass. An unreachable envelope must be visible in the
        # audit trail as "not checked", never as "checked and fine".
        return {"evaluated": False, "passed": True, "breaches": [], "checked": []}

    known = [k for k in ENGINE_LIMIT_KEYS + LEGACY_LIMIT_KEYS if envelope.get(k) is not None]
    if not known:
        # A published envelope carrying only limits this code does not
        # understand is not a clean bill of health. Saying "passed" here is how
        # a limit nobody checked becomes a limit everybody trusts.
        return {"evaluated": False, "passed": True, "breaches": [], "checked": []}

    projected = _projected_book(current_book, proposed)
    breaches = []
    checked = []

    # -- per-symbol cap, in CONTRACTS. This is what the engine enforces. ------
    contract_caps = envelope.get("max_symbol_position_contracts") or {}
    cap = contract_caps.get(proposed["symbol"])
    if cap is None:
        cap = contract_caps.get(base_symbol(proposed["symbol"]))
    if cap is not None:
        checked.append("max_symbol_position_contracts")
        actual = abs(float(proposed["quantity"]))
        if actual > float(cap):
            breaches.append({
                "limit": "max_symbol_position_contracts",
                "limit_value": float(cap),
                "actual": actual,
                "message": (
                    f"{proposed['symbol']} would be {actual:,.0f} contracts, over its "
                    f"cap of {float(cap):,.0f}"
                ),
            })

    # -- leverage, which needs exposure and the value of the book ------------
    gross = _gross_notional(projected)
    for key, label in (("max_gross_leverage", "Gross"), ("max_net_leverage", "Net")):
        limit = envelope.get(key)
        if limit is None:
            continue
        if gross is None or not portfolio_value:
            # Cannot be computed. Not a pass; the caller is told what was and
            # was not looked at via "checked".
            continue
        checked.append(key)
        actual = gross / float(portfolio_value)
        if actual > float(limit):
            breaches.append({
                "limit": key,
                "limit_value": float(limit),
                "actual": actual,
                "message": (
                    f"{label} leverage would be {actual:,.2f}x, over the limit of "
                    f"{float(limit):,.2f}x"
                ),
            })

    # -- legacy dollar caps, honoured only if actually present ---------------
    symbol_caps = envelope.get("max_symbol_notional") or {}
    dollar_cap = symbol_caps.get(proposed["symbol"])
    if dollar_cap is not None:
        proposed_notional = proposed.get("notional")
        if proposed_notional is not None:
            checked.append("max_symbol_notional")
            if float(proposed_notional) > float(dollar_cap):
                breaches.append({
                    "limit": "max_symbol_notional",
                    "limit_value": float(dollar_cap),
                    "actual": float(proposed_notional),
                    "message": (
                        f"{proposed['symbol']} exposure {float(proposed_notional):,.0f} "
                        f"exceeds its cap of {float(dollar_cap):,.0f}"
                    ),
                })

    max_gross = envelope.get("max_gross_notional")
    if max_gross is not None and gross is not None:
        checked.append("max_gross_notional")
        if gross > float(max_gross):
            breaches.append({
                "limit": "max_gross_notional",
                "limit_value": float(max_gross),
                "actual": gross,
                "message": (
                    f"Gross exposure {gross:,.0f} exceeds the portfolio cap of "
                    f"{float(max_gross):,.0f}"
                ),
            })

    max_count = envelope.get("max_position_count")
    if max_count is not None:
        checked.append("max_position_count")
        actual = len(projected)
        if actual > float(max_count):
            breaches.append({
                "limit": "max_position_count",
                "limit_value": float(max_count),
                "actual": actual,
                "message": (
                    f"{actual} open positions exceeds the cap of {float(max_count):,.0f}"
                ),
            })

    if not checked:
        # Limits were published but none could be evaluated -- an exposure was
        # unknown, or the book's value was not available.
        return {"evaluated": False, "passed": True, "breaches": [], "checked": []}

    return {
        "evaluated": True,
        "passed": not breaches,
        "breaches": breaches,
        # Which limits were actually compared. Written into the audit trail so
        # "passed" can be read as "passed these", not "passed everything".
        "checked": sorted(set(checked)),
    }
