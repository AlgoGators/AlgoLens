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
from services.config_service import (
    ConfigValidationError,
    get_effective_config,
    get_active_overrides,
    get_config_history,
    validate_overrides,
    create_version,
    activate_version,
)
from services.incubation import (
    IncubationError,
    get_incubating,
    start_incubation,
    promote_to_live,
    retire,
    get_incubation_performance,
)

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


@portfolio_bp.route("/config/<strategy_id>", methods=["GET"])
@jwt_required()
@internal_only
def get_config(strategy_id):
    """Fetch the effective config and active overrides for one strategy.

    Returns a dict with:
    - effective: the newest manifest row's effective config (or null if unpublished)
    - active_overrides: the active strategy_config row (or null if none)
    - version: the active version number (or null)
    """
    cfg = get_strategy_config(strategy_id)
    if cfg is None:
        return jsonify({"error": "Strategy not found"}), 404

    portfolio_id = cfg["portfolio_id"]

    try:
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                effective = get_effective_config(cursor, portfolio_id)
                active = get_active_overrides(cursor, portfolio_id)
        finally:
            conn.close()

        # None is distinguishable from an empty dict: the engine has not published yet.
        response = {
            "effective": effective,
            "active_overrides": dict(active) if active else None,
            "version": active["version"] if active else None,
        }
        return jsonify(response), 200

    except Exception as e:
        current_app.logger.error(
            f"Failed to fetch config for {strategy_id}: {e}", exc_info=True
        )
        return jsonify({"error": "Failed to fetch config"}), 500


@portfolio_bp.route("/config/<strategy_id>/history", methods=["GET"])
@jwt_required()
@internal_only
def get_config_history_route(strategy_id):
    """Fetch the version history for one strategy's config, newest first."""
    cfg = get_strategy_config(strategy_id)
    if cfg is None:
        return jsonify({"error": "Strategy not found"}), 404

    portfolio_id = cfg["portfolio_id"]

    try:
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                rows = get_config_history(cursor, portfolio_id)
        finally:
            conn.close()

        versions = [dict(row) for row in rows]
        return jsonify({"versions": versions}), 200

    except Exception as e:
        current_app.logger.error(
            f"Failed to fetch config history for {strategy_id}: {e}", exc_info=True
        )
        return jsonify({"error": "Failed to fetch history"}), 500


@portfolio_bp.route("/config/<strategy_id>", methods=["POST"])
@jwt_required()
@internal_only
def create_config(strategy_id):
    """Create a new config version with overrides.

    Body: {"overrides": {...}, "reason": "..."}

    Validates the overrides against the engine's published config, then
    creates a new version and makes it active. Returns 201.
    """
    cfg = get_strategy_config(strategy_id)
    if cfg is None:
        return jsonify({"error": "Strategy not found"}), 404

    portfolio_id = cfg["portfolio_id"]
    payload = request.get_json(silent=True)

    if not isinstance(payload, dict):
        return jsonify({"error": "Request body must be a JSON object"}), 400

    overrides = payload.get("overrides")
    reason = payload.get("reason")

    if overrides is None:
        return jsonify({"error": "Missing required field: overrides"}), 400
    if reason is None or not str(reason).strip():
        return jsonify({"error": "Missing required field: reason"}), 400

    # Parse user_id from JWT identity defensively.
    try:
        user_id = int(get_jwt_identity())
    except (TypeError, ValueError):
        current_app.logger.error(f"JWT identity is not numeric: {get_jwt_identity()!r}")
        return jsonify({"error": "Invalid user identity in token"}), 400

    try:
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                # Fetch the effective config to validate against.
                effective = get_effective_config(cursor, portfolio_id)
        finally:
            # Cursor is closed, but connection stays open for create_version.
            pass

        # If the engine has never published, we have no schema to validate against.
        if effective is None:
            conn.close()
            return (
                jsonify(
                    {
                        "error": "Engine has not published a config yet",
                        "details": "Cannot set overrides without knowing what the engine reads",
                    }
                ),
                400,
            )

        # Validate overrides against effective schema.
        try:
            validate_overrides(overrides, effective)
        except ConfigValidationError as e:
            conn.close()
            return jsonify({"error": str(e)}), 400

        # All good: create the new version.
        result = create_version(
            conn, portfolio_id, overrides, reason=str(reason).strip(), user_id=user_id
        )
        conn.close()

        current_app.logger.info(
            f"Created config version {result.get('version')} for {strategy_id} "
            f"by user {user_id}"
        )
        return jsonify(result), 201

    except Exception as e:
        current_app.logger.error(
            f"Failed to create config version for {strategy_id}: {e}", exc_info=True
        )
        return jsonify({"error": "Failed to create config version"}), 500


@portfolio_bp.route("/config/<strategy_id>/activate", methods=["POST"])
@jwt_required()
@internal_only
def activate_config(strategy_id):
    """Revert to an earlier config version.

    Body: {"version": <version_number>, "reason": "..."}

    Creates a new version row copying the old overrides, preserving the
    append-only audit trail. Returns 201.
    """
    cfg = get_strategy_config(strategy_id)
    if cfg is None:
        return jsonify({"error": "Strategy not found"}), 404

    portfolio_id = cfg["portfolio_id"]
    payload = request.get_json(silent=True)

    if not isinstance(payload, dict):
        return jsonify({"error": "Request body must be a JSON object"}), 400

    version = payload.get("version")
    reason = payload.get("reason")

    if version is None:
        return jsonify({"error": "Missing required field: version"}), 400
    if reason is None or not str(reason).strip():
        return jsonify({"error": "Missing required field: reason"}), 400

    # Parse user_id from JWT identity defensively.
    try:
        user_id = int(get_jwt_identity())
    except (TypeError, ValueError):
        current_app.logger.error(f"JWT identity is not numeric: {get_jwt_identity()!r}")
        return jsonify({"error": "Invalid user identity in token"}), 400

    try:
        conn = get_db_connection()
        result = activate_version(
            conn,
            portfolio_id,
            version=int(version),
            reason=str(reason).strip(),
            user_id=user_id,
        )
        conn.close()

        current_app.logger.info(
            f"Reverted to config version {version} for {strategy_id} by user {user_id}"
        )
        return jsonify(result), 201

    except ConfigValidationError as e:
        return jsonify({"error": str(e)}), 400
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid version number"}), 400
    except Exception as e:
        current_app.logger.error(
            f"Failed to activate config version for {strategy_id}: {e}", exc_info=True
        )
        return jsonify({"error": "Failed to activate config version"}), 500


@portfolio_bp.route("/incubation", methods=["GET"])
@jwt_required()
@internal_only
def get_incubation_strategies():
    """List all strategies currently in incubation, with days elapsed and progress."""
    try:
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                strategies = get_incubating(cursor)
        finally:
            conn.close()

        return jsonify({"incubating_strategies": strategies}), 200

    except Exception as e:
        current_app.logger.error(
            f"Failed to fetch incubating strategies: {e}", exc_info=True
        )
        return jsonify({"error": "Failed to fetch incubating strategies"}), 500


@portfolio_bp.route("/incubation/<strategy_id>/start", methods=["POST"])
@jwt_required()
@internal_only
def start_strategy_incubation(strategy_id):
    """Move a live strategy into incubation on mock capital.

    Body: {"mock_capital": <positive_number>, "reason": "..."}

    Returns 201 if successful.

    Note: We resolve with include_incubating=True so that if the strategy is
    already incubating, the service layer can detect it and return the proper
    400 error (not a misleading 404).
    """
    cfg = get_strategy_config(strategy_id, include_incubating=True)
    if cfg is None:
        return jsonify({"error": "Strategy not found"}), 404

    payload = request.get_json(silent=True)

    if not isinstance(payload, dict):
        return jsonify({"error": "Request body must be a JSON object"}), 400

    mock_capital = payload.get("mock_capital")
    reason = payload.get("reason")

    if mock_capital is None:
        return jsonify({"error": "Missing required field: mock_capital"}), 400
    if reason is None or not str(reason).strip():
        return jsonify({"error": "Missing required field: reason"}), 400

    # Parse user_id from JWT identity defensively.
    try:
        user_id = int(get_jwt_identity())
    except (TypeError, ValueError):
        current_app.logger.error(f"JWT identity is not numeric: {get_jwt_identity()!r}")
        return jsonify({"error": "Invalid user identity in token"}), 400

    try:
        conn = get_db_connection()
        start_incubation(
            conn,
            strategy_id=strategy_id,
            mock_capital=float(mock_capital),
            reason=str(reason).strip(),
            user_id=str(user_id),
        )
        conn.close()

        current_app.logger.info(
            f"Started incubation for strategy {strategy_id} by user {user_id}"
        )
        return jsonify({"message": "Incubation started"}), 201

    except IncubationError as e:
        return jsonify({"error": str(e)}), 400
    except (ValueError, TypeError) as e:
        return jsonify(
            {"error": "Invalid mock_capital: must be a positive number"}
        ), 400
    except Exception as e:
        current_app.logger.error(
            f"Failed to start incubation for {strategy_id}: {e}", exc_info=True
        )
        return jsonify({"error": "Failed to start incubation"}), 500


@portfolio_bp.route("/incubation/<strategy_id>/promote", methods=["POST"])
@jwt_required()
@internal_only
def promote_strategy_to_live(strategy_id):
    """Move an incubating strategy back into live trading.

    Body: {"reason": "..."}

    Returns 200 if successful.
    """
    cfg = get_strategy_config(strategy_id, include_incubating=True)
    if cfg is None:
        return jsonify({"error": "Strategy not found"}), 404

    payload = request.get_json(silent=True)

    if not isinstance(payload, dict):
        return jsonify({"error": "Request body must be a JSON object"}), 400

    reason = payload.get("reason")

    if reason is None or not str(reason).strip():
        return jsonify({"error": "Missing required field: reason"}), 400

    # Parse user_id from JWT identity defensively.
    try:
        user_id = int(get_jwt_identity())
    except (TypeError, ValueError):
        current_app.logger.error(f"JWT identity is not numeric: {get_jwt_identity()!r}")
        return jsonify({"error": "Invalid user identity in token"}), 400

    try:
        conn = get_db_connection()
        promote_to_live(
            conn,
            strategy_id=strategy_id,
            reason=str(reason).strip(),
            user_id=str(user_id),
        )
        conn.close()

        current_app.logger.info(
            f"Promoted strategy {strategy_id} to live by user {user_id}"
        )
        return jsonify({"message": "Strategy promoted to live"}), 200

    except IncubationError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Failed to promote {strategy_id}: {e}", exc_info=True)
        return jsonify({"error": "Failed to promote strategy"}), 500


@portfolio_bp.route("/incubation/<strategy_id>/retire", methods=["POST"])
@jwt_required()
@internal_only
def retire_strategy(strategy_id):
    """Retire a strategy (move it out of live or incubation).

    Body: {"reason": "..."}

    Returns 200 if successful.
    """
    cfg = get_strategy_config(strategy_id, include_incubating=True)
    if cfg is None:
        return jsonify({"error": "Strategy not found"}), 404

    payload = request.get_json(silent=True)

    if not isinstance(payload, dict):
        return jsonify({"error": "Request body must be a JSON object"}), 400

    reason = payload.get("reason")

    if reason is None or not str(reason).strip():
        return jsonify({"error": "Missing required field: reason"}), 400

    # Parse user_id from JWT identity defensively.
    try:
        user_id = int(get_jwt_identity())
    except (TypeError, ValueError):
        current_app.logger.error(f"JWT identity is not numeric: {get_jwt_identity()!r}")
        return jsonify({"error": "Invalid user identity in token"}), 400

    try:
        conn = get_db_connection()
        retire(
            conn,
            strategy_id=strategy_id,
            reason=str(reason).strip(),
            user_id=str(user_id),
        )
        conn.close()

        current_app.logger.info(f"Retired strategy {strategy_id} by user {user_id}")
        return jsonify({"message": "Strategy retired"}), 200

    except IncubationError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Failed to retire {strategy_id}: {e}", exc_info=True)
        return jsonify({"error": "Failed to retire strategy"}), 500


@portfolio_bp.route("/incubation/<strategy_id>/performance", methods=["GET"])
@jwt_required()
@internal_only
def get_incubation_perf(strategy_id):
    """Get day-by-day mock positions and equity for an incubating strategy.

    Only returns data from incubation_started_at onward.
    """
    cfg = get_strategy_config(strategy_id, include_incubating=True)
    if cfg is None:
        return jsonify({"error": "Strategy not found"}), 404

    try:
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                performance = get_incubation_performance(
                    cursor, strategy_id, cfg["portfolio_id"]
                )
        finally:
            conn.close()

        return jsonify(performance), 200

    except Exception as e:
        current_app.logger.error(
            f"Failed to fetch incubation performance for {strategy_id}: {e}",
            exc_info=True,
        )
        return jsonify({"error": "Failed to fetch incubation performance"}), 500
