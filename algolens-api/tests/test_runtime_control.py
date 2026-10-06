"""Runtime approval has a separate, default-deny authority boundary."""
import copy
import json

import pytest

from algolens.application.runtime_control import RuntimeControlError, RuntimeControlService
from algolens.infrastructure.config.runtime_control import RuntimeControlConfig


def snapshot():
    return {
        'snapshot_version': 2, 'use_optimization': True, 'covariance_history_prices': 756, 'sleeve_risk_modules': {}, 'portfolio_id': 'TEST_BOOK', 'initial_capital': 1000,
        'reserve_capital_pct': .1, 'benchmark_mode': 'live', 'execution': {},
        'optimization': {}, 'risk': {'schema':2}, 'max_drawdown': .4, 'max_leverage': 4,
        'backtest': {}, 'live': {}, 'strategy_defaults': {},
        'strategies': {'TEST': {'enabled_live': True, 'default_allocation': 1,
                                'type': 'TrendFollowingStrategy', 'config': {}}},
    }


def manifest(tmp_path, payload=None):
    file = tmp_path / 'reviewed-config.json'
    file.write_text(json.dumps(payload or {'version': 1, 'scopes': [{
        'registry_id': 'test', 'portfolio_id': 'TEST_BOOK',
        'engine_strategy_id': 'LIVE_TEST', 'config_snapshot': snapshot(),
    }]}))
    return str(file)


class Repository:
    def __init__(self):
        self.calls = []

    def request(self, **kwargs):
        self.calls.append(('request', kwargs))
        return {'id': 1, 'status': 'pending'}

    def approve(self, **kwargs):
        self.calls.append(('approve', kwargs))
        return {'id': 1, 'status': 'approved'}

    def status(self, **kwargs):
        self.calls.append(('status', kwargs))
        return {'intent': None, 'latest_attempt': None}


def test_composition_is_lazy_and_preserves_default_deny():
    from algolens.infrastructure.config.dependencies import create_runtime_control_service
    def no_connection():
        pytest.fail('Composition or disabled control must not connect')
    control = create_runtime_control_service(connection_factory=no_connection, environment={})
    assert control.repository.connection_factory is no_connection
    with pytest.raises(RuntimeControlError, match='runtime_disabled'):
        control.request('test', {'action': 'run', 'portfolio_id': 'TEST_BOOK', 'reason': 'review'}, '7')


@pytest.mark.parametrize('flag', [None, '', 'false', 'TRUE', '1', 'true '])
def test_runtime_mutations_default_deny(flag, tmp_path):
    env = {'QT_RUNTIME_CONFIG_MANIFEST': manifest(tmp_path)}
    if flag is not None:
        env['QT_RUNTIME_CONTROL_ENABLED'] = flag
    repo = Repository()
    service = RuntimeControlService(repo, RuntimeControlConfig(env))
    with pytest.raises(RuntimeControlError, match='runtime_disabled'):
        service.request('test', {'action': 'run', 'portfolio_id': 'TEST_BOOK', 'reason': 'review'}, '7')
    assert repo.calls == []


def service(tmp_path, **env):
    repo = Repository()
    config = RuntimeControlConfig({'QT_RUNTIME_CONTROL_ENABLED': 'true',
                                  'QT_RUNTIME_CONFIG_MANIFEST': manifest(tmp_path), **env})
    return RuntimeControlService(repo, config), repo


def test_request_uses_trusted_snapshot_not_browser_capital(tmp_path):
    control, repo = service(tmp_path)
    with pytest.raises(RuntimeControlError, match='invalid_request'):
        control.request('test', {'action': 'run', 'portfolio_id': 'TEST_BOOK',
                                'reason': 'review', 'config_snapshot': {'initial_capital': 999}}, '7')
    assert not repo.calls
    control.request('test', {'action': 'run', 'portfolio_id': 'test_book', 'reason': ' reviewed '}, '7')
    payload = repo.calls[0][1]
    assert payload['scope']['config_snapshot'] == snapshot()
    assert payload['reason'] == 'reviewed'
    assert payload['user_id'] == '7'


@pytest.mark.parametrize('role,ids', [('general_member', '7'), ('admin', ''), ('investor', '7')])
def test_approval_requires_current_admin_and_explicit_eligibility(tmp_path, role, ids):
    control, repo = service(tmp_path, QT_RUNTIME_APPROVER_IDS=ids)
    with pytest.raises(RuntimeControlError, match='runtime_approval_forbidden'):
        control.approve('test', 1, {'reason': 'review'}, '7', role)
    assert not repo.calls


def test_eligible_admin_approval_and_status_do_not_claim_engine_enabled(tmp_path):
    control, repo = service(tmp_path, QT_RUNTIME_APPROVER_IDS='7,8')
    control.approve('test', 1, {'reason': 'review'}, '7', 'admin')
    assert repo.calls[0][1]['user_id'] == '7'
    result = control.status('test', 'TEST_BOOK', '7', 'admin')
    assert result['enabled'] is True
    assert result['approval_eligible'] is True
    assert result['engine_enabled'] is None
    assert result['latest_attempt'] is None


@pytest.mark.parametrize('change', ['secret', 'database', 'partial_weights', 'wrong_scope', 'nan', 'duplicate'])
def test_manifest_fails_closed_for_unsafe_or_incompatible_snapshot(tmp_path, change):
    snap = snapshot()
    scope = {'registry_id': 'test', 'portfolio_id': 'TEST_BOOK',
             'engine_strategy_id': 'LIVE_TEST', 'config_snapshot': snap}
    data = {'version': 1, 'scopes': [scope]}
    if change == 'secret':
        snap['strategies']['TEST']['config']['password'] = 'synthetic-only'
    elif change == 'database':
        snap['database'] = {'host': 'synthetic.invalid'}
    elif change == 'partial_weights':
        snap['strategies']['TEST']['default_allocation'] = .5
    elif change == 'wrong_scope':
        snap['portfolio_id'] = 'OTHER_BOOK'
    elif change == 'nan':
        snap['initial_capital'] = float('nan')
    else:
        data['scopes'].append(copy.deepcopy(scope))
    config = RuntimeControlConfig({'QT_RUNTIME_CONFIG_MANIFEST': manifest(tmp_path, data)})
    with pytest.raises(RuntimeControlError, match='runtime_configuration_unavailable'):
        config.scope('test', 'TEST_BOOK')


def test_missing_or_unlisted_static_scope_cannot_activate(tmp_path):
    for env in ({}, {'QT_RUNTIME_CONFIG_MANIFEST': manifest(tmp_path)}):
        with pytest.raises(RuntimeControlError, match='runtime_scope_unsupported'):
            RuntimeControlConfig(env).scope('not-allowed', 'NEW_BOOK')


def test_status_can_be_read_while_control_is_disabled():
    repo = Repository()
    result = RuntimeControlService(repo, RuntimeControlConfig({})).status('test', 'TEST_BOOK', '7', 'admin')
    assert result['enabled'] is False
    assert result['approval_eligible'] is False
    assert repo.calls == [('status', {'strategy_id': 'test', 'portfolio_id': 'TEST_BOOK'})]
