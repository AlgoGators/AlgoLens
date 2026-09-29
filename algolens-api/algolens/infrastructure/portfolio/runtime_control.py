"""Transactional next-run requests; no engine calls or process control."""
from contextlib import contextmanager
import json

import psycopg2
from psycopg2.extras import Json

from algolens.application.runtime_control import RuntimeControlError, financial_summary, validate_snapshot
from algolens.infrastructure.db.postgres import get_db_connection
from algolens.infrastructure.portfolio.book_lock import acquire_qt_book_locks


def _iso(value):
    return value.isoformat() if value is not None else None


def _intent(row):
    if row is None:
        return None
    validate_snapshot(row['config_snapshot'], row['portfolio_id'], row['engine_strategy_id'])
    fields = ('id', 'registry_id', 'portfolio_id', 'engine_strategy_id', 'action',
              'registry_revision', 'status', 'requested_by', 'request_reason',
              'approved_by', 'approval_reason')
    result = {key: row[key] for key in fields}
    result.update(requested_at=_iso(row['requested_at']), approved_at=_iso(row['approved_at']),
                  financial_summary=financial_summary(row['config_snapshot']))
    return result


def _attempt(row):
    if row is None:
        return None
    fields = ('id', 'intent_id', 'registry_revision', 'producer_version', 'status',
              'publication_id', 'outcome')
    result = {key: row[key] for key in fields}
    # Never reflect arbitrary exception strings stored by a future producer.
    codes = {'publication_failed', 'runtime_request_stale', 'runtime_scope_unsupported',
             'runtime_lifecycle_conflict', 'runtime_configuration_mismatch',
             'runtime_storage_unavailable', 'computation_failed', 'abandoned_attempt'}
    result['failure_code'] = (row['failure_code'] if row['failure_code'] in codes
                              else 'publication_failed' if row['status'] == 'failed' else None)
    result.update(run_date=_iso(row['run_date']), started_at=_iso(row['started_at']),
                  finished_at=_iso(row['finished_at']))
    return result


class PostgresRuntimeControlRepository:
    def __init__(self, connection_factory=None):
        self.connection_factory = connection_factory or get_db_connection

    @contextmanager
    def _transaction(self, readonly=False):
        conn = None
        try:
            conn = self.connection_factory()
            if readonly:
                conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
            with conn.cursor() as cursor:
                yield cursor
            conn.commit()
        except Exception as exc:
            if conn is not None:
                conn.rollback()
            if isinstance(exc, psycopg2.Error):
                raise RuntimeControlError('runtime_storage_unavailable', 503) from None
            raise
        finally:
            if conn is not None:
                conn.close()

    @staticmethod
    def _registry(cursor, strategy_id, *, lock):
        cursor.execute('''SELECT id, strategy_type, portfolio_id, lifecycle, is_active,
                          runtime_revision FROM trading.strategy_registry WHERE id=%s'''
                       + (' FOR UPDATE' if lock else ''), (strategy_id,))
        registry = cursor.fetchone()
        if registry is None:
            raise RuntimeControlError('strategy_not_found', 404)
        return registry

    @staticmethod
    def _check(registry, scope, action):
        if (registry['id'] != scope['registry_id']
                or registry['strategy_type'] != scope['engine_strategy_id']
                or registry['portfolio_id'] != scope['portfolio_id']):
            raise RuntimeControlError('runtime_scope_unsupported')
        # A run publishes the MODEL (system stream): live or incubating, and active (the engine's
        # publishes_model rule and migration 025). The QT desk stays live-only (qt_workflow).
        if ((action == 'run' and (registry['lifecycle'] not in ('live', 'incubating')
                                  or registry['is_active'] is not True))
                or (action == 'stop' and registry['lifecycle'] != 'retired')):
            raise RuntimeControlError('runtime_lifecycle_conflict')

    def request(self, *, strategy_id, action, reason, user_id, scope):
        with self._transaction() as cur:
            registry = self._registry(cur, strategy_id, lock=True)
            acquire_qt_book_locks(cur, scope['portfolio_id'])
            self._check(registry, scope, action)
            cur.execute('''INSERT INTO trading.runtime_intents
                (registry_id,portfolio_id,engine_strategy_id,action,registry_revision,
                 config_snapshot,status,requested_by,request_reason)
                VALUES (%s,%s,%s,%s,%s,%s,'pending',%s,%s) RETURNING *''',
                (strategy_id, scope['portfolio_id'], scope['engine_strategy_id'], action,
                 registry['runtime_revision'], Json(scope['config_snapshot']), user_id, reason))
            return _intent(cur.fetchone())

    def approve(self, *, strategy_id, intent_id, reason, user_id, scope_loader):
        with self._transaction() as cur:
            registry = self._registry(cur, strategy_id, lock=True)
            cur.execute('SELECT * FROM trading.runtime_intents WHERE id=%s AND registry_id=%s',
                        (intent_id, strategy_id))
            pending = cur.fetchone()
            if pending is None:
                raise RuntimeControlError('runtime_request_not_found', 404)
            scope = scope_loader(strategy_id, pending['portfolio_id'])
            acquire_qt_book_locks(cur, scope['portfolio_id'])
            # All supported approval writers take this registry lock first.
            if (pending['status'] != 'pending'
                    or pending['registry_revision'] != registry['runtime_revision']
                    or pending['engine_strategy_id'] != scope['engine_strategy_id']
                    or json.dumps(pending['config_snapshot'], sort_keys=True) !=
                       json.dumps(scope['config_snapshot'], sort_keys=True)):
                raise RuntimeControlError('runtime_request_stale')
            self._check(registry, scope, pending['action'])
            cur.execute('''UPDATE trading.runtime_intents SET status='superseded'
                           WHERE registry_id=%s AND portfolio_id=%s AND engine_strategy_id=%s
                             AND status='approved' ''',
                        (strategy_id, scope['portfolio_id'], scope['engine_strategy_id']))
            cur.execute('''UPDATE trading.runtime_intents SET status='approved',
                           approved_by=%s,approval_reason=%s,approved_at=now()
                           WHERE id=%s AND status='pending' RETURNING *''',
                        (user_id, reason, intent_id))
            approved = cur.fetchone()
            if approved is None:
                raise RuntimeControlError('runtime_request_stale')
            return _intent(approved)

    def status(self, *, strategy_id, portfolio_id):
        with self._transaction(readonly=True) as cur:
            registry = self._registry(cur, strategy_id, lock=False)
            cur.execute('''SELECT * FROM trading.runtime_intents
                           WHERE registry_id=%s AND portfolio_id=%s ORDER BY id DESC LIMIT 1''',
                        (strategy_id, portfolio_id))
            intent = _intent(cur.fetchone())
            cur.execute('''SELECT * FROM trading.runtime_intents
                           WHERE registry_id=%s AND portfolio_id=%s AND status='approved'
                           ORDER BY id DESC LIMIT 1''', (strategy_id, portfolio_id))
            approved = _intent(cur.fetchone())
            cur.execute('''SELECT attempt.* FROM trading.runtime_attempts attempt
                           JOIN trading.runtime_intents intent ON intent.id=attempt.intent_id
                           WHERE intent.registry_id=%s AND intent.portfolio_id=%s
                           ORDER BY attempt.started_at DESC, attempt.id DESC LIMIT 1''',
                        (strategy_id, portfolio_id))
            attempt = _attempt(cur.fetchone())
            for item in (intent, approved):
                if item is not None:
                    item['stale'] = item['registry_revision'] != registry['runtime_revision']
            return {'intent': intent, 'approved_intent': approved, 'latest_attempt': attempt,
                    'registry_revision': registry['runtime_revision'],
                    'registry_lifecycle': registry['lifecycle']}
