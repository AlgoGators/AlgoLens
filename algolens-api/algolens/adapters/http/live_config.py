"""Session identity and CSRF are mandatory; body never supplies an actor or artifact."""
import json
from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import jwt_required
from algolens.adapters.http import portfolio as portfolio_http
from algolens.adapters.http.capability_guard import requires_capability
from algolens.application.identity.use_cases import UserNotFound
from algolens.application.live_config import LiveConfigError
from algolens.infrastructure.config.dependencies import create_live_config_service

live_config_bp = Blueprint('live_config',__name__)
_CODES = frozenset({'live_config_invalid_request','live_config_authorization_changed',
    'live_config_scope_unsupported','live_config_validator_unavailable','live_config_configuration_unavailable',
    'live_config_configuration_changed','live_config_active_changed','live_config_storage_unavailable',
    'live_config_request_not_found','live_config_distinct_person_required'})


def _body():
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError()
            result[key] = value
        return result
    def constant(_):
        raise ValueError()
    try:
        if not request.is_json or (request.content_length or 0) > 262144:
            raise ValueError()
        raw = request.stream.read(262145)
        if len(raw) > 262144:
            raise ValueError()
        return json.loads(raw, object_pairs_hook=unique, parse_constant=constant)
    except (ValueError, TypeError, RecursionError):
        raise LiveConfigError('live_config_invalid_request',400) from None


def _service():
    return create_live_config_service()


def _invoke(operation, status=200):
    try:
        user = portfolio_http._current_user()
        return jsonify(operation(_service(),user)),status
    except UserNotFound:
        return jsonify({'code':'live_config_authorization_changed','error':'Current configuration authority is required.'}),403
    except LiveConfigError as error:
        code = error.code if error.code in _CODES else 'live_config_storage_unavailable'
        return jsonify({'code':code,'error':'Configuration request refused. Refresh current authority and configuration before retrying.'}),error.status
    except Exception:
        current_app.logger.error('Live configuration request failed')
        return jsonify({'code':'live_config_storage_unavailable','error':'Configuration service unavailable.'}),503


@live_config_bp.route('/strategies/<strategy_id>/config',methods=['GET'])
@requires_capability('view_internal')
@jwt_required()
@portfolio_http.internal_only
def status(strategy_id):
    return _invoke(lambda service,user: service.status(strategy_id,request.args.get('portfolio_id')))


@live_config_bp.route('/strategies/<strategy_id>/config/preview',methods=['POST'])
@requires_capability('edit_config')
@jwt_required()
@portfolio_http.internal_only
def preview(strategy_id):
    return _invoke(lambda service,user: service.preview(strategy_id,_body(),user.id))


@live_config_bp.route('/strategies/<strategy_id>/config/requests',methods=['POST'])
@requires_capability('edit_config')
@jwt_required()
@portfolio_http.internal_only
def submit(strategy_id):
    return _invoke(lambda service,user: service.submit(strategy_id,_body(),user.id),201)


@live_config_bp.route('/strategies/<strategy_id>/config/requests/<request_id>/approve',methods=['POST'])
@requires_capability('approve_config')
@jwt_required()
@portfolio_http.internal_only
def approve(strategy_id,request_id):
    return _invoke(lambda service,user: service.approve(strategy_id,request_id,_body(),user.id))
