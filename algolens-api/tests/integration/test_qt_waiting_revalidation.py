"""Deterministic real SQL waiters revalidate authority and source after release."""
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Barrier, Event
from time import monotonic
from uuid import uuid4

import psycopg2
import pytest

from algolens.domain.portfolio.qt_workflow_errors import QtWorkflowError
from algolens.infrastructure.portfolio.book_lock import acquire_qt_book_locks
from algolens.infrastructure.portfolio.qt_workflow_repository import QtTransaction
from tests.integration.test_qt_a3_read_set_postgres import a3_db
from tests.integration.test_qt_preview_evaluator import preview_db, query
from tests.integration.test_qt_a6_confirmation_postgres import prepared
from tests.integration.test_qt_a7_approval_postgres import pending, approval_request


TABLES = ('positions', 'position_overrides', 'qt_drafts', 'qt_draft_heads',
    'qt_previews', 'qt_decisions', 'qt_override_requests', 'qt_override_approvals',
    'qt_idempotency', 'qt_desk_receipts', 'qt_desk_results', 'qt_execution_observations')
FINANCIAL_TABLES = ('positions', 'position_overrides', 'qt_desk_receipts',
                    'qt_desk_results', 'qt_execution_observations')


def state(connection):
    with connection.cursor() as cursor:
        result = {}
        for name in TABLES:
            cursor.execute('SELECT to_jsonb(t) FROM trading.' + name + ' t ORDER BY to_jsonb(t)::text')
            result[name] = cursor.fetchall()
        return result


def queued(dsn, service, monkeypatch, stage, actions, mutation=None):
    """Prove all callers are actual DB lock waiters before committing changes.

    Events/barrier identify transactions; pg_blocking_pids proves the wait.
    No scheduling delay is treated as evidence that a caller reached a lock.
    Every failure releases the holder before executor joins; SQL is bounded.
    """
    options = '-c lock_timeout=10000 -c statement_timeout=15000'
    service.repository._connection_factory = lambda: psycopg2.connect(dsn, options=options)
    holder = psycopg2.connect(dsn, options=options)
    observer = psycopg2.connect(dsn, options=options)
    observer.autocommit = True
    rendezvous = Barrier(len(actions) + 1)
    pids = Queue()
    original = getattr(QtTransaction, stage)

    def reached(tx, *args, **kwargs):
        pids.put(tx.cursor.connection.get_backend_pid())
        rendezvous.wait(timeout=10)
        return original(tx, *args, **kwargs)

    def invoke(action):
        try:
            return action().to_wire()
        except QtWorkflowError as error:
            return {'rejected': error.code}

    executor = ThreadPoolExecutor(max_workers=len(actions))
    futures = []
    try:
        with holder.cursor() as cursor:
            if stage == 'lock_authorities':
                cursor.execute('SELECT id FROM auth.users WHERE id=101 FOR UPDATE')
            else:
                assert stage == 'lock_books'
                acquire_qt_book_locks(cursor, 'BOOK')
        monkeypatch.setattr(QtTransaction, stage, reached)
        futures = [executor.submit(invoke, action) for action in actions]
        rendezvous.wait(timeout=10)
        waiters = [pids.get(timeout=1) for _ in actions]
        deadline = monotonic() + 8
        tick = Event()
        while True:
            with observer.cursor() as cursor:
                cursor.execute('SELECT pid,cardinality(pg_blocking_pids(pid)) FROM unnest(%s::int[]) pid', (waiters,))
                blocked = cursor.fetchall()
            if len(blocked) == len(actions) and all(count > 0 for _, count in blocked):
                break
            assert monotonic() < deadline, ('expected actual SQL waiters', blocked)
            tick.wait(0.01)
        if mutation:
            with holder.cursor() as cursor:
                cursor.execute(mutation)
        expected = state(holder)
        holder.commit()
        results = [future.result(timeout=20) for future in futures]
        after = state(observer)
        return results, expected, after
    finally:
        # Unblock real PostgreSQL waiters even when a barrier/assertion fails.
        holder.rollback()
        holder.close()
        rendezvous.abort()
        for future in futures:
            future.cancel()
        executor.shutdown(wait=True, cancel_futures=True)
        observer.close()


@pytest.mark.parametrize('stage,mutation', [
    ('lock_books', "UPDATE trading.positions SET quantity=9 WHERE portfolio_type='qt_proposal'"),
    ('lock_books', "UPDATE trading.positions SET quantity=0 WHERE portfolio_type='qt_proposal'"),
    ('lock_books', "DELETE FROM trading.positions WHERE portfolio_type='qt_proposal'"),
    ('lock_books', "INSERT INTO trading.positions "
        "(portfolio_id,strategy_id,strategy_name,date,symbol,portfolio_type,quantity,average_price,qt_proposal_revision) "
        "SELECT portfolio_id,strategy_id,strategy_name,date,'INSERTED',portfolio_type,quantity,average_price,qt_proposal_revision "
        "FROM trading.positions WHERE portfolio_type='qt_proposal'"),
    ('lock_books', "UPDATE trading.qt_source_policies SET version=version+1"),
    ('lock_authorities', "UPDATE auth.users SET role='guest' WHERE id=101"),
    ('lock_authorities', "UPDATE trading.qt_action_grants SET active=false,version=version+1 WHERE user_id=101"),
])
def test_confirmation_waiter_rechecks_committed_source_or_authority(preview_db, monkeypatch, stage, mutation):
    service, preview, request = prepared(preview_db)
    results, expected, actual = queued(preview_db, service, monkeypatch, stage,
        [lambda: service.confirm_preview(preview['preview_id'], 101, request)], mutation)
    assert results[0].get('rejected') in {'preview_stale', 'provenance_unresolved', 'authorization_changed', 'draft_stale'}, results
    assert actual == expected


@pytest.mark.parametrize('stage,mutation', [
    ('lock_books', "UPDATE trading.positions SET quantity=9 WHERE portfolio_type='qt_proposal'"),
    ('lock_books', "UPDATE trading.qt_source_policies SET version=version+1"),
    ('lock_authorities', "UPDATE auth.users SET role='guest' WHERE id=202"),
    ('lock_authorities', "UPDATE trading.qt_action_grants SET active=false,version=version+1 WHERE user_id=202 AND capability='qt_approve'"),
    ('lock_authorities', "UPDATE trading.qt_approver_allowlist SET active=false,mapping_version=mapping_version+1 WHERE user_id=202"),
])
def test_second_approval_waiter_rechecks_first_person_and_source(preview_db, monkeypatch, stage, mutation):
    service, decision = pending(preview_db)
    assert query(preview_db, 'SELECT created_by FROM trading.qt_decisions') == [(101,)]
    service.approve_override(decision['request_id'], 202, approval_request())
    assert query(preview_db, 'SELECT user_id FROM trading.qt_override_approvals') == [(202,)]
    results, expected, actual = queued(preview_db, service, monkeypatch, stage,
        [lambda: service.approve_override(decision['request_id'], 303, approval_request())], mutation)
    assert results[0].get('rejected') in {'preview_stale', 'provenance_unresolved', 'authorization_changed', 'draft_stale', 'approval_identity_unmapped'}, results
    assert actual == expected


def test_two_confirmations_are_observed_waiting_before_single_consumption(preview_db, monkeypatch):
    service, preview, request = prepared(preview_db)
    def action(key):
        return lambda: service.confirm_preview(preview['preview_id'], 101, {**request, 'idempotency_key': key})
    results, expected, actual = queued(preview_db, service, monkeypatch, 'lock_authorities',
        [action(str(uuid4())), action(str(uuid4()))])
    assert {name: actual[name] for name in FINANCIAL_TABLES} == {name: expected[name] for name in FINANCIAL_TABLES}
    assert sum(value.get('status') == 'confirmed_decision' for value in results) == 1
    assert sum(value.get('rejected') == 'preview_consumed' for value in results) == 1
    assert query(preview_db, 'SELECT count(*) FROM trading.qt_decisions') == [(1,)]
    assert query(preview_db, 'SELECT count(*) FROM trading.qt_desk_receipts') == [(0,)]


def test_two_second_approvers_are_observed_waiting_before_single_promotion(preview_db, monkeypatch):
    service, decision = pending(preview_db)
    assert query(preview_db, 'SELECT created_by FROM trading.qt_decisions') == [(101,)]
    query(preview_db, 'UPDATE trading.qt_approver_allowlist SET active=true WHERE user_id=404')
    service.approve_override(decision['request_id'], 202, approval_request())
    assert query(preview_db, 'SELECT user_id FROM trading.qt_override_approvals') == [(202,)]
    def action(actor):
        return lambda: service.approve_override(decision['request_id'], actor, approval_request())
    results, expected, actual = queued(preview_db, service, monkeypatch, 'lock_authorities', [action(303), action(404)])
    assert {name: actual[name] for name in FINANCIAL_TABLES} == {name: expected[name] for name in FINANCIAL_TABLES}
    assert sum(value.get('status') == 'confirmed_decision' for value in results) == 1
    assert sum('rejected' in value for value in results) == 1
    assert query(preview_db, 'SELECT count(*) FROM trading.qt_override_approvals') == [(2,)]
    actors = {row[0] for row in query(preview_db, 'SELECT user_id FROM trading.qt_override_approvals')}
    assert actors in ({202, 303}, {202, 404})
    assert query(preview_db, 'SELECT status FROM trading.qt_decisions') == [('confirmed_decision',)]
    assert query(preview_db, 'SELECT state FROM trading.qt_previews') == [('confirmed_decision',)]
    assert query(preview_db, 'SELECT count(*) FROM trading.qt_desk_receipts') == [(0,)]
