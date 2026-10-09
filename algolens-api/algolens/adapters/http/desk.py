"""QT desk HTTP routes (contract sections 4, 6 and 7).

Every route here is behind QT_DESK_ENABLED (default off, ruling 22): with the
flag off they answer 404 as if they did not exist. Desk routes also need
can_use_qt_desk(user); the approval routes need an approver (QT_APPROVERS).

Mounted under /portfolio/desk so the edge proxy's /portfolio/ rule serves it;
the browser page /qt/approve is the frontend's.
"""

from functools import wraps

import psycopg2
from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import jwt_required

from algolens.adapters.http.portfolio import (
    can_use_qt_desk,
    current_user,
    is_approver,
)
from algolens.application.qt.ports import (
    DeskConflict,
    DeskForbidden,
    DeskGone,
    DeskNotFound,
    DeskNotSeeded,
)
from algolens.application.qt.use_cases import (
    DecideOverride,
    GetCommand,
    GetDeskState,
    ListSymbolChoices,
    LookupApproval,
    PublishDesk,
    RequestOverride,
    SaveDeskEdit,
)
from algolens.application.qt.settings_use_cases import (
    GetSettings,
    RevertSettings,
    SaveSettings,
)
from algolens.domain.portfolio.registry import portfolio_entries
from algolens.domain.qt.approvers import APPROVER_ROLES
from algolens.domain.qt.desk import DeskRuleError
from algolens.domain.qt.settings import SettingsRuleError
from algolens.infrastructure.config.dependencies import (
    create_desk_dependencies,
    create_portfolio_dependencies,
    load_qt_settings,
)
from extensions import limiter

desk_bp = Blueprint("desk", __name__)

_ERRORS = (
    (DeskRuleError, 400),
    (SettingsRuleError, 400),
    (DeskForbidden, 403),
    (DeskNotFound, 404),
    (DeskNotSeeded, 409),
    (DeskConflict, 409),
    (DeskGone, 410),
)


def _desk_dependencies():
    return create_desk_dependencies()


def desk_enabled(fn):
    """404 unless QT_DESK_ENABLED is on (ruling 22)."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not load_qt_settings().desk_enabled:
            return jsonify({"error": "The QT desk is not enabled"}), 404
        return fn(*args, **kwargs)

    return wrapper


def desk_user(fn):
    """403 unless the user may use the QT desk."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not can_use_qt_desk(current_user()):
            return jsonify({"error": "Insufficient permissions"}), 403
        return fn(*args, **kwargs)

    return wrapper


def handled(fn):
    """Map desk errors to their HTTP status; anything else is a logged 500."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except tuple(e for e, _ in _ERRORS) as exc:
            status = next(code for error, code in _ERRORS if isinstance(exc, error))
            return jsonify({"error": str(exc)}), status
        except psycopg2.IntegrityError as exc:
            current_app.logger.warning("[DESK] refused by the database: %s", exc)
            return jsonify({"error": "The command log refused this request"}), 409
        except Exception as exc:
            current_app.logger.error("[DESK] %s failed: %s", request.path, exc, exc_info=True)
            return jsonify({"error": "The desk request failed"}), 500

    return wrapper


def _portfolio(portfolio_id):
    registry, _reader = create_portfolio_dependencies()
    cfg = registry.get_portfolio(portfolio_id)
    if cfg is None:
        raise DeskNotFound("Portfolio not found")
    return portfolio_entries([cfg])[0]


def _body():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise DeskRuleError("Request body must be a JSON object")
    return payload


def _approver_role(user):
    return next((role for role in APPROVER_ROLES if is_approver(user, role)), None)


@desk_bp.route("/<portfolio_id>", methods=["GET"])
@jwt_required()
@desk_enabled
@desk_user
@handled
def desk_state(portfolio_id):
    repo, _agent, _settings = _desk_dependencies()
    return jsonify(GetDeskState(repo).execute(_portfolio(portfolio_id))), 200


@desk_bp.route("/<portfolio_id>/symbols", methods=["GET"])
@jwt_required()
@desk_enabled
@desk_user
@handled
def desk_symbols(portfolio_id):
    repo, _agent, _settings = _desk_dependencies()
    choices = ListSymbolChoices(repo).execute(_portfolio(portfolio_id))
    return jsonify({"symbols": choices}), 200


@desk_bp.route("/<portfolio_id>/save", methods=["POST"])
@jwt_required()
@desk_enabled
@desk_user
@handled
def desk_save(portfolio_id):
    payload = _body()
    repo, agent, _settings = _desk_dependencies()
    result = SaveDeskEdit(repo, agent).execute(
        _portfolio(portfolio_id),
        payload.get("changes"),
        payload.get("reason"),
        current_user()["email"],
    )
    return jsonify(result), 201


@desk_bp.route("/commands/<int:command_id>", methods=["GET"])
@jwt_required()
@desk_enabled
@desk_user
@handled
def desk_command(command_id):
    repo, _agent, _settings = _desk_dependencies()
    return jsonify(GetCommand(repo).execute(command_id)), 200


@desk_bp.route("/<portfolio_id>/override-request", methods=["POST"])
@jwt_required()
@desk_enabled
@desk_user
@handled
def desk_override_request(portfolio_id):
    payload = _body()
    repo, agent, _settings = _desk_dependencies()
    result = RequestOverride(repo, agent).execute(
        _portfolio(portfolio_id), payload.get("reason"), current_user()["email"]
    )
    return jsonify(result), 201


@desk_bp.route("/<portfolio_id>/publish", methods=["POST"])
@jwt_required()
@desk_enabled
@desk_user
@handled
def desk_publish(portfolio_id):
    repo, agent, _settings = _desk_dependencies()
    result = PublishDesk(repo, agent).execute(
        _portfolio(portfolio_id), current_user()["email"]
    )
    return jsonify(result), 201


# --- override approval (the e-mailed link opens /qt/approve?token=...) --------
#
# The token travels in the POST body, never in an API URL, so it stays out of
# access logs. AlgoLens only hashes it (sha256) to find the request.


@desk_bp.route("/approval", methods=["POST"])
@jwt_required()
@desk_enabled
@limiter.limit("30 per minute")
@handled
def approval_lookup():
    user = current_user()
    role = _approver_role(user)
    if role is None and not can_use_qt_desk(user):
        return jsonify({"error": "Insufficient permissions"}), 403
    repo, _agent, _settings = _desk_dependencies()
    result = LookupApproval(repo).execute(_body().get("token"))
    result["viewer"] = {
        "email": user["email"],
        "approver_role": role,
        "is_requester": (user["email"] or "").lower()
        == (result["request"]["requested_by"] or "").lower(),
    }
    return jsonify(result), 200


@desk_bp.route("/approval/decide", methods=["POST"])
@jwt_required()
@desk_enabled
@limiter.limit("30 per minute")
@handled
def approval_decide():
    payload = _body()
    user = current_user()
    repo, agent, _settings = _desk_dependencies()
    result = DecideOverride(repo, agent).execute(
        payload.get("token"),
        payload.get("approved"),
        user["email"],
        _approver_role(user),
        payload.get("reason"),
    )
    return jsonify(result), 201


# --- desk settings (A7): strategy_config versions over the config files -------


@desk_bp.route("/<portfolio_id>/settings", methods=["GET"])
@jwt_required()
@desk_enabled
@desk_user
@handled
def settings_get(portfolio_id):
    repo, _agent, _settings = _desk_dependencies()
    return jsonify(GetSettings(repo).execute(_portfolio(portfolio_id))), 200


@desk_bp.route("/<portfolio_id>/settings", methods=["POST"])
@jwt_required()
@desk_enabled
@desk_user
@handled
def settings_save(portfolio_id):
    payload = _body()
    repo, _agent, _settings = _desk_dependencies()
    version = SaveSettings(repo).execute(
        _portfolio(portfolio_id),
        payload.get("changes"),
        payload.get("reason"),
        current_user()["email"],
    )
    return jsonify({"version": version}), 201


@desk_bp.route("/<portfolio_id>/settings/revert", methods=["POST"])
@jwt_required()
@desk_enabled
@desk_user
@handled
def settings_revert(portfolio_id):
    payload = _body()
    repo, _agent, _settings = _desk_dependencies()
    version = RevertSettings(repo).execute(
        _portfolio(portfolio_id),
        payload.get("version"),
        payload.get("reason"),
        current_user()["email"],
    )
    return jsonify({"version": version}), 201
