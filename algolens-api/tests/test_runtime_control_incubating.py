"""N5 (e): a controlled (approved) run accepts an ACTIVE incubating strategy, as the engine's model
publication does; retired, inactive and unknown lifecycles stay refused, and stop still requires retired."""
from datetime import datetime, timezone

import pytest

from algolens.adapters.http.runtime_control import MESSAGES
from algolens.application.runtime_control import RuntimeControlError
from algolens.infrastructure.portfolio.runtime_control import PostgresRuntimeControlRepository
from tests.test_runtime_control import snapshot

SCOPE = {'registry_id': 'test', 'portfolio_id': 'TEST_BOOK', 'engine_strategy_id': 'LIVE_TEST',
         'config_snapshot': snapshot()}


def registry(lifecycle, active=True, revision=0):
    return {'id': 'test', 'strategy_type': 'LIVE_TEST', 'portfolio_id': 'TEST_BOOK',
            'lifecycle': lifecycle, 'is_active': active, 'runtime_revision': revision}


@pytest.mark.parametrize('lifecycle', ['live', 'incubating'])
def test_run_admits_an_active_live_or_incubating_strategy(lifecycle):
    PostgresRuntimeControlRepository._check(registry(lifecycle), SCOPE, 'run')


@pytest.mark.parametrize('lifecycle,active', [('incubating', False), ('live', False), ('retired', True),
                                              ('retired', False), ('paper', True), ('Incubating', True),
                                              ('incubating', 'true'), ('incubating', 1), ('incubating', None)])
def test_run_refuses_inactive_retired_or_unknown_lifecycle(lifecycle, active):
    with pytest.raises(RuntimeControlError, match='runtime_lifecycle_conflict') as refused:
        PostgresRuntimeControlRepository._check(registry(lifecycle, active), SCOPE, 'run')
    assert refused.value.status == 409


@pytest.mark.parametrize('lifecycle', ['live', 'incubating'])
def test_stop_still_requires_a_retired_strategy(lifecycle):
    with pytest.raises(RuntimeControlError, match='runtime_lifecycle_conflict'):
        PostgresRuntimeControlRepository._check(registry(lifecycle), SCOPE, 'stop')
    PostgresRuntimeControlRepository._check(registry('retired', False), SCOPE, 'stop')


def test_scope_mismatch_is_checked_before_lifecycle():
    other = dict(registry('incubating'), strategy_type='LIVE_OTHER')
    with pytest.raises(RuntimeControlError, match='runtime_scope_unsupported'):
        PostgresRuntimeControlRepository._check(other, SCOPE, 'run')


class _Cursor:
    def __init__(self, registry_row):
        self.calls, self.registry_row, self.inserted = [], registry_row, None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=()):
        self.calls.append((' '.join(sql.split()), params))
        if 'INSERT INTO trading.runtime_intents' in sql:
            registry_id, book, engine, action, revision, snap, user, reason = params
            self.inserted = {'id': 11, 'registry_id': registry_id, 'portfolio_id': book,
                             'engine_strategy_id': engine, 'action': action, 'registry_revision': revision,
                             'config_snapshot': snap.adapted, 'status': 'pending', 'requested_by': user,
                             'request_reason': reason, 'approved_by': None, 'approval_reason': None,
                             'requested_at': datetime(2026, 9, 29, tzinfo=timezone.utc), 'approved_at': None}

    def fetchone(self):
        return self.inserted if self.inserted is not None else self.registry_row


class _Connection:
    def __init__(self, cursor):
        self._cursor, self.committed, self.rolled_back, self.closed = cursor, False, False, False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def _request(registry_row, action='run'):
    cursor = _Cursor(registry_row)
    connection = _Connection(cursor)
    repository = PostgresRuntimeControlRepository(lambda: connection)
    return repository, cursor, connection, lambda: repository.request(
        strategy_id='test', action=action, reason='Reviewed', user_id='7', scope=SCOPE)


def test_incubating_run_request_is_recorded_at_the_current_revision():
    """A lifecycle change bumps runtime_revision; the approved intent carries it, which is the only
    path an incubating scope with revision != 0 has (the uncontrolled revision-0 rule is unchanged)."""
    _, cursor, connection, call = _request(registry('incubating', revision=1))
    intent = call()
    assert (intent['action'], intent['registry_revision'], intent['status']) == ('run', 1, 'pending')
    assert connection.committed and not connection.rolled_back
    statements = [sql for sql, _ in cursor.calls]
    assert statements[0].startswith('SELECT id, strategy_type') and statements[0].endswith('FOR UPDATE')
    assert cursor.calls[1] == ('SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))',
                               ('algolens:qt-book:TEST_BOOK',))
    assert statements[2].startswith('INSERT INTO trading.runtime_intents')


@pytest.mark.parametrize('lifecycle,active', [('incubating', False), ('retired', True)])
def test_refused_run_request_writes_nothing(lifecycle, active):
    _, cursor, connection, call = _request(registry(lifecycle, active))
    with pytest.raises(RuntimeControlError, match='runtime_lifecycle_conflict'):
        call()
    assert connection.rolled_back and not connection.committed
    assert not any('INSERT' in sql for sql, _ in cursor.calls)


def test_conflict_message_names_both_run_lifecycles():
    assert MESSAGES['runtime_lifecycle_conflict'] == (
        'Run requests require an active live or incubating strategy; stop requests require a retired strategy.')
