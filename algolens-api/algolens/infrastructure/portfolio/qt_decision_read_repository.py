"""Scoped SQL and filesystem prerequisites for the QT decision read port."""
from datetime import datetime, timezone
from pathlib import Path
import re
from psycopg2.extras import RealDictCursor
from algolens.domain.portfolio.qt_workflow_errors import QtWorkflowError
from algolens.infrastructure.portfolio.qt_workflow_repository import QtWorkflowRepository
from algolens.infrastructure.portfolio.qt_publication_proof import require_legacy_qt_disabled
from algolens.infrastructure.portfolio.qt_accounting_proof import load_accounting_evidence

def _stamp(value):
    return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z') if isinstance(value, datetime) else value


def _context(cursor, decision_id, book_id=None):
    cursor.execute('SELECT * FROM trading.qt_decisions WHERE decision_id=%s '
                   'AND (%s IS NULL OR book_id=%s)', (str(decision_id), book_id, book_id))
    raw = cursor.fetchone()
    if raw is None: raise QtWorkflowError('not_found')
    decision = dict(raw)
    cursor.execute('SELECT * FROM trading.qt_override_requests WHERE decision_id=%s', (str(decision_id),))
    raw = cursor.fetchone()
    request = dict(raw) if raw is not None else None
    approvals = []
    if request:
        cursor.execute('SELECT * FROM trading.qt_override_approvals WHERE request_id=%s ORDER BY approval_id',
                       (str(request['request_id']),))
        approvals = [dict(row) for row in cursor.fetchall()]
    return {'decision': decision, 'request': request, 'approvals': approvals}


class QtDecisionReadRepository(QtWorkflowRepository):
    def decision_routing(self, decision_id):
        conn = self._connection_factory()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                return _context(cursor, decision_id)
        finally:
            conn.close()

    def latest_routing(self, book_id, source_day):
        conn = self._connection_factory()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                if source_day is None:
                    cursor.execute("SELECT (clock_timestamp() AT TIME ZONE 'UTC')::date AS source_day")
                    source_day = cursor.fetchone()['source_day']
                cursor.execute('SELECT decision_id FROM trading.qt_decisions WHERE book_id=%s AND source_day=%s '
                               'ORDER BY created_at DESC,decision_id DESC LIMIT 1', (book_id, source_day))
                raw = cursor.fetchone()
                return source_day, _context(cursor, raw['decision_id'], book_id) if raw is not None else None
        finally:
            conn.close()


def _publication_evidence(tx, context, preview, receipt, facts):
    """Fixed scoped SELECT closure borrows the already ordered transaction."""
    tx._require_mutable()
    d = context['decision']
    cursor = tx.cursor
    pub = receipt['publication_payload']
    cursor.execute('SELECT o.* FROM trading.qt_execution_observations o '
                   'JOIN trading.qt_decisions d ON d.decision_id=o.decision_id '
                   'WHERE d.book_id=%s AND o.decision_id=%s AND o.observation_id=%s',
                   (tx.book_id, d['decision_id'], pub['observation_id']))
    raw = cursor.fetchone()
    observation = dict(raw) if raw is not None else None
    if observation:
        for name in ['as_of', 'valid_until']: observation[name] = _stamp(observation[name])
    cursor.execute('SELECT r.* FROM trading.qt_desk_results r JOIN trading.qt_decisions d '
                   'ON d.decision_id=r.decision_id WHERE d.book_id=%s AND r.decision_id=%s',
                   (tx.book_id, d['decision_id']))
    raw = cursor.fetchone()
    result = dict(raw) if raw is not None else None
    cursor.execute("SELECT enabled,producer_id,policy_version FROM trading.qt_source_policies "
                   "WHERE book_id=%s AND purpose='execution'", (tx.book_id,))
    raw = cursor.fetchone()
    policy = dict(raw) if raw is not None else None
    cursor.execute('SELECT decision_id FROM trading.qt_decisions WHERE book_id=%s AND source_day=%s '
                   'ORDER BY created_at DESC,decision_id DESC LIMIT 1', (tx.book_id, d['source_day']))
    latest = cursor.fetchone()
    source = tx.read_source_evidence()
    receipt = {**receipt, 'processed_at': _stamp(receipt['processed_at'])}
    accounting = load_accounting_evidence(cursor, d, pub['observation_id'], current=True)
    return {'decision': {**d, 'decision_id': str(d['decision_id'])}, 'preview': preview, 'receipt': receipt,
        'observation': observation, 'result': result, 'execution_policy': policy, 'audits': source['audits'],
        'accounting': accounting,
        'current_facts': facts, 'latest_decision_id': str(latest['decision_id']) if latest else None,
        'checked_at': facts['captured_at']}


class QtDecisionReadQueries:
    def decision_context(self, tx, decision_id, book_id):
        tx._require_mutable()
        return _context(tx.cursor, decision_id, book_id)

    def latest_decision_id(self, tx, book_id, source_day):
        tx._require_mutable()
        tx.cursor.execute('SELECT decision_id FROM trading.qt_decisions WHERE book_id=%s AND source_day=%s '
                          'ORDER BY created_at DESC,decision_id DESC LIMIT 1', (book_id, source_day))
        raw = tx.cursor.fetchone()
        return str(raw['decision_id']) if raw is not None else None

    def publication_evidence(self, tx, context, preview, receipt, facts):
        return _publication_evidence(tx, context, preview, receipt, facts)

    def require_legacy_disabled(self, tx):
        tx._require_mutable()
        return require_legacy_qt_disabled(tx.cursor, tx.book_id)

    def enabled_prerequisites(self, tx, bundle_directory):
        directory = bundle_directory
        if directory is None or not directory.is_dir() or directory.is_symlink(): return False
        manifest = directory / 'qt_evaluator_manifest.json'
        if not manifest.is_file() or manifest.is_symlink(): return False
        tx._require_mutable()
        tx.cursor.execute("SELECT to_regclass('trading.qt_source_policies') IS NOT NULL "
                          "AND to_regclass('trading.qt_evaluation_snapshots') IS NOT NULL "
                          "AND to_regclass('trading.qt_execution_observations') IS NOT NULL "
                          "AND to_regclass('trading.qt_desk_results') IS NOT NULL AS ready")
        if not tx.cursor.fetchone()['ready']: return False
        tx.cursor.execute("SELECT to_jsonb(p) AS policy FROM trading.qt_source_policies p "
                          "WHERE book_id=%s AND purpose='evaluation'", (tx.book_id,))
        raw = tx.cursor.fetchone()
        policy = raw['policy'] if raw is not None else None
        return bool(policy is not None and policy.get('enabled') is True and
            type(policy.get('version')) is int and policy['version'] > 0 and
            type(policy.get('evaluator_build')) is str and policy['evaluator_build'].strip() and
            type(policy.get('policy_version')) is str and policy['policy_version'].strip() and
            all(type(policy.get(name)) is str and re.fullmatch('[0-9a-f]{64}', policy[name])
                for name in ['evaluator_sha256', 'evaluator_bundle_sha256']))
