"""Production authority checks use registry foreign keys, never engine aliases."""
from copy import deepcopy
import pytest

from algolens.domain.portfolio.qt_workflow_errors import QtWorkflowError
from algolens.infrastructure.config.dependencies import create_qt_workflow_service
from tests.test_qt_a4_draft import BOOK, DraftRepository, _ready_provenance, _save_request, choice, key
from tests.test_qt_preview import preview_fixture


@pytest.mark.parametrize('primary_book', [True, False])
def test_exact_registry_membership_allows_preview_authority_without_financial_defaults(monkeypatch, primary_book):
    service, repository, request = preview_fixture(monkeypatch)
    facts = repository.tx.read_current_facts()
    facts['registry'][0]['portfolio_id'] = BOOK if primary_book else 'PRIMARY_OTHER'
    facts['memberships'] = [{'strategy_id': 'registry-1', 'portfolio_id': BOOK}]
    repository.tx.read_current_facts = lambda: deepcopy(facts)
    def missing(*args, **kwargs):
        raise QtWorkflowError('preview_unavailable')
    monkeypatch.setattr('algolens.infrastructure.portfolio.qt_workflow_runtime.load_qt_evaluation_inputs', missing)
    response = service.create_preview(101, request).to_wire()
    assert response['unavailable_reasons'] == ['governed_inputs_unavailable']
    assert not response['confirmable']


@pytest.mark.parametrize('operation', ['save', 'preview'])
def test_engine_name_collision_cannot_borrow_a_foreign_registry_membership(monkeypatch, operation):
    monkeypatch.setattr('algolens.infrastructure.portfolio.qt_workflow_runtime.reconcile_qt_source',
                        lambda *a, **k: _ready_provenance())
    if operation == 'preview':
        service, repository, request = preview_fixture(monkeypatch)
    else:
        repository = DraftRepository()
        service = create_qt_workflow_service(repository)
        request = _save_request([choice(key(), '2')])
    facts = repository.tx.read_current_facts()
    facts['registry'].append({'id': 'LIVE_TREND', 'strategy_type': 'ANOTHER_ENGINE',
        'portfolio_id': BOOK, 'is_active': True, 'lifecycle': 'live'})
    facts['memberships'] = [{'strategy_id': 'LIVE_TREND', 'portfolio_id': BOOK}]
    repository.tx.read_current_facts = lambda: deepcopy(facts)
    with pytest.raises(QtWorkflowError) as refused:
        if operation == 'save': service.save_draft(BOOK, 101, request)
        else: service.create_preview(101, request)
    assert refused.value.code == 'authorization_changed'
    assert repository.tx.position_mutations == 0
