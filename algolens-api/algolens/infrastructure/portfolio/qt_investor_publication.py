"""Immutable release storage; quantities come only from a proven desk receipt."""
from datetime import date
from hashlib import sha256
from psycopg2.extras import Json, RealDictCursor
from algolens.application.portfolio.qt_investor_publication import QtPublicationView
from algolens.domain.portfolio.qt_workflow_errors import QtWorkflowError
from algolens.infrastructure.db.postgres import get_db_connection
from algolens.infrastructure.portfolio.qt_evaluation_inputs import canonical_qt_input_bytes
from algolens.infrastructure.portfolio.qt_decision_read_repository import _stamp


def _digest(value):
    return sha256(canonical_qt_input_bytes(value)).hexdigest()


def _view(row):
    if _digest(row['snapshot']) != row['snapshot_digest']:
        raise QtWorkflowError('workflow_unavailable')
    snapshot = row['snapshot']
    if (snapshot.get('portfolio_id') != row['portfolio_id']
            or snapshot.get('source_day') != str(row['source_day'])
            or snapshot.get('portfolio_type') != 'qt'):
        raise QtWorkflowError('workflow_unavailable')
    return {'schema_version': 'qt-investor-publication/v1',
            'portfolio_id': row['portfolio_id'], 'source_day': str(row['source_day']),
            'portfolio_type': 'qt', 'published_at': _stamp(row['published_at']),
            'snapshot_digest': row['snapshot_digest'], 'snapshot': snapshot}


class QtReleaseAction:
    def __init__(self, actor_id, expected_digest):
        self.actor_id, self.expected_digest = actor_id, expected_digest

    def authorize(self, tx):
        # Called after ordered user locks and before registry/book locks. Holding
        # these rows prevents authority revocation racing the release commit.
        tx.cursor.execute("SELECT to_regclass('trading.qt_investor_publication_policy') AS policy, "
                          "to_regclass('trading.qt_investor_publish_grants') AS grants")
        tables = tx.cursor.fetchone()
        if not tables['policy'] or not tables['grants']:
            raise QtWorkflowError('authorization_changed')
        tx.cursor.execute('SELECT * FROM trading.qt_investor_publication_policy '
                          'WHERE book_id=%s FOR UPDATE', (tx.book_id,))
        self.policy = tx.cursor.fetchone()
        tx.cursor.execute('SELECT * FROM trading.qt_investor_publish_grants '
                          'WHERE book_id=%s AND user_id=%s FOR UPDATE', (tx.book_id, self.actor_id))
        self.grant = tx.cursor.fetchone()
        if not self.policy or not self.policy['enabled'] or not self.grant or not self.grant['active']:
            raise QtWorkflowError('authorization_changed')

    def replay(self, tx, decision):
        tx._require_mutable()
        if decision['selected_book_digest'] != self.expected_digest:
            raise QtWorkflowError('preview_mismatch')
        tx.cursor.execute('SELECT * FROM trading.qt_investor_publications '
                          'WHERE portfolio_id=%s AND source_day=%s',
                          (tx.book_id, decision['source_day']))
        existing = tx.cursor.fetchone()
        if existing is None:
            return None
        if (str(existing['decision_id']) != str(decision['decision_id'])
                or existing['selected_book_digest'] != self.expected_digest):
            raise QtWorkflowError('idempotency_conflict')
        return QtPublicationView(_view(existing))

    def save(self, tx, context, receipt):
        tx._require_mutable()
        decision = context['decision']
        payload = receipt['publication_payload']
        # The caller proved the full current receipt/read-set under this same
        # transaction's locks. Freeze complete accounting, expose quantities.
        positions = [{'key': row['key'], 'quantity_exact': row['quantity_exact']}
                     for row in payload['after_accounting']]
        positions.sort(key=lambda row: canonical_qt_input_bytes(row['key']))
        snapshot = {'portfolio_id': tx.book_id, 'source_day': str(decision['source_day']),
                    'portfolio_type': 'qt', 'positions': positions}
        tx.cursor.execute('INSERT INTO trading.qt_investor_publications '
            '(portfolio_id,source_day,portfolio_type,decision_id,attempt_id,selected_book_digest,'
            'processed_payload_digest,snapshot_digest,snapshot,published_by,policy_version,grant_version) '
            "VALUES(%s,%s,'qt',%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
            (tx.book_id, decision['source_day'], decision['decision_id'], receipt['attempt_id'],
             self.expected_digest, _digest(payload), _digest(snapshot), Json(snapshot), self.actor_id,
             self.policy['version'], self.grant['version']))
        return QtPublicationView(_view(tx.cursor.fetchone()))


class QtInvestorPublicationRepository:
    def __init__(self, connection_factory=None):
        self.connection_factory = connection_factory or get_db_connection

    def release_action(self, actor_id, expected_digest):
        return QtReleaseAction(actor_id, expected_digest)

    def get_public(self, book_id, source_day):
        try:
            if date.fromisoformat(source_day).isoformat() != source_day:
                raise ValueError()
        except (TypeError, ValueError):
            raise QtWorkflowError('invalid_qt_payload') from None
        conn = self.connection_factory()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute('SELECT p.* FROM trading.qt_investor_publications p '
                    'JOIN trading.qt_investor_publication_policy a ON a.book_id=p.portfolio_id '
                    'WHERE p.portfolio_id=%s AND p.source_day=%s AND a.enabled AND a.public_read_enabled',
                    (book_id, source_day))
                row = cursor.fetchone()
                if row is None:
                    raise QtWorkflowError('not_found')
                return _view(row)
        finally:
            conn.close()
