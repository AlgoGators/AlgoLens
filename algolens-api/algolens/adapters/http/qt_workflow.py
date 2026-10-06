"""Authenticated, single-attempt QT workflow transport."""
from functools import wraps
import json
from uuid import UUID
from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from algolens.application.identity.use_cases import VerifySession, UserNotFound
from algolens.domain.portfolio.qt_workflow_errors import QtWorkflowError
from algolens.domain.portfolio.qt_workflow_models import (
    QtDraftSaveRequest, QtCreatePreviewRequest, QtConfirmRequest, QtApproveRequest)
from algolens.infrastructure.config.dependencies import (create_identity_dependencies,
    create_qt_workflow_service, create_qt_decision_read_service, create_qt_investor_publication_service)
from algolens.application.portfolio.qt_investor_publication import QtPublishRequest
from algolens.adapters.http.capability_guard import disabled_route, requires_capability
from algolens.domain.identity.capabilities import role_has_capability

qt_workflow_bp = Blueprint('qt_workflow', __name__)


def _publication_service():
    configured = current_app.config.get('QT_EVALUATOR_BUNDLE_DIR')
    return create_qt_investor_publication_service(evaluator_bundle_directory=configured if configured else None)


def _workflow_service():
    configured = current_app.config.get('QT_EVALUATOR_BUNDLE_DIR')
    return create_qt_workflow_service(evaluator_bundle_directory=configured if configured else None)


def guard_legacy_write(registry, payload):
    """Resolve existing book scope before the legacy use case can evaluate/write."""
    from algolens.domain.portfolio.position_edit import validate_position_payload, resolve_target_book
    normalized = validate_position_payload(payload)
    try:
        strategy = getattr(registry, 'get_any', registry.get)(normalized['strategy_id'])
        if strategy is None: raise QtWorkflowError('not_found')
        books = registry.books_for_strategy(strategy['id'])
        book = resolve_target_book(strategy['id'], normalized.get('portfolio_id'), books, strategy['portfolio_id'])
        _read_service().ensure_legacy_disabled(book, current_actor())
    except QtWorkflowError: raise
    except Exception:
        raise QtWorkflowError('workflow_unavailable') from None


def _read_service():
    configured = current_app.config.get('QT_EVALUATOR_BUNDLE_DIR')
    return create_qt_decision_read_service(evaluator_bundle_directory=configured if configured else None)


def current_actor(required_capability='view_qt_platform'):
    subject = get_jwt_identity()
    if type(subject) is not str or not subject.isascii() or not subject.isdecimal() or subject.startswith('0'):
        raise QtWorkflowError('authorization_changed')
    users, _, _ = create_identity_dependencies()
    try:
        account = VerifySession(users).execute(subject)
    except UserNotFound:
        raise QtWorkflowError('authorization_changed') from None
    if str(account.id) != subject or not role_has_capability(account.role, required_capability):
        raise QtWorkflowError('authorization_changed')
    return int(subject)


def _body(model):
    raw = request.get_data(cache=False)
    if not request.is_json or len(raw) > 1_048_576:
        raise QtWorkflowError('invalid_qt_payload')
    def pairs(items):
        value = {}
        for name, item in items:
            if name in value: raise ValueError('duplicate_field')
            value[name] = item
        return value
    def refuse(_): raise ValueError('json_float')
    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_float=refuse, parse_constant=refuse)
        return model.from_wire(value)
    except (ValueError, TypeError, UnicodeDecodeError, RecursionError):
        raise QtWorkflowError('invalid_qt_payload') from None


def _id(value):
    try:
        if str(UUID(value)) != value: raise ValueError()
        return value
    except (ValueError, TypeError):
        raise QtWorkflowError('invalid_qt_payload') from None


def _boundary_for_capability(required_capability):
    def decorate(fn):
        @wraps(fn)
        @jwt_required()
        def wrapped(*args, **kwargs):
            try:
                return jsonify(fn(current_actor(required_capability), *args, **kwargs).to_wire())
            except QtWorkflowError as exc:
                return jsonify(exc.to_wire(book_id=kwargs.get('book_id'), preview_id=kwargs.get('preview_id'))), exc.http_status
            except Exception:
                exc = QtWorkflowError('workflow_unavailable')
                return jsonify(exc.to_wire(book_id=kwargs.get('book_id'), preview_id=kwargs.get('preview_id'))), 503
        return wrapped
    return decorate


_boundary = _boundary_for_capability('view_qt_platform')
_approval_boundary = _boundary_for_capability('view_qt_platform')


@qt_workflow_bp.get('/qt-books/<book_id>/proposal')
@requires_capability('view_qt_platform')
@_boundary
def proposal(actor, book_id):
    return _read_service().get_proposal(book_id, actor)


@qt_workflow_bp.get('/qt-books/<book_id>/draft')
@requires_capability('view_qt_platform')
@_boundary
def draft(actor, book_id):
    return _read_service().get_draft(book_id, actor)


@qt_workflow_bp.put('/qt-books/<book_id>/draft')
@requires_capability('edit_qt_book')
@_boundary
def save_draft(actor, book_id):
    return _workflow_service().save_draft(book_id, actor, _body(QtDraftSaveRequest))


@qt_workflow_bp.post('/qt-previews')
@requires_capability('edit_qt_book')
@_boundary
def preview(actor):
    return _workflow_service().create_preview(actor, _body(QtCreatePreviewRequest))


@qt_workflow_bp.post('/qt-previews/<preview_id>/confirm')
@requires_capability('edit_qt_book')
@_boundary
def confirm(actor, preview_id):
    return _workflow_service().confirm_preview(_id(preview_id), actor, _body(QtConfirmRequest))


@qt_workflow_bp.post('/qt-override-requests/<request_id>/approvals')
@requires_capability('approve_qt_override')
@_approval_boundary
def approve(actor, request_id):
    return _workflow_service().approve_override(_id(request_id), actor, _body(QtApproveRequest))


@qt_workflow_bp.get('/qt-decisions/<decision_id>')
@requires_capability('view_qt_platform')
@_approval_boundary
def decision(actor, decision_id):
    return _read_service().get_decision(_id(decision_id), actor)


@qt_workflow_bp.get('/qt-books/<book_id>/decision')
@requires_capability('view_qt_platform')
@_approval_boundary
def book_decision(actor, book_id):
    if set(request.args) - {'source_day'} or len(request.args.getlist('source_day')) > 1:
        raise QtWorkflowError('invalid_qt_payload')
    return _read_service().get_book_decision(book_id, actor, request.args.get('source_day'))


@qt_workflow_bp.post('/qt-decisions/<decision_id>/publish')
@requires_capability('publish_qt_book')
@_boundary
def publish_decision(actor, decision_id):
    return _publication_service().publish(_id(decision_id), actor, _body(QtPublishRequest))


@qt_workflow_bp.get('/qt-published-books/<book_id>/<source_day>')
@disabled_route
def published_book(book_id, source_day):
    # Public disclosure is separately default-denied by the book policy. This
    # route never falls back to the mutable desk or MODEL positions.
    try:
        if request.args:
            raise QtWorkflowError('invalid_qt_payload')
        payload = _publication_service().get_public(book_id, source_day).to_wire()
        response = jsonify(payload)
    except QtWorkflowError as exc:
        response = jsonify(exc.to_wire(book_id=book_id)), exc.http_status
    except Exception:
        exc = QtWorkflowError('workflow_unavailable')
        response = jsonify(exc.to_wire(book_id=book_id)), 503
    from flask import make_response
    result = make_response(response)
    result.headers['Cache-Control'] = 'no-store'
    return result
