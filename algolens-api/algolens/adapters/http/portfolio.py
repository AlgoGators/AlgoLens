"""Portfolio HTTP routes."""

from datetime import datetime, timezone
from functools import wraps
import time

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import get_jwt, get_jwt_identity, jwt_required

from algolens.adapters.serializers.portfolio import (
    serialize_assignment_history,
    serialize_assignment_result,
    serialize_book_list,
    serialize_incubating_strategy_list,
    serialize_incubation_performance,
    serialize_portfolio_list,
    serialize_strategy_detail,
    serialize_strategy_list,
)
from algolens.application.portfolio.ports import (
    BookNotEmpty,
    IncubationError,
    IncubationStorageError,
    MembershipAcknowledgementRequired,
    PortfolioReassignmentAcknowledgementRequired,
    RiskAcknowledgementRequired,
    StrategyNameUnresolved,
    StrategyNotInRegistry,
)
from algolens.application.portfolio.use_cases import (
    ChangeBookMembership,
    CreateBook,
    DeleteBook,
    GetIncubationPerformance,
    GetStrategyDetail,
    ListAssignmentHistory,
    ListBooks,
    ListIncubatingStrategies,
    ListPortfolios,
    ListPositionOverrides,
    ListStrategies,
    PreviewPortfolioAssignment,
    PromoteToLive,
    ReassignStrategyPortfolio,
    RetireStrategy,
    StartIncubation,
    StrategyDataNotFound,
    StrategyNotFound,
    UpsertQtPosition,
)
from algolens.domain.portfolio.position_edit import AmbiguousBook, PositionValidationError
from algolens.domain.portfolio.portfolio_assignment import AssignmentValidationError
from algolens.infrastructure.config.dependencies import create_portfolio_dependencies

portfolio_bp = Blueprint("portfolio", __name__)

# Rendered from PositionValidationError.code rather than from the exception
# itself, so no exception text can reach a client (CodeQL py/stack-trace-
# exposure). Every message here is authored, not derived.
ASSIGNMENT_MESSAGES = {
    "not_a_member_of_book": "That strategy does not belong to the book named",
    "missing_portfolio_id": "Field 'portfolio_id' is required",
    "portfolio_id_not_a_string": "Field 'portfolio_id' must be a string",
    "empty_portfolio_id": "Field 'portfolio_id' must not be empty",
    "portfolio_id_too_long": "Field 'portfolio_id' is too long",
    "portfolio_id_invalid_characters": (
        "Field 'portfolio_id' may contain only letters, digits, underscores and hyphens"
    ),
    "strategy_not_found": "Strategy not found",
    "book_name_too_long": "Field 'name' is too long",
    "unknown_action": "Action must be 'add' or 'remove'",
    "last_book": (
        "A strategy must belong to at least one book. Add it to another book "
        "before removing it from this one."
    ),
    "not_an_object": "Request body must be a JSON object",
    "strategy_retired": (
        "A retired strategy cannot be reassigned: its book is closed and moving it "
        "would rewrite history that has already been reported"
    ),
}

VALIDATION_MESSAGES = {
    "not_an_object": "Request body must be a JSON object",
    "portfolio_type_forbidden": (
        "portfolio_type may not be supplied by the caller: this endpoint "
        "writes the qt stream only. Other portfolio types are read-only."
    ),
    "missing_strategy_id": "Missing required field: strategy_id",
    "missing_symbol": "Missing required field: symbol",
    "missing_quantity": "Missing required field: quantity",
    "missing_reason": "Missing required field: reason",
    "empty_symbol": "Field 'symbol' must not be empty",
    "empty_strategy_id": "Field 'strategy_id' must not be empty",
    "empty_reason": (
        "Field 'reason' must not be empty: an override with no stated reason "
        "is indistinguishable from an accident when read back months later"
    ),
    "quantity_not_a_number": "Field 'quantity' must be a number",
    "portfolio_id_not_a_string": "Field 'portfolio_id' must be a string",
    "empty_portfolio_id": "Field 'portfolio_id' must not be empty",
    "not_a_member_of_book": "That strategy does not belong to the book named",
    "strategy_has_no_book": "That strategy is not in any book; nothing to write into",
    "price_not_a_number": "Field 'average_price' must be a number",
    "price_negative": "Field 'average_price' must not be negative",
}

# Incubation is an internal member-only surface. Default-deny: an unrecognised
# or absent role is refused, so new roles stay locked out until explicitly added.
INTERNAL_ROLES = frozenset({"admin", "general_member"})


def _portfolio_dependencies():
    return create_portfolio_dependencies()


def internal_only(fn):
    """Refuse anyone whose JWT role is not an internal one."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        role = get_jwt().get("role")
        if role not in INTERNAL_ROLES:
            current_app.logger.warning(
                "Refused %s to %s: role %r is not internal",
                request.method,
                request.path,
                role,
            )
            return jsonify({"error": "Insufficient permissions"}), 403
        return fn(*args, **kwargs)

    return wrapper


def _request_user_id():
    user_id = get_jwt_identity()
    if user_id is None:
        raise IncubationError("Invalid user identity in token")
    return str(user_id)


def _incubation_error_status(exc):
    """404 for a missing strategy, 400 for a lifecycle rule.

    Decided on the exception type. This used to search the message for the words
    "not found", which meant a reason string containing them silently turned a
    400 into a 404.
    """
    return 404 if isinstance(exc, StrategyNotInRegistry) else 400


@portfolio_bp.route("/strategy/<strategy_id>", methods=["GET"])
@jwt_required()
def get_strategy(strategy_id):
    start = time.perf_counter()
    try:
        current_app.logger.info("Fetching strategy: %s", strategy_id)
        registry, reader = _portfolio_dependencies()
        # Optional. Omitted means the primary book, which is what every
        # existing caller gets. Named means that book, provided the strategy
        # is in it.
        strategy = GetStrategyDetail(registry, reader).execute(
            strategy_id, request.args.get("portfolio_id")
        )
        elapsed_ms = (time.perf_counter() - start) * 1000
        current_app.logger.info(
            "[PORTFOLIO_TIMING] detail strategy_id=%s elapsed_ms=%.0f",
            strategy_id,
            elapsed_ms,
        )
        return jsonify(serialize_strategy_detail(strategy)), 200
    except AssignmentValidationError as exc:
        message = ASSIGNMENT_MESSAGES.get(exc.code, str(exc))
        return jsonify({"error": message, "code": exc.code}), 400
    except StrategyNotFound:
        return jsonify({"error": "Strategy not found"}), 404
    except StrategyDataNotFound as exc:
        book = getattr(exc, "portfolio_id", None)
        if book:
            return (
                jsonify(
                    {
                        "error": (
                            f"The engine has not published any results for this "
                            f"strategy in {book} yet."
                        ),
                        "code": "no_data_for_book",
                        "portfolio_id": book,
                    }
                ),
                404,
            )
        return jsonify({"error": "No data found for strategy"}), 404
    except Exception as exc:
        current_app.logger.error(
            "Error fetching strategy %s: %s", strategy_id, str(exc), exc_info=True
        )
        return jsonify({"error": "Failed to fetch strategy"}), 500


@portfolio_bp.route("/strategies", methods=["GET"])
@jwt_required()
def get_all_strategies():
    start = time.perf_counter()
    current_app.logger.info("[STRATEGIES] === /strategies endpoint called ===")

    try:
        registry, reader = _portfolio_dependencies()
        strategies = ListStrategies(registry, reader).execute()
        elapsed_ms = (time.perf_counter() - start) * 1000
        current_app.logger.info("[STRATEGIES] Returning %s strategies", len(strategies))
        current_app.logger.info(
            "[PORTFOLIO_TIMING] strategies count=%s elapsed_ms=%.0f",
            len(strategies),
            elapsed_ms,
        )
        return jsonify(serialize_strategy_list(strategies)), 200
    except Exception as exc:
        current_app.logger.error(
            "[STRATEGIES] Error fetching strategies: %s", str(exc), exc_info=True
        )
        return jsonify({"error": "Failed to fetch strategies"}), 500


@portfolio_bp.route("/incubation", methods=["GET"])
@jwt_required()
@internal_only
def get_incubation_strategies():
    try:
        _registry, reader = _portfolio_dependencies()
        strategies = ListIncubatingStrategies(reader).execute(
            datetime.now(timezone.utc)
        )
        return jsonify(serialize_incubating_strategy_list(strategies)), 200
    except Exception as exc:
        current_app.logger.error(
            "Failed to fetch incubating strategies: %s", str(exc), exc_info=True
        )
        return jsonify({"error": "Failed to fetch incubating strategies"}), 500


@portfolio_bp.route("/incubation/<strategy_id>/performance", methods=["GET"])
@jwt_required()
@internal_only
def get_incubation_perf(strategy_id):
    try:
        _registry, reader = _portfolio_dependencies()
        performance = GetIncubationPerformance(reader).execute(strategy_id)
        return jsonify(serialize_incubation_performance(performance)), 200
    except Exception as exc:
        current_app.logger.error(
            "Failed to fetch incubation performance for %s: %s",
            strategy_id,
            str(exc),
            exc_info=True,
        )
        return jsonify({"error": "Failed to fetch incubation performance"}), 500


@portfolio_bp.route("/incubation/<strategy_id>/start", methods=["POST"])
@jwt_required()
@internal_only
def start_strategy_incubation(strategy_id):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Request body must be a JSON object"}), 400

    if payload.get("mock_capital") is None:
        return jsonify({"error": "Missing required field: mock_capital"}), 400
    if payload.get("reason") is None or not str(payload.get("reason")).strip():
        return jsonify({"error": "Missing required field: reason"}), 400

    try:
        mock_capital = float(payload["mock_capital"])
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid mock_capital: must be a positive number"}), 400

    try:
        _registry, reader = _portfolio_dependencies()
        StartIncubation(reader).execute(
            strategy_id=strategy_id,
            mock_capital=mock_capital,
            reason=str(payload["reason"]),
            user_id=_request_user_id(),
        )
        current_app.logger.info("Started incubation for strategy %s", strategy_id)
        return jsonify({"message": "Incubation started"}), 201
    except IncubationStorageError:
        # Detail is in the server log. The driver message names columns and
        # SQL, and a storage fault is not a client error.
        return jsonify({"error": "Incubation change could not be saved"}), 500
    except IncubationError as exc:
        return jsonify({"error": str(exc)}), _incubation_error_status(exc)
    except Exception as exc:
        current_app.logger.error(
            "Failed to start incubation for %s: %s",
            strategy_id,
            str(exc),
            exc_info=True,
        )
        return jsonify({"error": "Failed to start incubation"}), 500


@portfolio_bp.route("/incubation/<strategy_id>/promote", methods=["POST"])
@jwt_required()
@internal_only
def promote_strategy_to_live(strategy_id):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Request body must be a JSON object"}), 400

    if payload.get("reason") is None or not str(payload.get("reason")).strip():
        return jsonify({"error": "Missing required field: reason"}), 400

    try:
        _registry, reader = _portfolio_dependencies()
        PromoteToLive(reader).execute(
            strategy_id=strategy_id,
            reason=str(payload["reason"]),
            user_id=_request_user_id(),
        )
        current_app.logger.info("Promoted strategy %s to live", strategy_id)
        return jsonify({"message": "Strategy promoted to live"}), 200
    except IncubationStorageError:
        # Detail is in the server log. The driver message names columns and
        # SQL, and a storage fault is not a client error.
        return jsonify({"error": "Incubation change could not be saved"}), 500
    except IncubationError as exc:
        return jsonify({"error": str(exc)}), _incubation_error_status(exc)
    except Exception as exc:
        current_app.logger.error(
            "Failed to promote %s: %s", strategy_id, str(exc), exc_info=True
        )
        return jsonify({"error": "Failed to promote strategy"}), 500


@portfolio_bp.route("/incubation/<strategy_id>/retire", methods=["POST"])
@jwt_required()
@internal_only
def retire_strategy(strategy_id):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Request body must be a JSON object"}), 400

    if payload.get("reason") is None or not str(payload.get("reason")).strip():
        return jsonify({"error": "Missing required field: reason"}), 400

    try:
        _registry, reader = _portfolio_dependencies()
        RetireStrategy(reader).execute(
            strategy_id=strategy_id,
            reason=str(payload["reason"]),
            user_id=_request_user_id(),
        )
        current_app.logger.info("Retired strategy %s", strategy_id)
        return jsonify({"message": "Strategy retired"}), 200
    except IncubationStorageError:
        # Detail is in the server log. The driver message names columns and
        # SQL, and a storage fault is not a client error.
        return jsonify({"error": "Incubation change could not be saved"}), 500
    except IncubationError as exc:
        return jsonify({"error": str(exc)}), _incubation_error_status(exc)
    except Exception as exc:
        current_app.logger.error(
            "Failed to retire %s: %s", strategy_id, str(exc), exc_info=True
        )
        return jsonify({"error": "Failed to retire strategy"}), 500


@portfolio_bp.route("/positions", methods=["POST"])
@jwt_required()
@internal_only
def upsert_position():
    """Create or amend one position in the qt stream.

    A risk breach does not block the write, but it does require the caller to
    come back with acknowledge_risk=true (409 on the first attempt). Every write
    lands in trading.position_overrides in the same transaction.
    """
    payload = request.get_json(silent=True)
    acknowledge = bool((payload or {}).get("acknowledge_risk"))

    # Parse the user_id from the JWT identity defensively.
    user_id = get_jwt_identity()
    if user_id is None:
        return jsonify({"error": "Invalid user identity in token"}), 400

    try:
        registry, reader = _portfolio_dependencies()
        result = UpsertQtPosition(registry, reader).execute(
            payload, user_id=user_id, acknowledge_risk=acknowledge
        )
        return jsonify(result), 201
    except PositionValidationError as exc:
        message = VALIDATION_MESSAGES.get(exc.code, "Invalid request body")
        return jsonify({"error": message, "code": exc.code}), 400
    except StrategyNotFound:
        return jsonify({"error": "Strategy not found"}), 404
    except AmbiguousBook as exc:
        # 409, not 400: the request is well formed, it just cannot be resolved
        # to one book. The client is told which books to choose between.
        return (
            jsonify(
                {
                    "error": (
                        f"{exc.strategy_id} belongs to {len(exc.books)} books. "
                        f"Say which one this edit is for."
                    ),
                    "code": "ambiguous_book",
                    "books": exc.books,
                    "resubmit_with": "portfolio_id",
                }
            ),
            409,
        )
    except RiskAcknowledgementRequired as exc:
        return jsonify(
            {
                "error": "This position breaches a risk limit",
                "risk_check": exc.verdict,
                "resubmit_with": "acknowledge_risk",
            }
        ), 409
    except StrategyNameUnresolved as exc:
        # The detail names internal strategy and portfolio ids, so it is logged
        # rather than returned.
        current_app.logger.error("Strategy name unresolved: %s", exc)
        return jsonify(
            {
                "error": (
                    "The engine has not written any positions for this strategy "
                    "yet, so this edit cannot be attached to a book."
                )
            }
        ), 409
    except Exception:
        current_app.logger.error("Failed to write position", exc_info=True)
        return jsonify({"error": "Failed to write position"}), 500


@portfolio_bp.route("/overrides/<strategy_id>", methods=["GET"])
@jwt_required()
@internal_only
def get_overrides(strategy_id):
    """The audit trail for one strategy, most recent first."""
    try:
        registry, reader = _portfolio_dependencies()
        overrides = ListPositionOverrides(registry, reader).execute(strategy_id)
        return jsonify({"overrides": overrides}), 200
    except StrategyNotFound:
        return jsonify({"error": "Strategy not found"}), 404
    except Exception:
        current_app.logger.error(
            "Failed to fetch overrides for %s", strategy_id, exc_info=True
        )
        return jsonify({"error": "Failed to fetch overrides"}), 500


@portfolio_bp.route("/portfolios", methods=["GET"])
@jwt_required()
def get_portfolios():
    """The strategies grouped by the portfolio they belong to.

    Readable by any authenticated user -- it is the same information the
    strategy list already exposes, only grouped.
    """
    try:
        registry, reader = _portfolio_dependencies()
        return (
            jsonify(serialize_portfolio_list(ListPortfolios(registry, reader).execute())),
            200,
        )
    except Exception as exc:
        current_app.logger.error("Failed to list portfolios: %s", str(exc), exc_info=True)
        return jsonify({"error": "Failed to list portfolios"}), 500


@portfolio_bp.route("/strategies/<strategy_id>/portfolio", methods=["PUT"])
@jwt_required()
@internal_only
def reassign_strategy_portfolio(strategy_id):
    """Move a strategy to another portfolio.

    Returns 409 with the consequences when the move would break history
    continuity and the caller has not acknowledged it -- the same
    resubmit-to-acknowledge shape as a risk breach on a position edit.
    """
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Request body must be a JSON object"}), 400

    try:
        registry, _reader = _portfolio_dependencies()
        result = ReassignStrategyPortfolio(registry).execute(
            strategy_id,
            payload.get("portfolio_id"),
            user_id=_request_user_id(),
            reason=payload.get("reason"),
            acknowledge=bool(payload.get("acknowledge")),
        )
        return jsonify(serialize_assignment_result(result)), 200
    except AssignmentValidationError as exc:
        message = ASSIGNMENT_MESSAGES.get(exc.code, "Invalid request body")
        status = 404 if exc.code == "strategy_not_found" else 400
        return jsonify({"error": message, "code": exc.code}), status
    except PortfolioReassignmentAcknowledgementRequired as exc:
        return (
            jsonify(
                {
                    "error": "This reassignment breaks portfolio history continuity",
                    "assignment_check": exc.verdict,
                    "resubmit_with": "acknowledge",
                }
            ),
            409,
        )
    except Exception as exc:
        current_app.logger.error(
            "Failed to reassign %s: %s", strategy_id, str(exc), exc_info=True
        )
        return jsonify({"error": "Failed to reassign the strategy"}), 500


@portfolio_bp.route("/strategies/<strategy_id>/portfolio/history", methods=["GET"])
@jwt_required()
@internal_only
def get_assignment_history(strategy_id):
    try:
        registry, _reader = _portfolio_dependencies()
        history = ListAssignmentHistory(registry).execute(strategy_id)
        return jsonify(serialize_assignment_history(history)), 200
    except Exception as exc:
        current_app.logger.error(
            "Failed to read assignment history for %s: %s", strategy_id, str(exc), exc_info=True
        )
        return jsonify({"error": "Failed to read assignment history"}), 500


@portfolio_bp.route("/books", methods=["GET"])
@jwt_required()
@internal_only
def get_books():
    """Every book and what is in it, including books defined but still empty."""
    try:
        registry, reader = _portfolio_dependencies()
        return jsonify(serialize_book_list(ListBooks(registry, reader).execute())), 200
    except Exception as exc:
        current_app.logger.error("Failed to list books: %s", str(exc), exc_info=True)
        return jsonify({"error": "Failed to list books"}), 500


@portfolio_bp.route("/books", methods=["POST"])
@jwt_required()
@internal_only
def create_book():
    try:
        registry, _reader = _portfolio_dependencies()
        book = CreateBook(registry).execute(request.get_json(silent=True), _request_user_id())
        return jsonify(book), 201
    except AssignmentValidationError as exc:
        return (
            jsonify(
                {
                    "error": ASSIGNMENT_MESSAGES.get(exc.code, "Invalid request body"),
                    "code": exc.code,
                }
            ),
            400,
        )
    except Exception as exc:
        current_app.logger.error("Failed to create book: %s", str(exc), exc_info=True)
        return jsonify({"error": "Failed to create the book"}), 500


@portfolio_bp.route("/books/<portfolio_id>", methods=["DELETE"])
@jwt_required()
@internal_only
def delete_book(portfolio_id):
    """Remove a book. Refused while anything still sits in it."""
    try:
        registry, _reader = _portfolio_dependencies()
        return jsonify(DeleteBook(registry).execute(portfolio_id)), 200
    except AssignmentValidationError as exc:
        return (
            jsonify(
                {
                    "error": ASSIGNMENT_MESSAGES.get(exc.code, "Invalid request"),
                    "code": exc.code,
                }
            ),
            400,
        )
    except BookNotEmpty as exc:
        return (
            jsonify(
                {
                    "error": (
                        f"{exc.portfolio_id} still holds {exc.occupied} "
                        f"{'strategy' if exc.occupied == 1 else 'strategies'}. "
                        f"Move them to another book first."
                    ),
                    "code": "book_not_empty",
                }
            ),
            409,
        )
    except Exception as exc:
        current_app.logger.error("Failed to delete book: %s", str(exc), exc_info=True)
        return jsonify({"error": "Failed to delete the book"}), 500


@portfolio_bp.route("/books/<portfolio_id>/strategies", methods=["POST"])
@jwt_required()
@internal_only
def add_strategy_to_book(portfolio_id):
    """Put a strategy in this book. It keeps the books it is already in.

    A reason is required, as it is for removal. Adding needs no acknowledgement
    -- nothing is taken away -- but it still changes what a book contains, and a
    change with no stated reason is indistinguishable from an accident when the
    audit trail is read back months later.
    """
    payload = request.get_json(silent=True) or {}
    if not str(payload.get("reason") or "").strip():
        return (
            jsonify(
                {
                    "error": (
                        "Field 'reason' must not be empty: a book change with no "
                        "stated reason is indistinguishable from an accident when "
                        "read back months later"
                    ),
                    "code": "empty_reason",
                }
            ),
            400,
        )
    return _change_book_membership(portfolio_id, "add")


@portfolio_bp.route("/books/<portfolio_id>/strategies/<strategy_id>", methods=["DELETE"])
@jwt_required()
@internal_only
def remove_strategy_from_book(portfolio_id, strategy_id):
    """Take a strategy out of this book.

    Answers 409 with the consequences unless the caller has acknowledged that
    the book's history becomes discontinuous.
    """
    return _change_book_membership(portfolio_id, "remove", strategy_id)


def _change_book_membership(portfolio_id, action, strategy_id=None):
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"error": "Request body must be a JSON object"}), 400
    if not str(payload.get("reason") or "").strip():
        return (
            jsonify(
                {
                    "error": (
                        "Field 'reason' must not be empty: a book change with no "
                        "stated reason is indistinguishable from an accident when "
                        "read back months later"
                    ),
                    "code": "empty_reason",
                }
            ),
            400,
        )
    strategy_id = strategy_id or payload.get("strategy_id")
    if not strategy_id:
        return jsonify({"error": "Missing required field: strategy_id"}), 400

    try:
        registry, _reader = _portfolio_dependencies()
        result = ChangeBookMembership(registry).execute(
            strategy_id,
            portfolio_id,
            action,
            user_id=_request_user_id(),
            reason=payload.get("reason"),
            acknowledge=bool(payload.get("acknowledge")),
        )
        return jsonify(serialize_assignment_result(result)), 200
    except AssignmentValidationError as exc:
        message = ASSIGNMENT_MESSAGES.get(exc.code, "Invalid request")
        status = 404 if exc.code == "strategy_not_found" else 400
        return jsonify({"error": message, "code": exc.code}), status
    except MembershipAcknowledgementRequired as exc:
        return (
            jsonify(
                {
                    "error": "Removing this strategy breaks the book's history continuity",
                    "assignment_check": exc.verdict,
                    "resubmit_with": "acknowledge",
                }
            ),
            409,
        )
    except Exception as exc:
        current_app.logger.error(
            "Failed to %s membership for %s: %s", action, strategy_id, str(exc), exc_info=True
        )
        return jsonify({"error": "Failed to change book membership"}), 500
