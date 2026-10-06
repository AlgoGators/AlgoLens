"""Server-retained evaluator authority reaches both existing publication paths."""
from datetime import date

import pytest

from algolens.infrastructure.config.dependencies import (
    create_qt_workflow_service, create_qt_decision_read_service)
from algolens.infrastructure.portfolio import qt_publication_proof
from algolens.infrastructure.portfolio.qt_provenance import reconcile_qt_source
from tests.test_qt_receipt_provenance import receipt_source


@pytest.mark.parametrize('compose', [create_qt_workflow_service, create_qt_decision_read_service])
@pytest.mark.parametrize('path', ['source', 'report'])
def test_retained_server_bundle_and_original_pins_reach_complete_proof(
        monkeypatch, tmp_path, compose, path):
    evidence, source, system, publication = receipt_source(monkeypatch)
    # The preview fixture stubs source discovery while building its immutable
    # record. Restore the actual source-to-receipt chain for this test.
    monkeypatch.setattr('algolens.infrastructure.portfolio.qt_workflow_runtime.reconcile_qt_source',
        reconcile_qt_source)
    retained = tmp_path / 'server-retained-bundle'
    service = compose(object(), evaluator_bundle_directory=retained)
    received = []

    def accounting_proof(actual, *, recompute_client_factory=None, finalization_recompute_client_factory=None):
        assert actual['decision'] == evidence['decision']
        assert callable(recompute_client_factory), 'retained recomputation authority was dropped'
        assert callable(finalization_recompute_client_factory), 'retained finalization authority was dropped'
        authority = {'evaluator_sha256': 'a' * 64, 'evaluator_bundle_sha256': 'b' * 64,
                     'evaluator_build': 'original-preview-build'}
        client = recompute_client_factory(authority)
        assert client.process.bundle_directory == retained
        assert str(client.process.executable) == str(retained / 'bin/qt_evaluator')
        assert client.process.expected_sha256 == authority['evaluator_sha256']
        assert client.process.expected_bundle_sha256 == authority['evaluator_bundle_sha256']
        assert client.process.expected_build == authority['evaluator_build']
        successor_client = finalization_recompute_client_factory(authority)
        assert successor_client.process.bundle_directory == retained
        assert successor_client.process.expected_sha256 == authority['evaluator_sha256']
        assert successor_client.process.expected_bundle_sha256 == authority['evaluator_bundle_sha256']
        assert successor_client.process.expected_build == authority['evaluator_build']
        received.append(actual['decision']['decision_id'])
        return {}

    monkeypatch.setattr(qt_publication_proof, 'producer_prior_carries', accounting_proof)
    if path == 'report':
        service.evidence.prove_report(evidence)
    else:
        result = service.evidence.reconcile_source('BOOK', date(2026, 9, 25), [publication],
            source, evidence['audits'], observed_system_rows=system,
            observed_saved_rows=evidence['current_facts']['saved_rows'],
            observed_saved_accounting=evidence['current_facts']['saved_accounting'],
            processed_publications=[evidence])
        assert result.status == 'ready'
    assert received == [evidence['decision']['decision_id']]


@pytest.mark.parametrize('compose', [create_qt_workflow_service, create_qt_decision_read_service])
def test_absent_retained_bundle_does_not_substitute_current_executable(monkeypatch, compose):
    evidence, _, _, _ = receipt_source(monkeypatch)
    kwargs = {'evaluator_executable': '/unretained/current-qt-evaluator'} if compose is create_qt_workflow_service else {}
    service = compose(object(), **kwargs)
    received = []

    def accounting_proof(actual, *, recompute_client_factory=None, finalization_recompute_client_factory=None):
        assert recompute_client_factory is None
        assert finalization_recompute_client_factory is None
        received.append(True)
        return {}

    monkeypatch.setattr(qt_publication_proof, 'producer_prior_carries', accounting_proof)
    service.evidence.prove_report(evidence)
    assert received == [True]


def test_explicit_evidence_port_is_preserved(tmp_path):
    supplied = object()
    service = create_qt_workflow_service(object(), evidence=supplied,
        evaluator_bundle_directory=tmp_path / 'retained')
    assert service.evidence is supplied


@pytest.mark.parametrize('compose', [create_qt_workflow_service, create_qt_decision_read_service])
@pytest.mark.parametrize('caller_owned', [False, True])
def test_composed_repository_preserves_its_factory_through_actual_current_facts(
        monkeypatch, tmp_path, compose, caller_owned):
    from algolens.infrastructure.portfolio import qt_workflow_repository as persistence

    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def execute(self, sql, params=()): self.sql = sql
        def fetchall(self): return []
        def fetchone(self):
            if 'SELECT id, role FROM auth.users' in self.sql:
                return {'id': 7, 'role': 'admin'}
            return None

    class Connection:
        def __init__(self): self.events = []; self.owned_cursor = Cursor()
        def cursor(self, **kwargs): return self.owned_cursor
        def commit(self): self.events.append('commit')
        def rollback(self): self.events.append('rollback')
        def close(self): self.events.append('close')

    connection = Connection()
    supplied_factory = lambda authority: None
    supplied_finalization_factory = lambda authority: None
    supplied_repository = (persistence.QtWorkflowRepository(
        lambda: connection, recompute_client_factory=supplied_factory,
        finalization_recompute_client_factory=supplied_finalization_factory) if caller_owned else None)
    service = compose(supplied_repository, connection_factory=lambda: connection,
        evaluator_bundle_directory=tmp_path / 'server-retained-bundle')
    expected_factory = supplied_factory if caller_owned else service.evidence._recompute_client_factory
    expected_finalization_factory = supplied_finalization_factory if caller_owned else service.evidence._finalization_recompute_client_factory
    assert callable(expected_factory)
    if caller_owned: assert service.repository is supplied_repository
    observed = []

    def reconcile(*args, **kwargs):
        observed.append((kwargs.get('recompute_client_factory'),kwargs.get('finalization_recompute_client_factory')))
        return reconcile_qt_source(*args, **kwargs)

    monkeypatch.setattr(persistence, 'reconcile_qt_source', reconcile)
    monkeypatch.setattr(persistence.QtTransaction, 'read_source_evidence', lambda self: {
        'captured_at': '2026-09-25T12:00:00Z', 'source_day': date(2026, 9, 25),
        'publications': [], 'source_rows': [], 'audits': [], 'saved_rows': [],
        'system_rows': [], 'saved_accounting': [], 'processed_publications': []})
    with service.repository.transaction('BOOK', 7) as transaction:
        # Exercise the real transaction and ordered lock stages. Empty source
        # records remain unavailable; this test grants no financial readiness.
        transaction.lock_authorities([])
        transaction.lock_registries([])
        transaction.lock_books([])
        transaction.lock_mutable(source_day=date(2026, 9, 25))
        facts = transaction.read_current_facts()
        assert facts['provenance']['status'] == 'provenance_unresolved'
    assert observed == [(expected_factory,expected_finalization_factory)]
    assert connection.events == ['commit', 'close']
