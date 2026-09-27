"""Real JWT/CSRF routes; fake persistence, no external services."""
import pytest

from tests.test_incubation_routes import _set_jwt_cookie
from tests.test_runtime_control import Repository, manifest
from algolens.application.runtime_control import RuntimeControlService
from algolens.infrastructure.config.runtime_control import RuntimeControlConfig

URL = '/portfolio/strategies/test/runtime'


def test_runtime_status_requires_login(client):
    assert client.get(URL + '?portfolio_id=TEST_BOOK').status_code == 401


@pytest.fixture
def repository(monkeypatch, tmp_path):
    import algolens.adapters.http.runtime_control as http
    repo = Repository()
    config = RuntimeControlConfig({'QT_RUNTIME_CONTROL_ENABLED': 'true',
        'QT_RUNTIME_APPROVER_IDS': '7', 'QT_RUNTIME_CONFIG_MANIFEST': manifest(tmp_path)})
    monkeypatch.setattr(http, '_service', lambda: RuntimeControlService(repo, config))
    return repo


def test_internal_can_request_but_cannot_approve(client, repository):
    csrf = _set_jwt_cookie(client, role='general_member', identity='7')
    request = client.post(URL+'/requests', json={'action':'run', 'portfolio_id':'TEST_BOOK', 'reason':'Reviewed'},
                          headers={'X-CSRF-TOKEN':csrf})
    assert request.status_code == 201
    approve = client.post(URL+'/requests/1/approve', json={'reason':'Reviewed'}, headers={'X-CSRF-TOKEN':csrf})
    assert approve.status_code == 403
    assert [call[0] for call in repository.calls] == ['request']


def test_stale_admin_claim_cannot_approve_after_demotion(client, repository):
    csrf = _set_jwt_cookie(client, role='admin', identity='7', current_role='general_member')
    response = client.post(URL+'/requests/1/approve', json={'reason':'Reviewed'}, headers={'X-CSRF-TOKEN':csrf})
    assert response.status_code == 403
    assert repository.calls == []


def test_current_eligible_admin_can_approve(client, repository):
    csrf = _set_jwt_cookie(client, role='general_member', identity='7', current_role='admin')
    response = client.post(URL+'/requests/1/approve', json={'reason':'Reviewed'}, headers={'X-CSRF-TOKEN':csrf})
    assert response.status_code == 200
    assert response.json['intent']['status'] == 'approved'
    assert [call[0] for call in repository.calls] == ['approve']


def test_investor_and_deleted_user_cannot_read_control(client, repository):
    _set_jwt_cookie(client, role='subscriber_individual', identity='7')
    assert client.get(URL+'?portfolio_id=TEST_BOOK').status_code == 403
    _set_jwt_cookie(client, role='admin', identity='7')
    client.current_users.remove('7')
    assert client.get(URL+'?portfolio_id=TEST_BOOK').status_code == 403
    assert repository.calls == []


def test_runtime_mutations_require_csrf_and_strict_request_body(client, repository):
    csrf = _set_jwt_cookie(client, role='admin', identity='7')
    assert client.post(URL+'/requests/1/approve', json={'reason':'Reviewed'}).status_code == 401
    response = client.post(URL+'/requests', json={'action':'run', 'portfolio_id':'TEST_BOOK',
                    'reason':'Reviewed', 'approved_by':'7'}, headers={'X-CSRF-TOKEN':csrf})
    assert response.status_code == 400
    assert repository.calls == []


def test_status_does_not_imply_running_engine(client, repository):
    _set_jwt_cookie(client, role='admin', identity='7')
    response = client.get(URL+'?portfolio_id=TEST_BOOK')
    assert response.status_code == 200
    assert response.json['engine_enabled'] is None
    assert response.json['latest_attempt'] is None


def test_storage_error_is_safe(client, repository):
    _set_jwt_cookie(client, role='admin', identity='7')
    def failure(**_):
        raise RuntimeError('synthetic-private-details')
    repository.status = failure
    response = client.get(URL+'?portfolio_id=TEST_BOOK')
    assert response.status_code == 503
    assert 'synthetic-private-details' not in response.get_data(as_text=True)
