"""Explicit synthetic immutable history exercises original native closure."""
from copy import deepcopy
from hashlib import sha256
import importlib.util
from pathlib import Path

import pytest

from algolens.domain.portfolio.qt_canonical import qt_digest_v1
from algolens.infrastructure.portfolio.qt_evaluation_inputs import canonical_qt_input_bytes
from algolens.infrastructure.portfolio.qt_read_set import canonical_internal_snapshot_bytes
from tests.test_qt_finalization_proof import finalized_receipt_fixture

MODULE = Path(__file__).parents[1] / 'algolens/infrastructure/portfolio/qt_original_processing_proof.py'


def helper():
    assert MODULE.is_file(), 'immutable original-processing proof is missing'
    spec = importlib.util.spec_from_file_location('qt_original_processing_proof', MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.verify_original_processing


def digest(value):
    return sha256(canonical_qt_input_bytes(value)).hexdigest()


@pytest.fixture
def original(monkeypatch):
    evidence = finalized_receipt_fixture(monkeypatch)
    accounting = evidence['accounting']
    accounting['processing_context'] = processing_context(evidence)
    return accounting


def rehash_snapshot(context):
    decision, preview, receipt = (context[name] for name in ('decision', 'preview', 'receipt'))
    read_digest = sha256(canonical_internal_snapshot_bytes('qt-read-set/v1', preview['read_set_payload'])).hexdigest()
    preview['read_set_digest'] = preview['payload']['read_set_digest'] = decision['read_set_digest'] = read_digest
    decision['payload']['read_set_digest'] = receipt['publication_payload']['read_set_digest'] = read_digest
    preview['payload']['payload_digest'] = qt_digest_v1({name: value for name, value in preview['payload'].items() if name != 'payload_digest'})
    preview['payload_digest'] = decision['payload']['preview_payload_digest'] = receipt['publication_payload']['preview_payload_digest'] = preview['payload']['payload_digest']


def processing_context(evidence):
    """Build one coherent public synthetic MODEL/read-set link for other fixtures."""
    context = {name: deepcopy(evidence[name]) for name in (
        'decision', 'preview', 'receipt', 'observation', 'result')}
    decision, snapshot = context['decision'], context['preview']['read_set_payload']
    seed = deepcopy(snapshot['system_rows'])
    assert seed and len({row['key']['strategy_id'] for row in seed}) == 1
    seed_digest = qt_digest_v1({'seed_rows': seed})
    ref = {**deepcopy(snapshot['publication_refs'][0]),
           'publication_id': decision['model_publication_id'],
           'strategy_id': seed[0]['key']['strategy_id'], 'seed_digest': seed_digest}
    snapshot['publication_refs'] = [ref]
    snapshot['provenance']['seed_digest'] = seed_digest
    proposals = [{**deepcopy(row), 'action': 'inserted',
        'origin_publication_id': decision['model_publication_id']} for row in snapshot['source_rows']]
    ref['proposal_manifest_digest'] = sha256(canonical_internal_snapshot_bytes(
        'qt-proposal-manifest/v1', {'proposal_rows': proposals})).hexdigest()
    context['model_publication'] = {**deepcopy(ref), 'portfolio_id': decision['book_id'],
        'source_day': decision['source_day'], 'system_components': seed, 'proposal_components': proposals}
    rehash_snapshot(context)
    return context


def test_complete_original_processing_is_immutable_and_uses_no_current_lease(original):
    before = deepcopy(original)
    assert helper()(original) is None
    assert original == before


@pytest.mark.parametrize('damage', ['changed', 'input_missing', 'observation_missing', 'both_empty'])
def test_original_observation_preserves_copied_input_source_version(original, damage):
    inputs = original['input_row']
    observed = original['processing_context']['observation']
    if damage == 'changed':
        inputs['source_version'] = 'different-version'
    elif damage == 'input_missing':
        del inputs['source_version']
    elif damage == 'observation_missing':
        del observed['source_version']
    else:
        inputs['source_version'] = observed['source_version'] = ''
    before = deepcopy(original)
    with pytest.raises(ValueError, match='unproven_original_processing'):
        helper()(original)
    assert original == before


@pytest.mark.parametrize('damage', [
    'missing_context', 'trusted_flag', 'pending_decision', 'pending_preview', 'decision_identity',
    'decision_envelope', 'preview_digest', 'read_set', 'selection', 'missing_receipt', 'pending_receipt',
    'receipt_attempt', 'receipt_scope', 'receipt_before', 'receipt_after', 'observation_identity',
    'observation_digest', 'observation_producer', 'observation_input', 'lease', 'result_identity',
    'result_digest', 'result_totals', 'model_scope', 'model_digest', 'accounting_input', 'accounting_digest'])
def test_detached_or_rehashed_original_records_are_refused(original, damage):
    context = original['processing_context']
    decision, preview, receipt, observation, result = (context[name] for name in (
        'decision', 'preview', 'receipt', 'observation', 'result'))
    if damage == 'missing_context': del original['processing_context']
    elif damage == 'trusted_flag': original['processing_context'] = {'processed': True}
    elif damage == 'pending_decision': decision['status'] = 'pending_override'
    elif damage == 'pending_preview': preview['state'] = 'pending'
    elif damage == 'decision_identity': decision['decision_id'] = '00000000-0000-4000-8000-000000000099'
    elif damage == 'decision_envelope': decision['payload']['preview_payload_digest'] = '0' * 64
    elif damage == 'preview_digest': preview['payload_digest'] = '0' * 64
    elif damage == 'read_set': preview['read_set_payload']['saved_accounting'] = []
    elif damage == 'selection': preview['payload']['selection_rows'][0]['quantity_exact'] = '3'
    elif damage == 'missing_receipt': del context['receipt']
    elif damage == 'pending_receipt': receipt['status'] = 'pending'
    elif damage == 'receipt_attempt': receipt['attempt_id'] = '00000000-0000-4000-8000-000000000099'
    elif damage == 'receipt_scope': receipt['publication_payload']['book_id'] = 'OTHER'
    elif damage == 'receipt_before': receipt['publication_payload']['before_accounting'] = []
    elif damage == 'receipt_after': receipt['publication_payload']['after_accounting'][0]['average_price_exact'] = '99'
    elif damage == 'observation_identity': observation['observation_id'] = '00000000-0000-4000-8000-000000000099'
    elif damage == 'observation_digest': observation['content_digest'] = '0' * 64
    elif damage == 'observation_producer': observation['producer_id'] = 'foreign'
    elif damage == 'observation_input': observation['payload']['accounting_input_id'] = 'foreign'
    elif damage == 'lease': receipt['processed_at'] = '2026-09-26T12:00:00Z'
    elif damage == 'result_identity': result['attempt_id'] = '00000000-0000-4000-8000-000000000099'
    elif damage == 'result_digest': result['content_digest'] = '0' * 64
    elif damage == 'result_totals':
        result['payload']['results']['currency_totals'][0]['actual_cash_cost_exact'] = '7'
        result['content_digest'] = receipt['publication_payload']['results_digest'] = digest(result['payload'])
    elif damage == 'model_scope': context['model_publication']['source_day'] = '2026-09-24'
    elif damage == 'model_digest': context['model_publication']['seed_digest'] = '0' * 64
    elif damage == 'accounting_input': original['input_row']['decision_id'] = 'foreign'
    elif damage == 'accounting_digest': original['content_digest'] = '0' * 64
    frozen = deepcopy(original)
    with pytest.raises(ValueError, match='unproven_original_processing'):
        helper()(original)
    assert original == frozen


@pytest.mark.parametrize('damage', ['missing_proposals', 'arbitrary_proposals', 'changed_proposals',
    'carry_with_execution', 'carry_without_prior', 'carry_prior_quantity', 'carry_prior_basis', 'carry_prior_owner'])
def test_actual_manifest_and_bounded_carried_owner_are_required(original, damage):
    context = original['processing_context']
    if damage == 'missing_proposals': del context['model_publication']['proposal_components']
    elif damage == 'arbitrary_proposals': context['model_publication']['proposal_components'] = [{'untrusted': True}]
    elif damage == 'changed_proposals': context['model_publication']['proposal_components'][0]['quantity_exact'] = '99'
    else:
        fill = context['observation']['payload']['fills'][0]
        fill.update(observation_kind='carried', execution_id=None, actual_cash_cost_exact='0')
        fill['average_price_exact'] = context['preview']['payload']['selection_rows'][0]['average_price_exact']
        context['receipt']['publication_payload']['after_accounting'][0]['average_price_exact'] = fill['average_price_exact']
        context['observation']['payload']['results']['currency_totals'][0]['actual_cash_cost_exact'] = '0'
        prior = {'key': {**fill['key'], 'date': original['input_row']['payload']['previous_day']},
                 'quantity_exact': fill['selected_quantity_exact'], 'average_price_exact': fill['average_price_exact']}
        original['input_row']['payload']['previous_positions'] = [prior]
        if damage != 'carry_with_execution': original['payload']['executions'] = []
        if damage == 'carry_without_prior': original['input_row']['payload']['previous_positions'] = []
        elif damage == 'carry_prior_quantity': prior['quantity_exact'] = '99'
        elif damage == 'carry_prior_basis': prior['average_price_exact'] = '99'
        elif damage == 'carry_prior_owner': prior['key']['strategy_id'] = 'FOREIGN'
        original['input_row']['content_digest'] = digest(original['input_row']['payload'])
        original['payload']['input_digest'] = original['input_row']['content_digest']
        rehash_observation(original)
    with pytest.raises(ValueError, match='unproven_original_processing'):
        helper()(original)


def test_bounded_unchanged_prior_carry_needs_no_recursive_ledger(original):
    context = original['processing_context']
    fill = context['observation']['payload']['fills'][0]
    fill.update(observation_kind='carried', execution_id=None, actual_cash_cost_exact='0')
    fill['average_price_exact'] = context['preview']['payload']['selection_rows'][0]['average_price_exact']
    context['receipt']['publication_payload']['after_accounting'][0]['average_price_exact'] = fill['average_price_exact']
    context['observation']['payload']['results']['currency_totals'][0]['actual_cash_cost_exact'] = '0'
    original['input_row']['payload']['previous_positions'] = [{
        'key': {**fill['key'], 'date': original['input_row']['payload']['previous_day']},
        'quantity_exact': fill['selected_quantity_exact'], 'average_price_exact': fill['average_price_exact']}]
    original['payload']['executions'] = []
    original['input_row']['content_digest'] = digest(original['input_row']['payload'])
    original['payload']['input_digest'] = original['input_row']['content_digest']
    rehash_observation(original)
    frozen = deepcopy(original)
    assert helper()(original) is None
    assert original == frozen


@pytest.mark.parametrize('field', ['decision_id', 'book_id', 'source_day'])
def test_coherently_rehashed_foreign_observation_scope_is_refused(original, field):
    context = original['processing_context']
    observation = context['observation']
    observation['payload'][field] = 'foreign'
    observation['content_digest'] = digest(observation['payload'])
    original['payload']['observation'] = deepcopy(observation['payload'])
    original['content_digest'] = digest(original['payload'])
    context['receipt']['publication_payload']['observation_digest'] = observation['content_digest']
    with pytest.raises(ValueError, match='unproven_original_processing'):
        helper()(original)


def rehash_observation(original):
    context = original['processing_context']
    observed = context['observation']
    observed['content_digest'] = digest(observed['payload'])
    original['payload']['observation'] = deepcopy(observed['payload'])
    original['content_digest'] = digest(original['payload'])
    context['receipt']['publication_payload']['observation_digest'] = observed['content_digest']
    context['result']['payload']['results'] = deepcopy(observed['payload']['results'])
    context['result']['content_digest'] = context['receipt']['publication_payload']['results_digest'] = digest(context['result']['payload'])


@pytest.mark.parametrize('damage', [
    'model_quantity', 'model_empty', 'model_owner', 'model_version', 'model_manifest', 'model_producer',
    'missing_model_ref', 'provenance_seed', 'provenance_unready', 'evaluator_build', 'evaluator_policy',
    'evaluator_unavailable', 'capability_disabled', 'capability_version', 'submitter_version',
    'submitter_missing', 'submitter_inactive', 'position_count', 'position_count_bool',
    'currency_total', 'extra_currency', 'fill_extra', 'fill_kind', 'fill_cost_negative',
    'fill_currency_empty', 'fill_source_empty', 'fill_execution_missing', 'fill_carried_cost', 'fill_basis_negative'])
def test_archived_bindings_and_rehashed_result_semantics_are_required(original, damage):
    context = original['processing_context']
    snapshot, model = context['preview']['read_set_payload'], context['model_publication']
    observed = context['observation']['payload']
    fill = observed['fills'][0]
    if damage == 'model_quantity':
        model['system_components'][0]['quantity_exact'] = '99'
        model['seed_digest'] = qt_digest_v1({'seed_rows': model['system_components']})
    elif damage == 'model_empty':
        model['system_components'] = []
        model['seed_digest'] = qt_digest_v1({'seed_rows': []})
    elif damage == 'model_owner': model['strategy_id'] = 'OTHER'
    elif damage == 'model_version': model['publication_version'] += 1
    elif damage == 'model_manifest': model['proposal_manifest_digest'] = '0' * 64
    elif damage == 'model_producer': model['producer_version'] = 'foreign'
    elif damage == 'missing_model_ref': snapshot['publication_refs'] = []
    elif damage == 'provenance_seed': snapshot['provenance']['seed_digest'] = '0' * 64
    elif damage == 'provenance_unready': snapshot['provenance']['status'] = 'provenance_unresolved'
    elif damage == 'evaluator_build': context['preview']['evaluator_build'] = 'foreign-recorded-build'
    elif damage == 'evaluator_policy': context['preview']['policy_version'] = context['decision']['policy_version'] = 'foreign'
    elif damage == 'evaluator_unavailable': snapshot['evaluator'] = {'status': 'unavailable', 'build': None, 'policy_version': None}
    elif damage == 'capability_disabled': snapshot['capability']['enabled'] = False
    elif damage == 'capability_version': context['decision']['workflow_capability_version'] += 1
    elif damage == 'submitter_version': context['decision']['submitter_grant_version'] = 999
    elif damage == 'submitter_missing': snapshot['grants'] = []
    elif damage == 'submitter_inactive': snapshot['grants'][0]['active'] = False
    elif damage == 'position_count': observed['results']['position_count'] = 999
    elif damage == 'position_count_bool': observed['results']['position_count'] = True
    elif damage == 'currency_total': observed['results']['currency_totals'][0]['actual_cash_cost_exact'] = '99'
    elif damage == 'extra_currency': observed['results']['currency_totals'].append({**observed['results']['currency_totals'][0], 'currency': 'EUR'})
    elif damage == 'fill_extra': fill['untrusted'] = True
    elif damage == 'fill_kind': fill['observation_kind'] = 'assumed'
    elif damage == 'fill_cost_negative': fill['actual_cash_cost_exact'] = '-1'
    elif damage == 'fill_currency_empty': fill['currency'] = ''
    elif damage == 'fill_source_empty': fill['accounting_source_id'] = ''
    elif damage == 'fill_execution_missing': fill['execution_id'] = None
    elif damage == 'fill_carried_cost': fill['observation_kind'] = 'carried'
    elif damage == 'fill_basis_negative':
        fill['average_price_exact'] = '-1'
        context['receipt']['publication_payload']['after_accounting'][0]['average_price_exact'] = '-1'
    rehash_snapshot(context)
    rehash_observation(original)
    frozen = deepcopy(original)
    with pytest.raises(ValueError, match='unproven_original_processing'):
        helper()(original)
    assert original == frozen
