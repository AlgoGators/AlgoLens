"""Authenticated QT transport uses current accounts and cookie CSRF."""
import importlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token, get_csrf_token
from algolens.domain.portfolio.qt_workflow_errors import QtWorkflowError

MODULE = Path(__file__).resolve().parents[1] / 'algolens/adapters/http/qt_workflow.py'


@pytest.fixture
def client(monkeypatch):
    assert MODULE.is_file(), 'A8 authenticated QT blueprint is missing'
    module = importlib.import_module('algolens.adapters.http.qt_workflow')
    account = SimpleNamespace(id=101, role='general_member')
    users = Mock()
    users.find_by_id.return_value = account
    monkeypatch.setattr(module, 'create_identity_dependencies', lambda: (users, None, None))
    service, reads = Mock(), Mock()
    response = SimpleNamespace(to_wire=lambda: {'schema_version': 'qt-workflow/v1', 'test': 'synthetic'})
    service.create_preview.return_value = response
    service.approve_override.return_value = response
    reads.get_proposal.return_value = response
    reads.get_book_decision.return_value = response
    monkeypatch.setattr(module, '_workflow_service', lambda: service)
    monkeypatch.setattr(module, '_read_service', lambda: reads)
    app = Flask(__name__)
    app.config.update(TESTING=True, JWT_SECRET_KEY='synthetic-unit-secret-' * 4,
                      JWT_TOKEN_LOCATION=['cookies'], JWT_COOKIE_CSRF_PROTECT=True, DEV_MODE=True)
    JWTManager(app)
    app.register_blueprint(module.qt_workflow_bp, url_prefix='/portfolio')
    with app.app_context():
        token = create_access_token(identity='101')
        csrf = get_csrf_token(token)
    browser = app.test_client()
    browser.set_cookie('access_token_cookie', token)
    return browser, csrf, service, reads, users, account


def test_proposal_uses_actual_persistent_session_identity(client):
    browser, _, _, reads, users, _ = client
    assert browser.get('/portfolio/qt-books/BOOK/proposal').status_code == 200
    users.find_by_id.assert_called_once_with('101')
    reads.get_proposal.assert_called_once_with('BOOK', 101)


@pytest.mark.parametrize('role', ['customer', 'external', None])
def test_current_noninternal_role_denied_even_dev_mode(client, role):
    browser, _, _, reads, _, account = client
    account.role = role
    result = browser.get('/portfolio/qt-books/BOOK/proposal')
    assert result.status_code == 403
    assert result.json['error']['code'] == 'authorization_changed'
    reads.get_proposal.assert_not_called()


def test_deleted_session_account_fails_closed(client):
    browser, _, _, reads, users, _ = client
    users.find_by_id.return_value = None
    assert browser.get('/portfolio/qt-books/BOOK/proposal').status_code == 403
    reads.get_proposal.assert_not_called()


def test_cookie_csrf_required_before_mutation(client):
    browser, _, service, _, _, _ = client
    assert browser.post('/portfolio/qt-previews', json={}).status_code == 401
    service.create_preview.assert_not_called()


@pytest.mark.parametrize('body', ['{"action":"approve","action":"approve","idempotency_key":"00000000-0000-4000-8000-000000000062"}',
    '{"action":"approve","actor_id":999}', '{"action":"approve","idempotency_key":1.2}', '{}'])
def test_strict_boundary_rejects_duplicates_floats_and_caller_identity(client, body):
    browser, csrf, service, _, _, _ = client
    response = browser.post('/portfolio/qt-override-requests/00000000-0000-4000-8000-000000000061/approvals',
        data=body, content_type='application/json', headers={'X-CSRF-TOKEN': csrf})
    assert response.status_code == 400
    service.approve_override.assert_not_called()


def test_approval_single_attempt_and_typed_conflict(client):
    browser, csrf, service, _, _, _ = client
    service.approve_override.side_effect = QtWorkflowError('preview_stale')
    response = browser.post('/portfolio/qt-override-requests/00000000-0000-4000-8000-000000000061/approvals',
        json={'action': 'approve', 'idempotency_key': '00000000-0000-4000-8000-000000000062'},
        headers={'X-CSRF-TOKEN': csrf})
    assert response.status_code == 409
    assert response.json['error'] == {'code': 'preview_stale', 'message': 'QT workflow request rejected', 'retryable': False}
    assert service.approve_override.call_count == 1
    assert service.approve_override.call_args.args[1] == 101


def test_exec_board_can_approve_but_cannot_open_submitter_workspace(client):
    browser, csrf, service, reads, _, account = client
    account.role = 'exec_board'
    response = browser.post('/portfolio/qt-override-requests/00000000-0000-4000-8000-000000000061/approvals',
        json={'action': 'approve', 'idempotency_key': '00000000-0000-4000-8000-000000000063'},
        headers={'X-CSRF-TOKEN': csrf})
    assert response.status_code == 200
    service.approve_override.assert_called_once()
    denied = browser.get('/portfolio/qt-books/BOOK/proposal')
    assert denied.status_code == 403
    reads.get_proposal.assert_not_called()


def test_storage_failure_is_safe_503(client):
    browser, _, _, reads, _, _ = client
    reads.get_proposal.side_effect = RuntimeError('sensitive connection detail')
    response = browser.get('/portfolio/qt-books/BOOK/proposal')
    assert response.status_code == 503
    assert 'sensitive' not in response.get_data(as_text=True)


@pytest.mark.parametrize('query', ['source_day=2026-09-25&source_day=2026-09-26', 'actor_id=202', 'source_day=bad'])
def test_book_decision_discovery_rejects_ambiguous_query(client, query):
    browser, _, _, reads, _, _ = client
    reads.get_book_decision.side_effect = QtWorkflowError('invalid_qt_payload')
    response = browser.get('/portfolio/qt-books/BOOK/decision?' + query)
    assert response.status_code == 400


def test_book_decision_discovery_is_read_only_actor_scoped(client):
    browser, _, _, reads, _, _ = client
    assert browser.get('/portfolio/qt-books/BOOK/decision?source_day=2026-09-25').status_code == 200
    reads.get_book_decision.assert_called_once_with('BOOK', 101, '2026-09-25')
