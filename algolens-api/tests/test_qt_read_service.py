"""Read access has current grants and registry scope, separate from submission."""
from copy import deepcopy
import pytest
from algolens.domain.portfolio.qt_workflow_errors import QtWorkflowError
from algolens.infrastructure.config.dependencies import create_qt_decision_read_service
from algolens.infrastructure.portfolio import qt_workflow_runtime as runtime
from algolens.infrastructure.portfolio import qt_decision_read_repository as storage
from tests.test_qt_a4_draft import DraftRepository, _ready_provenance, key


def setup_reader(monkeypatch, tmp_path, capability='qt_approve'):
    from algolens.application.portfolio import qt_decision_read as module
    assert hasattr(module, 'QtDecisionReadService'), 'A8 read-only workflow service is missing'
    repository = DraftRepository()
    tx = repository.tx
    tx.book_id = 'BOOK'
    tx.approval_authority = lambda actor: {'account': {'id': actor, 'role': 'general_member'},
        'grants': [{'user_id': actor, 'capability': capability, 'active': True, 'version': 1}], 'mappings': []}
    facts = tx.read_current_facts()
    facts['capability'].update(version=1)
    tx.capability = lambda: facts['capability']
    tx.read_current_facts = lambda **kwargs: deepcopy(facts)
    source_reader = tx.read_source_evidence
    tx.read_source_evidence = lambda: {**source_reader(), 'saved_accounting': [], 'processed_publications': []}
    monkeypatch.setattr(runtime, 'reconcile_qt_source', lambda *a, **k: _ready_provenance())
    (tmp_path / 'qt_evaluator_manifest.json').write_text('{}')  # Presence fixture; no closure verification claimed.
    class PolicyCursor:
        policy = {'enabled': True, 'version': 1, 'evaluator_build': 'synthetic-unit', 'policy_version': 'synthetic-policy',
                  'evaluator_sha256': 'a' * 64, 'evaluator_bundle_sha256': 'b' * 64}
        ready = True
        def execute(self, sql, params=()): self.sql = sql
        def fetchone(self): return {'ready': self.ready} if 'to_regclass' in self.sql else {'policy': deepcopy(self.policy)}
    tx.cursor = PolicyCursor()
    tx._require_mutable = lambda: None
    service = create_qt_decision_read_service(repository, evaluator_bundle_directory=tmp_path)
    return service, tx, facts


def test_approve_only_can_read_actual_model_seed_and_immutable_saved_qt(monkeypatch, tmp_path):
    service, tx, _ = setup_reader(monkeypatch, tmp_path)
    tx.saved_rows = [{'key': key('AAPL', 'qt').to_wire(), 'quantity_exact': '-0.125', 'average_price_exact': '99.5'}]
    result = service.get_proposal('BOOK', 101).to_wire()
    assert tx.lock_order == ['auth', 'registry', 'book', 'mutable']
    assert result['seed_rows'][0]['quantity_exact'] == '3'
    assert result['seed_rows'][0]['key']['portfolio_type'] == 'qt_proposal'
    assert result['saved_qt_rows'][0]['quantity_exact'] == '-0.125'
    assert result['saved_qt_rows'][0]['key']['portfolio_type'] == 'qt'
    assert result['action_grants']['can_save_draft'] is False
    assert service.get_draft('BOOK', 101).to_wire()['state'] == 'absent'
    assert tx.position_mutations == 0


@pytest.mark.parametrize('part', ['grant', 'registry', 'membership'])
def test_current_read_authority_is_rechecked(monkeypatch, tmp_path, part):
    service, tx, facts = setup_reader(monkeypatch, tmp_path, 'none' if part == 'grant' else 'qt_submit')
    if part == 'registry': facts['registry'][0]['is_active'] = False
    if part == 'membership': facts['memberships'] = []
    with pytest.raises(QtWorkflowError) as error: service.get_proposal('BOOK', 101)
    assert error.value.code == 'authorization_changed'


def test_unproven_source_remains_read_only_and_never_called_model(monkeypatch, tmp_path):
    from dataclasses import replace
    from algolens.application.portfolio import qt_decision_read as module
    service, _, _ = setup_reader(monkeypatch, tmp_path, 'qt_submit')
    monkeypatch.setattr(runtime, 'reconcile_qt_source', lambda *a, **k: replace(_ready_provenance(), status='unresolved'))
    result = service.get_proposal('BOOK', 101).to_wire()
    assert result['workflow_state'] == 'provenance_unresolved'
    assert result['seed_rows'] == []
    assert not any(result['action_grants'].values())


@pytest.mark.parametrize('missing', ['config', 'manifest', 'schema', 'policy', 'binary_pin', 'bundle_pin'])
def test_missing_cutover_prerequisite_blocks_advertised_actions(monkeypatch, tmp_path, missing):
    service, tx, _ = setup_reader(monkeypatch, tmp_path, 'qt_submit')
    if missing == 'config': service.evaluator_bundle_directory = None
    elif missing == 'manifest': (tmp_path / 'qt_evaluator_manifest.json').unlink()
    elif missing == 'schema': tx.cursor.ready = False
    elif missing == 'policy': tx.cursor.policy = None
    elif missing == 'binary_pin': tx.cursor.policy = {**tx.cursor.policy, 'evaluator_sha256': None}
    else: tx.cursor.policy = {**tx.cursor.policy, 'evaluator_bundle_sha256': None}
    result = service.get_proposal('BOOK', 101).to_wire()
    assert result['capability']['required'] is True and result['capability']['available'] is False
    assert result['workflow_state'] == 'workflow_unavailable'
    assert not any(result['action_grants'].values())
    assert result['seed_rows'][0]['origin'] == 'verified_model_seed'


@pytest.mark.parametrize('origin,display', [('verified_qt_decision','verified_qt_decision'), ('verified_qt_edit','reconciled_legacy_draft')])
def test_saved_display_labels_only_exact_proven_edit_keys(monkeypatch, tmp_path, origin, display):
    from dataclasses import replace
    from algolens.application.portfolio import qt_decision_read as module
    from algolens.infrastructure.portfolio.qt_provenance import QtExactPosition, QtVerifiedQtEdit
    service, tx, _ = setup_reader(monkeypatch, tmp_path)
    tx.saved_rows = [{'key': key(stream='qt').to_wire(), 'quantity_exact': '5', 'average_price_exact': '101'},
        {'key': key('AAPL','qt').to_wire(), 'quantity_exact': '-0.125', 'average_price_exact': '99'}]
    provenance = replace(_ready_provenance(), draft_overlay=(QtExactPosition(key(), '5', '101'),),
        verified_qt_edits=(QtVerifiedQtEdit(key(stream='qt'), key(), (100,), origin),))
    monkeypatch.setattr(runtime, 'reconcile_qt_source', lambda *a, **k: provenance)
    response = service.get_proposal('BOOK', 101).to_wire()
    selected = {row['key']['symbol']: row for row in response['saved_qt_rows']}
    assert selected['ES']['origin'] == display and selected['ES']['editable'] is True
    assert selected['ES']['quantity_exact'] == '5' and selected['ES']['average_price_exact'] == '101'
    assert selected['AAPL']['origin'] == 'immutable' and selected['AAPL']['editable'] is False
    assert response['seed_rows'][0]['quantity_exact'] == '3'


@pytest.mark.parametrize('day', ['bad', '20260925', '2026-9-25', ''])
def test_book_discovery_requires_canonical_source_day(monkeypatch, tmp_path, day):
    service, _, _ = setup_reader(monkeypatch, tmp_path)
    with pytest.raises(QtWorkflowError) as exc: service.get_book_decision('BOOK', 101, day)
    assert exc.value.code == 'invalid_qt_payload'


def decision_reader(monkeypatch):
    from contextlib import contextmanager
    from types import SimpleNamespace
    from tests.test_qt_decision_read import processed_fixture
    from tests.test_qt_a6_confirmation import confirmation_fixture
    from algolens.application.portfolio import qt_decision_read as module
    evidence = processed_fixture(monkeypatch)
    core, tx, _, _, _ = confirmation_fixture(monkeypatch)
    repository = core.repository
    context = {'decision': deepcopy(evidence['decision']), 'request': None, 'approvals': []}
    repository.decision_routing = lambda _: deepcopy(context)
    @contextmanager
    def transaction(book, actor):
        assert (book, actor) == ('BOOK', 202)
        yield tx
    repository.transaction = transaction
    tx.book_id, tx.cursor = 'BOOK', object()
    tx.lock_order = []
    def require_mutable():
        assert tx.lock_order[-1] == 'mutable'
    tx._require_mutable = require_mutable
    def authorities(ids):
        tx.lock_order.append('auth')
        assert set(ids) == {101, 202}
        return tuple({'id': user, 'role': 'general_member'} for user in ids)
    tx.lock_authorities = authorities
    tx.approval_authority = lambda actor: {'account': {'id': actor, 'role': 'general_member'},
        'grants': [{'user_id': actor, 'capability': 'qt_approve' if actor == 202 else 'qt_submit', 'active': True, 'version': 1}], 'mappings': []}
    actors = []
    def facts(*, actor_id=None):
        actors.append(actor_id)
        return deepcopy(evidence['current_facts'])
    tx.read_current_facts = facts
    tx.get_preview = lambda _: deepcopy(evidence['preview'])
    tx.get_receipt = lambda _: deepcopy(evidence['receipt'])
    monkeypatch.setattr(storage, '_context', lambda *a: deepcopy(context))
    monkeypatch.setattr(runtime, 'load_qt_evaluation_inputs', lambda *a, **k: SimpleNamespace(read_set_overrides={}))
    monkeypatch.setattr(storage, '_publication_evidence', lambda *a: {**deepcopy(evidence), 'current_facts': a[-1]})
    return create_qt_decision_read_service(repository), tx, evidence, actors, context


def test_decision_reader_separately_authorizes_reader_and_captures_submitter_source(monkeypatch):
    service, tx, _, actors, _ = decision_reader(monkeypatch)
    response = service.get_decision('00000000-0000-4000-8000-000000000081', 202).to_wire()
    assert response['report_ready'] is True
    assert response['status'] == 'confirmed_decision'
    assert response['can_approve'] is False
    assert actors == [101]
    assert tx.lock_order == ['auth', 'registry', 'book', 'mutable']
    assert tx.position_mutations == 0


@pytest.mark.parametrize('change', ['late_pending', 'accounting', 'policy'])
def test_decision_reader_never_promotes_unproven_receipt_flags(monkeypatch, change):
    service, _, evidence, _, _ = decision_reader(monkeypatch)
    if change == 'late_pending': evidence['latest_decision_id'] = '00000000-0000-4000-8000-000000000099'
    elif change == 'accounting': evidence['current_facts']['saved_accounting'][0]['quantity_exact'] = '9'
    else: evidence['execution_policy']['enabled'] = False
    assert service.get_decision('00000000-0000-4000-8000-000000000081', 202).to_wire()['report_ready'] is False


def test_changed_approval_discovery_requires_new_authority_snapshot(monkeypatch):
    from algolens.application.portfolio import qt_decision_read as module
    service, _, _, _, context = decision_reader(monkeypatch)
    changed = {**context, 'approvals': [{'approval_id': '00000000-0000-4000-8000-000000000001',
        'user_id': 303, 'person_id': 'eric_shwartz', 'mapping_version': 1, 'grant_version': 1}]}
    monkeypatch.setattr(storage, '_context', lambda *a: changed)
    with pytest.raises(QtWorkflowError) as exc: service.get_decision('00000000-0000-4000-8000-000000000081', 202)
    assert exc.value.code == 'authorization_changed'
    assert exc.value.retryable is True
