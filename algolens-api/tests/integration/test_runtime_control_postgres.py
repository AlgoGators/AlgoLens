"""Approval snapshots/revisions against owned disposable PostgreSQL only."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from threading import Event

import psycopg2
from psycopg2.extras import RealDictCursor
import pytest

from tests.integration.conftest import claim_schema, require_test_dsn
from tests.test_runtime_control import snapshot
from algolens.application.runtime_control import RuntimeControlError
from algolens.infrastructure.portfolio.runtime_control import PostgresRuntimeControlRepository

pytestmark = pytest.mark.integration


@pytest.fixture
def database():
    dsn = require_test_dsn()
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    with conn.cursor() as cursor:
        claim_schema(cursor)
        cursor.execute('''CREATE TABLE trading.strategy_registry (
          id TEXT PRIMARY KEY, strategy_type TEXT NOT NULL, portfolio_id TEXT NOT NULL,
          lifecycle TEXT NOT NULL, is_active BOOLEAN NOT NULL);
          CREATE TABLE trading.strategy_book_memberships (
          strategy_id TEXT REFERENCES trading.strategy_registry(id), portfolio_id TEXT,
          PRIMARY KEY(strategy_id,portfolio_id));
          INSERT INTO trading.strategy_registry VALUES ('test','LIVE_TEST','TEST_BOOK','live',true);
          INSERT INTO trading.strategy_book_memberships VALUES ('test','TEST_BOOK');''')
        # Runtime-only fixture: the producer's integration fixture separately
        # tests full row shapes. These declared prerequisites exercise 013's
        # all-or-nothing fence installation, not an absent-table shortcut.
        for table in ('positions', 'risk_limits', 'live_results', 'equity_curve',
                      'executions', 'signals', 'live_run_metadata', 'run_inputs'):
            cursor.execute(f'CREATE TABLE trading.{table} '
                           '(strategy_id TEXT, portfolio_id TEXT, portfolio_type TEXT)')
        migration = Path(__file__).resolve().parents[4] / 'trade-ngin-qt/migrations/013_runtime_control.sql'
        cursor.execute(migration.read_text())
    def factory():
        return psycopg2.connect(dsn, cursor_factory=RealDictCursor,
                               options='-c statement_timeout=10000 -c lock_timeout=3000')
    yield conn, PostgresRuntimeControlRepository(factory)
    conn.close()


def scope(*_):
    return {'registry_id': 'test', 'portfolio_id': 'TEST_BOOK',
            'engine_strategy_id': 'LIVE_TEST', 'config_snapshot': snapshot()}


def request(repo, action='run'):
    return repo.request(strategy_id='test', action=action, reason='Reviewed', user_id='7', scope=scope())


def approve(repo, intent):
    return repo.approve(strategy_id='test', intent_id=intent['id'], reason='Approved',
                        user_id='8', scope_loader=scope)


def test_request_approval_and_status_never_claim_applied(database):
    _, repo = database
    intent = request(repo)
    assert intent['status'] == 'pending'
    assert intent['registry_revision'] == 0
    assert 'config_snapshot' not in intent
    assert intent['financial_summary']['initial_capital'] == 1000
    approved = approve(repo, intent)
    assert approved['status'] == 'approved'
    assert approved['approved_by'] == '8'
    result = repo.status(strategy_id='test', portfolio_id='TEST_BOOK')
    assert result['intent']['id'] == intent['id']
    assert result['latest_attempt'] is None


def test_aba_lifecycle_invalidates_pending_approval(database):
    conn, repo = database
    intent = request(repo)
    with conn.cursor() as cur:
        cur.execute("UPDATE trading.strategy_registry SET lifecycle='retired'")
        cur.execute("UPDATE trading.strategy_registry SET lifecycle='live'")
    with pytest.raises(RuntimeControlError, match='runtime_request_stale'):
        approve(repo, intent)
    assert repo.status(strategy_id='test', portfolio_id='TEST_BOOK')['intent']['status'] == 'pending'


def test_membership_revision_invalidates_pending_approval(database):
    conn, repo = database
    intent = request(repo)
    with conn.cursor() as cur:
        cur.execute("INSERT INTO trading.strategy_book_memberships VALUES ('test','OTHER_BOOK')")
    with pytest.raises(RuntimeControlError, match='runtime_request_stale'):
        approve(repo, intent)


def test_reapproval_supersedes_without_rewriting_old_snapshot(database):
    _, repo = database
    first = approve(repo, request(repo))
    second = approve(repo, request(repo))
    assert second['id'] != first['id']
    assert repo.status(strategy_id='test', portfolio_id='TEST_BOOK')['intent']['id'] == second['id']
    with pytest.raises(RuntimeControlError, match='runtime_request_stale'):
        approve(repo, first)


def test_approval_failure_rolls_back_superseding_prior_approval(database):
    conn, repo = database
    first = approve(repo, request(repo))
    second = request(repo)
    with conn.cursor() as cur:
        cur.execute('''CREATE FUNCTION trading.fail_approval() RETURNS trigger LANGUAGE plpgsql AS $$
          BEGIN IF NEW.id > 1 AND NEW.status='approved' THEN RAISE EXCEPTION 'synthetic'; END IF;
          RETURN NEW; END $$;
          CREATE TRIGGER fail_approval BEFORE UPDATE ON trading.runtime_intents
          FOR EACH ROW EXECUTE FUNCTION trading.fail_approval();''')
    with pytest.raises(RuntimeControlError, match='runtime_storage_unavailable'):
        approve(repo, second)
    with conn.cursor() as cur:
        cur.execute('SELECT status FROM trading.runtime_intents WHERE id=%s', (first['id'],))
        assert cur.fetchone()[0] == 'approved'


def test_stop_requires_retired_and_run_requires_active_live(database):
    conn, repo = database
    with pytest.raises(RuntimeControlError, match='runtime_lifecycle_conflict'):
        request(repo, 'stop')
    with conn.cursor() as cur:
        cur.execute("UPDATE trading.strategy_registry SET lifecycle='retired'")
    assert approve(repo, request(repo, 'stop'))['action'] == 'stop'
    with pytest.raises(RuntimeControlError, match='runtime_lifecycle_conflict'):
        request(repo)


def test_static_configuration_change_refuses_approval(database):
    _, repo = database
    intent = request(repo)
    def changed(*_):
        value = scope()
        value['config_snapshot']['initial_capital'] = 2000
        return value
    with pytest.raises(RuntimeControlError, match='runtime_request_stale'):
        repo.approve(strategy_id='test', intent_id=intent['id'], reason='Review',
                     user_id='8', scope_loader=changed)


def test_reporting_membership_is_not_executable_primary_scope(database):
    _, repo = database
    alternate = scope()
    alternate['portfolio_id'] = 'OTHER_BOOK'
    with pytest.raises(RuntimeControlError, match='runtime_scope_unsupported'):
        repo.request(strategy_id='test', action='run', reason='Review', user_id='7', scope=alternate)


def test_http_jwt_csrf_request_and_approval_reach_real_postgres(database, client, monkeypatch, tmp_path):
    from tests.test_incubation_routes import _set_jwt_cookie
    from tests.test_runtime_control import manifest
    from algolens.application.runtime_control import RuntimeControlService
    from algolens.infrastructure.config.runtime_control import RuntimeControlConfig
    from algolens.adapters.http import runtime_control as http
    _, repo = database
    config = RuntimeControlConfig({'QT_RUNTIME_CONTROL_ENABLED': 'true',
        'QT_RUNTIME_APPROVER_IDS': '8', 'QT_RUNTIME_CONFIG_MANIFEST': manifest(tmp_path)})
    monkeypatch.setattr(http, '_service', lambda: RuntimeControlService(repo, config))
    url = '/portfolio/strategies/test/runtime'
    csrf = _set_jwt_cookie(client, role='general_member', identity='7')
    response = client.post(url+'/requests', json={'action':'run','portfolio_id':'TEST_BOOK','reason':'Review'},
                           headers={'X-CSRF-TOKEN':csrf})
    assert response.status_code == 201
    intent_id = response.json['intent']['id']
    csrf = _set_jwt_cookie(client, role='admin', identity='8')
    response = client.post(f'{url}/requests/{intent_id}/approve', json={'reason':'Exact config reviewed'},
                           headers={'X-CSRF-TOKEN':csrf})
    assert response.status_code == 200
    status = client.get(url+'?portfolio_id=TEST_BOOK')
    assert status.status_code == 200
    assert status.json['intent']['approved_by'] == '8'
    assert status.json['latest_attempt'] is None
    assert status.json['engine_enabled'] is None


@pytest.mark.parametrize('operation', ['request', 'approve'])
def test_runtime_mutation_waits_for_exact_canonical_book_lock(database, operation):
    _, repo = database
    pending = request(repo) if operation == 'approve' else None
    lock_connection = psycopg2.connect(require_test_dsn())
    started = Event()
    def mutate():
        started.set()
        return approve(repo, pending) if pending else request(repo)
    with lock_connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ('algolens:qt-book:TEST_BOOK',))
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(mutate)
        try:
            assert started.wait(2)
            with pytest.raises(FutureTimeoutError):
                future.result(timeout=.2)
        finally:
            lock_connection.rollback()
            lock_connection.close()
        assert future.result(timeout=5)['status'] in ('pending', 'approved')
