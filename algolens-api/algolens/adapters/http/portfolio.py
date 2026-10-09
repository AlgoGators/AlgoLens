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
from algolens.application.portfolio.ports import IncubationError
from algolens.application.portfolio.use_cases import (
    GetIncubationPerformance,
    GetPortfolioDetail,
    GetStrategyDetail,
    InvalidBook,
    ListIncubatingStrategies,
    ListPortfolios,
    ListStrategies,
    PortfolioNotFound,
    PromoteToLive,
    RetireStrategy,
    StartIncubation,
    StrategyDataNotFound,
    StrategyNotFound,
)
from algolens.infrastructure.config.dependencies import (
    create_portfolio_dependencies,
    load_qt_settings,
)

portfolio_bp = Blueprint("portfolio", __name__)

# Incubation is an internal member-only surface. Default-deny: an unrecognised
# or absent role is refused, so new roles stay locked out until explicitly added.
INTERNAL_ROLES = frozenset({"admin", "general_member"})


def can_use_qt_desk(user):
    """Whether a signed-in user may use the QT desk (edit, publish, settings).

    Provisional: the internal allow-list above. AlgoLens#94 replaces this with
    the qt_desk capability; every desk route goes through this one helper.
    """
    return (user or {}).get("role") in INTERNAL_ROLES


def is_approver(user, role):
    """Whether a signed-in user is the configured approver for `role`.

    `role` is 'vp' or 'president'; the addresses come from QT_APPROVERS.
    Provisional until AlgoLens#94 gives approvers a role of their own.
    """
    email = ((user or {}).get("email") or "").strip().lower()
    expected = load_qt_settings().approvers.get(role)
    return bool(email) and expected is not None and email == expected


def current_user():
    """The signed-in user as {id, email, role}, from the JWT claims."""
    claims = get_jwt()
    return {
        "id": str(get_jwt_identity()),
        "email": claims.get("email") or "",
        "role": claims.get("role"),
    }


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
        strategy = GetStrategyDetail(registry, reader).execute(
            strategy_id, book=request.args.get("book")
        )
        elapsed_ms = (time.perf_counter() - start) * 1000
        current_app.logger.info(
            "[PORTFOLIO_TIMING] detail strategy_id=%s elapsed_ms=%.0f",
            strategy_id,
            elapsed_ms,
        )
        return jsonify(serialize_strategy_detail(strategy)), 200
    except InvalidBook as exc:
        return jsonify({"error": str(exc)}), 400
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


@portfolio_bp.route("/portfolios", methods=["GET"])
@jwt_required()
def list_portfolios():
    """The portfolio switcher: live portfolios grouped by portfolio_group."""
    try:
        registry, _reader = _portfolio_dependencies()
        groups = ListPortfolios(registry).execute()
        return jsonify(
            {"groups": groups, "deskEnabled": load_qt_settings().desk_enabled}
        ), 200
    except Exception as exc:
        current_app.logger.error("Error listing portfolios: %s", str(exc), exc_info=True)
        return jsonify({"error": "Failed to list portfolios"}), 500


@portfolio_bp.route("/portfolios/<portfolio_id>", methods=["GET"])
@jwt_required()
def get_portfolio(portfolio_id):
    """One portfolio's book by portfolio id; ?book=system|qt_proposal|qt."""
    try:
        registry, reader = _portfolio_dependencies()
        detail = GetPortfolioDetail(registry, reader).execute(
            portfolio_id, book=request.args.get("book")
        )
        return jsonify(serialize_strategy_detail(detail)), 200
    except InvalidBook as exc:
        return jsonify({"error": str(exc)}), 400
    except PortfolioNotFound:
        return jsonify({"error": "Portfolio not found"}), 404
    except StrategyDataNotFound:
        return jsonify({"error": "No data found for portfolio"}), 404
    except Exception as exc:
        current_app.logger.error(
            "Error fetching portfolio %s: %s", portfolio_id, str(exc), exc_info=True
        )
        return jsonify({"error": "Failed to fetch portfolio"}), 500


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
