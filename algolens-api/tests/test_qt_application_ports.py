"""QT application policies receive ports; runtime factories compose implementations."""
from types import SimpleNamespace
import pytest

from algolens.application.portfolio.qt_workflow import QtWorkflowService
from algolens.application.portfolio.qt_decision_read import QtDecisionReadService
from algolens.infrastructure.config import dependencies
from tests.test_qt_a4_draft import DraftRepository, _ready_provenance


def test_qt_runtime_composition_is_explicit_and_does_not_open_database():
    assert hasattr(dependencies, 'create_qt_workflow_service')
    assert hasattr(dependencies, 'create_qt_decision_read_service')
    class Repository:
        def transaction(self, *args): raise AssertionError('composition opened a transaction')
    repository = Repository()
    workflow = dependencies.create_qt_workflow_service(repository)
    reader = dependencies.create_qt_decision_read_service(repository)
    assert workflow.repository is reader.repository is repository


@pytest.mark.parametrize('service', [QtWorkflowService, QtDecisionReadService])
def test_application_service_requires_explicit_ports(service):
    with pytest.raises(TypeError): service()


def test_application_draft_policy_uses_injected_proof_and_ordered_repository():
    repository = DraftRepository()
    evidence = SimpleNamespace(reconcile_source=lambda *a, **k: _ready_provenance())
    service = QtWorkflowService(repository, evidence=evidence, input_loader=object(), evaluator=object(), authorization=object())
    response = service.get_draft('BOOK', 101).to_wire()
    assert response['selection_rows'][0]['quantity_exact'] == '3'
    assert repository.tx.lock_order == ['auth', 'registry', 'book', 'mutable']
    assert repository.tx.position_mutations == 0
