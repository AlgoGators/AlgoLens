"""Rules for which portfolio a strategy belongs to.

Pure domain logic: no database, no Flask. `portfolio_id` has always scoped every
read in this app, but until now nothing could set it -- a strategy was assigned
to a portfolio by hand-editing a database row.

The rule that matters is not "can this string be written". It is that moving a
LIVE strategy between portfolios makes both portfolios' histories discontinuous.
Yesterday's equity curve for the old portfolio includes this strategy; today's
does not. Every number computed across that boundary -- cumulative return, the
qt/system/benchmark attribution, drawdown -- silently spans two different books.

So reassignment is not forbidden, but it is not free either. It follows the same
shape as the risk gate: the caller is told what it will cost, and must come back
with an explicit acknowledgement before it happens. Compare
RiskAcknowledgementRequired in the application layer.
"""

# A strategy that has never traded has no history to make discontinuous.
LIFECYCLES_WITHOUT_HISTORY = frozenset({"incubating"})

# Retired strategies are frozen records. Moving one rewrites a closed book.
LIFECYCLES_FROZEN = frozenset({"retired"})

MAX_PORTFOLIO_ID_LENGTH = 64


class AssignmentValidationError(Exception):
    """Bad input from the caller. Maps to HTTP 400.

    Carries a stable `code`; the HTTP adapter renders the message from the code
    so no exception text reaches a client.
    """

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def normalize_portfolio_id(raw):
    """Validate and canonicalize a target portfolio id."""
    if raw is None:
        raise AssignmentValidationError(
            "missing_portfolio_id", "Field 'portfolio_id' is required"
        )
    if not isinstance(raw, str):
        raise AssignmentValidationError(
            "portfolio_id_not_a_string", "Field 'portfolio_id' must be a string"
        )

    portfolio_id = raw.strip().upper()
    if not portfolio_id:
        raise AssignmentValidationError(
            "empty_portfolio_id", "Field 'portfolio_id' must not be empty"
        )
    if len(portfolio_id) > MAX_PORTFOLIO_ID_LENGTH:
        raise AssignmentValidationError(
            "portfolio_id_too_long",
            f"Field 'portfolio_id' must be at most {MAX_PORTFOLIO_ID_LENGTH} characters",
        )
    # Kept deliberately narrow: this value is a grouping key that appears in
    # audit rows and engine config, not free text.
    if not all(ch.isalnum() or ch in "_-" for ch in portfolio_id):
        raise AssignmentValidationError(
            "portfolio_id_invalid_characters",
            "Field 'portfolio_id' may contain only letters, digits, underscores and hyphens",
        )
    return portfolio_id


def evaluate_assignment(current, target_portfolio_id):
    """What moving this strategy to `target_portfolio_id` would cost.

    `current` is the registry row. Returns a verdict dict; raises only for input
    the caller could have avoided.
    """
    if current is None:
        raise AssignmentValidationError("strategy_not_found", "Strategy not found")

    lifecycle = (current.get("lifecycle") or "live").strip().lower()
    from_portfolio_id = current.get("portfolio_id")

    if lifecycle in LIFECYCLES_FROZEN:
        raise AssignmentValidationError(
            "strategy_retired",
            "A retired strategy cannot be reassigned: its book is closed and "
            "moving it would rewrite history that has already been reported",
        )

    if from_portfolio_id == target_portfolio_id:
        return {
            "changed": False,
            "requires_acknowledgement": False,
            "from_portfolio_id": from_portfolio_id,
            "to_portfolio_id": target_portfolio_id,
            "consequences": [],
        }

    # No trading history means nothing to break.
    if lifecycle in LIFECYCLES_WITHOUT_HISTORY:
        return {
            "changed": True,
            "requires_acknowledgement": False,
            "from_portfolio_id": from_portfolio_id,
            "to_portfolio_id": target_portfolio_id,
            "consequences": [],
        }

    return {
        "changed": True,
        "requires_acknowledgement": True,
        "from_portfolio_id": from_portfolio_id,
        "to_portfolio_id": target_portfolio_id,
        "consequences": [
            {
                "code": "history_discontinuity",
                "message": (
                    f"{from_portfolio_id} loses this strategy's history from today and "
                    f"{target_portfolio_id} gains it. Neither portfolio's cumulative "
                    f"return, drawdown or qt/system/benchmark attribution will be "
                    f"comparable across the move."
                ),
            },
            {
                "code": "engine_config_drift",
                "message": (
                    "The engine keys risk limits and position rows on "
                    "(strategy_id, portfolio_id). Until it publishes limits for "
                    f"{target_portfolio_id}, edits to this strategy will record "
                    "'not checked' rather than being risk-gated."
                ),
            },
        ],
    }


def build_assignment_audit(current, verdict, user_id, reason, acknowledged):
    """The append-only record of a reassignment.

    Mirrors position_overrides: who, when, before, after, why, and whether a
    warning was overridden. A move with no record is indistinguishable from a
    database accident when read back months later.
    """
    return {
        "strategy_id": current["id"],
        "user_id": user_id,
        "from_portfolio_id": verdict["from_portfolio_id"],
        "to_portfolio_id": verdict["to_portfolio_id"],
        "lifecycle_at_move": (current.get("lifecycle") or "live"),
        "reason": reason,
        "consequences": verdict["consequences"],
        "acknowledged": bool(acknowledged),
    }


# ---------------------------------------------------------------------------
# Books
#
# A "book" is a portfolio. Until now one existed only as a distinct portfolio_id
# on strategy_registry, which means an empty book could not exist -- you could
# not define a book and then decide what goes in it. Declaring them separately
# makes that possible, and gives a book a human name and a description.
#
# A declared book and a book that is merely in use are both real. The listing
# unions them, so a book created before this feature existed does not vanish.
# ---------------------------------------------------------------------------

MAX_BOOK_NAME_LENGTH = 120


def validate_book(payload):
    """Normalize and check a new book definition."""
    if not isinstance(payload, dict):
        raise AssignmentValidationError(
            "not_an_object", "Request body must be a JSON object"
        )

    portfolio_id = normalize_portfolio_id(payload.get("portfolio_id"))

    raw_name = payload.get("name")
    name = str(raw_name).strip() if raw_name is not None else ""
    if not name:
        # Default to the id rather than refusing: the id is already a usable
        # label, and forcing a second field adds friction for no safety gain.
        name = portfolio_id
    if len(name) > MAX_BOOK_NAME_LENGTH:
        raise AssignmentValidationError(
            "book_name_too_long",
            f"Field 'name' must be at most {MAX_BOOK_NAME_LENGTH} characters",
        )

    raw_description = payload.get("description")
    description = str(raw_description).strip() if raw_description is not None else ""

    return {
        "portfolio_id": portfolio_id,
        "name": name,
        "description": description,
    }


def merge_books(declared, in_use):
    """Every book, whether declared or merely occupied.

    `declared` are rows from the books table; `in_use` are the distinct
    portfolio_ids found on strategy_registry. A book can be either, or both:

      - declared and empty      -> a book waiting to be filled
      - in use but not declared -> predates this feature, or was created by the
                                   engine; must still appear
      - both                    -> the normal case

    Declared metadata wins where it exists, because someone typed it.
    """
    by_id = {}
    for row in declared:
        by_id[row["portfolio_id"]] = {
            "portfolio_id": row["portfolio_id"],
            "name": row.get("name") or row["portfolio_id"],
            "description": row.get("description") or "",
            "declared": True,
        }
    for portfolio_id in in_use:
        if portfolio_id not in by_id:
            by_id[portfolio_id] = {
                "portfolio_id": portfolio_id,
                "name": portfolio_id,
                "description": "",
                "declared": False,
            }
    return sorted(by_id.values(), key=lambda b: b["portfolio_id"])


# ---------------------------------------------------------------------------
# Membership: a strategy can be in more than one book
#
# The read side already supports this. positions, equity_curve and live_results
# are all keyed on (strategy, portfolio) pairs, so the same strategy running in
# two books produces two independent sets of rows. The only thing that forced
# one book per strategy was the single portfolio_id column on strategy_registry.
#
# That column stays, as the PRIMARY book -- the one used wherever a single
# answer is needed, and the one the engine reads. Membership is additive on top.
#
# The gate moves. ADDING a strategy to another book breaks nothing: the books it
# is already in keep it, and their histories stay continuous. REMOVING it from a
# book is the destructive half -- that book loses the strategy from today, and
# every number it reports spans two different compositions.
# ---------------------------------------------------------------------------


def evaluate_membership_add(strategy, portfolio_id, current_books):
    """Adding a strategy to a book. Free, but not always allowed."""
    if strategy is None:
        raise AssignmentValidationError("strategy_not_found", "Strategy not found")

    lifecycle = (strategy.get("lifecycle") or "live").strip().lower()
    if lifecycle in LIFECYCLES_FROZEN:
        raise AssignmentValidationError(
            "strategy_retired",
            "A retired strategy cannot be added to a book: its book is closed and "
            "doing so would rewrite history that has already been reported",
        )

    if portfolio_id in current_books:
        return {"changed": False, "requires_acknowledgement": False, "consequences": []}

    return {
        "changed": True,
        # Nothing loses anything. The engine simply starts producing a second
        # set of rows for the new pairing.
        "requires_acknowledgement": False,
        "consequences": [],
    }


def evaluate_membership_remove(strategy, portfolio_id, current_books):
    """Removing a strategy from a book. This is the destructive direction."""
    if strategy is None:
        raise AssignmentValidationError("strategy_not_found", "Strategy not found")

    lifecycle = (strategy.get("lifecycle") or "live").strip().lower()
    if lifecycle in LIFECYCLES_FROZEN:
        raise AssignmentValidationError(
            "strategy_retired",
            "A retired strategy cannot be removed from a book: its book is closed "
            "and doing so would rewrite history that has already been reported",
        )

    if portfolio_id not in current_books:
        return {"changed": False, "requires_acknowledgement": False, "consequences": []}

    # A strategy that belongs to nothing is unreachable: every read in this app
    # is scoped by (strategy, portfolio), so it would have no rows anywhere and
    # would simply disappear. Refuse rather than strand it.
    if len(current_books) <= 1:
        raise AssignmentValidationError(
            "last_book",
            "A strategy must belong to at least one book. Add it to another book "
            "before removing it from this one.",
        )

    if lifecycle in LIFECYCLES_WITHOUT_HISTORY:
        return {"changed": True, "requires_acknowledgement": False, "consequences": []}

    return {
        "changed": True,
        "requires_acknowledgement": True,
        "consequences": [
            {
                "code": "history_discontinuity",
                "message": (
                    f"{portfolio_id} loses this strategy's contribution from today. "
                    f"Its cumulative return, drawdown and qt/system/benchmark "
                    f"attribution will not be comparable across the change."
                ),
            }
        ],
    }


def build_membership_audit(strategy, portfolio_id, action, user_id, reason, acknowledged):
    """Append-only record of a membership change.

    Reuses the assignment audit shape so both kinds of change read back from one
    table: an add has no `from`, a removal has no `to`.
    """
    return {
        "strategy_id": strategy["id"],
        "user_id": user_id,
        "from_portfolio_id": portfolio_id if action == "remove" else None,
        "to_portfolio_id": portfolio_id if action == "add" else None,
        "lifecycle_at_move": (strategy.get("lifecycle") or "live"),
        "reason": reason,
        "consequences": [],
        "acknowledged": bool(acknowledged),
    }
