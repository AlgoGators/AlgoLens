"""Portfolio HTTP routes."""

from datetime import datetime, timezone
from functools import wraps
import time

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import get_jwt, get_jwt_identity, jwt_required

from algolens.adapters.serializers.portfolio import (
    serialize_incubating_strategy_list,
    serialize_incubation_performance,
    serialize_strategy_detail,
    serialize_strategy_list,
)
from algolens.application.portfolio.ports import (
    IncubationError,
    RiskAcknowledgementRequired,
    StrategyNameUnresolved,
)
from algolens.application.portfolio.use_cases import (
    GetIncubationPerformance,
    GetStrategyDetail,
    ListIncubatingStrategies,
    ListPositionOverrides,
    ListStrategies,
    PromoteToLive,
    RetireStrategy,
    StartIncubation,
    StrategyDataNotFound,
    StrategyNotFound,
    UpsertQtPosition,
)
from algolens.domain.portfolio.position_edit import PositionValidationError
from algolens.infrastructure.config.dependencies import create_portfolio_dependencies

portfolio_bp = Blueprint("portfolio", __name__)

# Rendered from PositionValidationError.code rather than from the exception
# itself, so no exception text can reach a client (CodeQL py/stack-trace-
# exposure). Every message here is authored, not derived.
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
    return 404 if "not found" in str(exc).lower() else 400


@portfolio_bp.route("/strategy/<strategy_id>", methods=["GET"])
@jwt_required()
def get_strategy(strategy_id):
    start = time.perf_counter()
    try:
        current_app.logger.info("Fetching strategy: %s", strategy_id)
        registry, reader = _portfolio_dependencies()
        strategy = GetStrategyDetail(registry, reader).execute(strategy_id)
        elapsed_ms = (time.perf_counter() - start) * 1000
        current_app.logger.info(
            "[PORTFOLIO_TIMING] detail strategy_id=%s elapsed_ms=%.0f",
            strategy_id,
            elapsed_ms,
        )
        return jsonify(serialize_strategy_detail(strategy)), 200
    except StrategyNotFound:
        return jsonify({"error": "Strategy not found"}), 404
    except StrategyDataNotFound:
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
