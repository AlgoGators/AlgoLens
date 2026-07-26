"""Portfolio routes.

Thin HTTP layer: resolve the requested strategy against the data-driven registry
(services.strategy_registry) and delegate all DB access and metric math to
services.portfolio_service. No strategy is hardcoded here anymore.
"""

from functools import wraps
from flask import Blueprint, jsonify, current_app, request
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt

from database import get_db_connection
from services.position_writer import (
    PositionValidationError,
    StrategyNameUnresolved,
    fetch_overrides,
    fetch_qt_book,
    fetch_risk_envelope,
    validate_position_payload,
    write_qt_position,
)
from services.risk_gate import evaluate
from services.strategy_registry import get_registry, get_strategy_config
from services.portfolio_service import get_strategy_detail, get_strategy_summary

# Writing the book and reading the fund's override reasoning are internal
# operations. Subscriber roles (ADR-000 C-6) are external paying customers:
# authenticating as one proves who you are, not that you may move the fund's
# money. Default-deny -- an unrecognised or absent role is refused, so a new
# role added later is locked out until somebody decides it belongs here.
INTERNAL_ROLES = frozenset({"admin", "general_member"})


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


portfolio_bp = Blueprint("portfolio", __name__)


@portfolio_bp.route("/strategy/<strategy_id>", methods=["GET"])
@jwt_required()
def get_strategy(strategy_id):
    """Fetch full data for one strategy, identified by its public registry id."""
    try:
        current_app.logger.info(f"Fetching strategy: {strategy_id}")

        cfg = get_strategy_config(strategy_id)
        if cfg is None:
            return jsonify({"error": "Strategy not found"}), 404

        strategy = get_strategy_detail(cfg)
        if strategy is None:
            # Known strategy, but no live_results rows yet.
            return jsonify({"error": "No data found for strategy"}), 404

        return jsonify(strategy), 200

    except Exception as e:
        current_app.logger.error(
            f"Error fetching strategy {strategy_id}: {str(e)}", exc_info=True
        )
        return jsonify({"error": "Failed to fetch strategy"}), 500


@portfolio_bp.route("/strategies", methods=["GET"])
@jwt_required()
def get_all_strategies():
    """Get summaries for every active strategy in the registry."""
    current_app.logger.info("[STRATEGIES] === /strategies endpoint called ===")

    try:
        strategies = []
        for cfg in get_registry(active_only=True):
            try:
                summary = get_strategy_summary(cfg)
            except Exception as e:
                # One strategy failing shouldn't blank the whole dashboard.
                current_app.logger.error(
                    f"[STRATEGIES] Failed to summarize {cfg['id']}: {str(e)}",
                    exc_info=True,
                )
                continue
            if summary:
                strategies.append(summary)

        current_app.logger.info(f"[STRATEGIES] Returning {len(strategies)} strategies")
        return jsonify({"strategies": strategies}), 200

    except Exception as e:
        current_app.logger.error(
            f"[STRATEGIES] Error fetching strategies: {str(e)}", exc_info=True
        )
        return jsonify({"error": "Failed to fetch strategies"}), 500


@portfolio_bp.route("/positions", methods=["POST"])
@jwt_required()
@internal_only
def upsert_position():
    """Create or amend one position in the qt stream.

    A risk breach does not block the write, but it does require the caller to
    come back with acknowledge_risk=true (409 on the first attempt). Every write
    lands in trading.position_overrides in the same transaction.
    """
    try:
        normalized = validate_position_payload(request.get_json(silent=True))
    except PositionValidationError as e:
        return jsonify({"error": str(e)}), 400

    cfg = get_strategy_config(normalized["strategy_id"])
    if cfg is None:
        return jsonify({"error": "Strategy not found"}), 404

    acknowledge = bool((request.get_json(silent=True) or {}).get("acknowledge_risk"))

    # Parse the user_id from the JWT identity defensively.
    try:
        user_id = int(get_jwt_identity())
    except (TypeError, ValueError):
        current_app.logger.error(f"JWT identity is not numeric: {get_jwt_identity()!r}")
        return jsonify({"error": "Invalid user identity in token"}), 400

    try:
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                envelope = fetch_risk_envelope(
                    cursor, cfg["strategy_type"], cfg["portfolio_id"]
                )
                book = fetch_qt_book(cursor, cfg["strategy_type"], cfg["portfolio_id"])

            # The verdict is evaluated against the book as it stands at this moment.
            # It describes the book at gate-evaluation time, not at commit time. This is
            # acceptable because the gate is advisory by design: a breach never blocks;
            # it only requires acknowledgement. The position write proceeds either way.
            verdict = evaluate(envelope, book, normalized)

            if not verdict["passed"] and not acknowledge:
                return jsonify(
                    {
                        "error": "This position breaches a risk limit",
                        "risk_check": verdict,
                        "resubmit_with": "acknowledge_risk",
                    }
                ), 409

            result = write_qt_position(
                conn,
                cfg,
                normalized,
                user_id=user_id,
                verdict=verdict,
                overrode_risk=not verdict["passed"],
            )
        finally:
            conn.close()

        return jsonify({**result, "risk_check": verdict}), 201

    except StrategyNameUnresolved as e:
        current_app.logger.error(
            f"Strategy name unresolved for {normalized['symbol']}: {e}"
        )
        return jsonify({"error": str(e)}), 409
    except Exception as e:
        current_app.logger.error(
            f"Failed to write position {normalized['symbol']}: {e}", exc_info=True
        )
        return jsonify({"error": "Failed to write position"}), 500


@portfolio_bp.route("/overrides/<strategy_id>", methods=["GET"])
@jwt_required()
@internal_only
def get_overrides(strategy_id):
    """The audit trail for one strategy, most recent first."""
    cfg = get_strategy_config(strategy_id)
    if cfg is None:
        return jsonify({"error": "Strategy not found"}), 404

    try:
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                rows = fetch_overrides(cursor, cfg["strategy_type"])
        finally:
            conn.close()
        return jsonify({"overrides": rows}), 200
    except Exception as e:
        current_app.logger.error(
            f"Failed to fetch overrides for {strategy_id}: {e}", exc_info=True
        )
        return jsonify({"error": "Failed to fetch overrides"}), 500
