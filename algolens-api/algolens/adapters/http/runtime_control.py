"""Next-run request/approval HTTP boundary; never starts the engine."""
from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import jwt_required

from algolens.adapters.http import portfolio as portfolio_http
from algolens.application.identity.use_cases import UserNotFound
from algolens.application.runtime_control import RuntimeControlError
from algolens.infrastructure.config.dependencies import create_runtime_control_service

runtime_control_bp = Blueprint('runtime_control', __name__)

MESSAGES = {
    'invalid_request': 'Provide a valid book, action and nonempty reason; extra control fields are not accepted.',
    'runtime_disabled': 'Next-run control is disabled. No execution approval was changed.',
    'runtime_approval_forbidden': 'Execution approval requires a currently eligible administrator.',
    'runtime_scope_unsupported': 'This book and complete strategy configuration are not approved for runtime control.',
    'runtime_configuration_unavailable': 'The reviewed runtime configuration is unavailable.',
    'runtime_storage_unavailable': 'Runtime control data is unavailable. Refresh before retrying.',
    'runtime_request_stale': 'This request is no longer current. Refresh and submit a new request.',
    'runtime_request_not_found': 'Runtime request not found.',
    'runtime_lifecycle_conflict': 'Run requests require an active live strategy; stop requests require a retired strategy.',
    'strategy_not_found': 'Strategy not found.',
}


def _service():
    return create_runtime_control_service()


def _invoke(operation, status=200):
    try:
        # Re-read the stored role, never the stale JWT role. The outer existing
        # internal guard rejects missing/demoted subjects before dependencies.
        user = portfolio_http._current_user()
        return jsonify(operation(_service(), user)), status
    except UserNotFound:
        return jsonify({'error': 'Insufficient permissions'}), 403
    except RuntimeControlError as exc:
        code = exc.code if exc.code in MESSAGES else 'runtime_storage_unavailable'
        return jsonify({'error': MESSAGES[code], 'code': code}), exc.status
    except Exception:
        current_app.logger.error('Runtime control request failed')
        return jsonify({'error': MESSAGES['runtime_storage_unavailable'],
                        'code': 'runtime_storage_unavailable'}), 503


@runtime_control_bp.route('/strategies/<strategy_id>/runtime', methods=['GET'])
@jwt_required()
@portfolio_http.internal_only
def runtime_status(strategy_id):
    return _invoke(lambda service, user: service.status(
        strategy_id, request.args.get('portfolio_id'), str(user.id), user.role))


@runtime_control_bp.route('/strategies/<strategy_id>/runtime/requests', methods=['POST'])
@jwt_required()
@portfolio_http.internal_only
def request_runtime(strategy_id):
    return _invoke(lambda service, user: {'intent': service.request(
        strategy_id, request.get_json(silent=True), str(user.id))}, 201)


@runtime_control_bp.route('/strategies/<strategy_id>/runtime/requests/<int:intent_id>/approve', methods=['POST'])
@jwt_required()
@portfolio_http.internal_only
def approve_runtime(strategy_id, intent_id):
    return _invoke(lambda service, user: {'intent': service.approve(
        strategy_id, intent_id, request.get_json(silent=True), str(user.id), user.role)})
