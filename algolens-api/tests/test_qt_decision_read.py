"""Current report readiness requires a verified publication, never receipt flags."""
from copy import deepcopy
from hashlib import sha256
import importlib
import json
from pathlib import Path

import pytest

from algolens.domain.portfolio.qt_canonical import qt_digest_v1, qt_book_digest_v1
from algolens.infrastructure.portfolio.qt_evaluation_inputs import canonical_qt_input_bytes
from algolens.infrastructure.portfolio.qt_read_set import capture_qt_read_set, canonical_internal_snapshot_bytes
from tests.test_qt_a6_confirmation import confirmation_fixture


MODULE = Path(__file__).resolve().parents[1] / 'algolens/infrastructure/portfolio/qt_decision_report_proof.py'


def source_hash(payload):
    return sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'),
                            ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def processed_fixture(monkeypatch):
    service, tx, original, preview_id, request = confirmation_fixture(monkeypatch)
    key = {**tx.preview['payload']['selection_rows'][0]['key'], 'portfolio_type': 'qt'}
    before = {'key': key, 'quantity_exact': '1', 'average_price_exact': '100',
              'daily_unrealized_pnl_exact': '1.25', 'daily_realized_pnl_exact': '-0.5',
              'last_update': '2026-09-25T11:59:00Z'}
    original['saved_accounting'] = [before]
    original['saved_rows'] = [{name: before[name] for name in ['key', 'quantity_exact', 'average_price_exact']}]
    capture = capture_qt_read_set(original)
    preview = deepcopy(tx.preview)
    preview['state'] = 'confirmed_decision'
    preview['read_set_payload'] = json.loads(canonical_internal_snapshot_bytes('qt-read-set/v1', capture.payload))
    preview['read_set_digest'] = preview['payload']['read_set_digest'] = capture.digest
    preview['payload']['payload_digest'] = qt_digest_v1({name: value for name, value in preview['payload'].items() if name != 'payload_digest'})
    preview['payload_digest'] = preview['payload']['payload_digest']
    decision = {'decision_id': '00000000-0000-4000-8000-000000000081', 'preview_id': preview_id,
                'book_id': 'BOOK', 'source_day': '2026-09-25', 'status': 'confirmed_decision',
                'model_publication_id': tx.head['model_publication_id'], 'draft_id': tx.head['draft_id'],
                'draft_revision': 1, 'selected_book_digest': preview['selected_book_digest'],
                'read_set_digest': capture.digest, 'created_by': 101,
                'workflow_capability_version': 1, 'submitter_grant_version': 1,
                'policy_version': preview['policy_version'], 'provenance_digest': preview['provenance_digest']}
    decision['payload'] = {'schema_version': 'qt-desk-decision/v1', **{name: decision[name] for name in
        ['decision_id', 'preview_id', 'book_id', 'source_day', 'selected_book_digest', 'read_set_digest']},
        'preview_payload_digest': preview['payload_digest']}
    after = {**before, 'quantity_exact': '2', 'average_price_exact': '101',
             'daily_unrealized_pnl_exact': '3', 'daily_realized_pnl_exact': '-1',
             'last_update': '2026-09-25T12:00:00Z'}
    observation = {'observation_id': '00000000-0000-4000-8000-000000000082',
                   'decision_id': decision['decision_id'], 'producer_id': 'synthetic-execution',
                   'policy_version': 'execution-v1', 'source_version': 'observation-v1',
                   'as_of': '2026-09-25T11:59:59Z', 'valid_until': '2026-09-25T12:01:00Z'}
    fill = {name: value for name, value in after.items() if name != 'quantity_exact'}
    fill.update(selected_quantity_exact='2', observation_kind='executed', actual_cash_cost_exact='0.02',
                currency='USD', execution_id='execution-1', accounting_source_id='accounting-1')
    results = {'position_count': 1, 'currency_totals': [{'currency': 'USD', 'actual_cash_cost_exact': '0.02',
               'daily_unrealized_pnl_exact': '3', 'daily_realized_pnl_exact': '-1'}]}
    observation['payload'] = {'schema_version': 'qt-execution/v1', 'decision_id': decision['decision_id'],
        'book_id': 'BOOK', 'source_day': '2026-09-25', 'fills': [fill], 'results': results}
    observation['content_digest'] = sha256(canonical_qt_input_bytes(observation['payload'])).hexdigest()
    result = {'decision_id': decision['decision_id'], 'attempt_id': '00000000-0000-4000-8000-000000000083',
              'observation_id': observation['observation_id']}
    result['payload'] = {'schema_version': 'qt-desk-result/v1', 'decision_id': decision['decision_id'],
        'observation_id': observation['observation_id'], 'book_id': 'BOOK', 'source_day': '2026-09-25',
        'selected_book_digest': decision['selected_book_digest'], 'results': results}
    result['content_digest'] = sha256(canonical_qt_input_bytes(result['payload'])).hexdigest()
    publication = {'schema_version': 'qt-desk-publication/v1', 'decision_id': decision['decision_id'],
        'attempt_id': result['attempt_id'], 'observation_id': observation['observation_id'],
        'book_id': 'BOOK', 'source_day': '2026-09-25', 'model_publication_id': decision['model_publication_id'],
        'preview_payload_digest': preview['payload_digest'], 'read_set_digest': capture.digest,
        'selected_book_digest': decision['selected_book_digest'], 'published_book_digest': decision['selected_book_digest'],
        'observation_digest': observation['content_digest'], 'results_digest': result['content_digest'],
        'before_accounting': [before], 'after_accounting': [after],
        'report_scope': {'portfolio_id': 'BOOK', 'strategy_id': key['strategy_id'],
                         'strategy_names': [key['strategy_name']], 'portfolio_type': 'qt', 'date': '2026-09-25'}}
    receipt = {'decision_id': decision['decision_id'], 'attempt_id': result['attempt_id'], 'status': 'processed',
               'published_book_digest': decision['selected_book_digest'], 'publication_payload': publication,
               'report_eligibility_status': 'eligible', 'report_reason_codes': [],
               'row_manifest_digest': qt_digest_v1({'component_keys': [key]}),
               'processed_at': '2026-09-25T12:00:00Z'}
    reference = {'schema_version': 'qt-desk-audit/v1', 'decision_id': decision['decision_id'],
        'attempt_id': result['attempt_id'], 'preview_id': preview_id, 'preview_payload_digest': preview['payload_digest'],
        'read_set_digest': capture.digest, 'selected_book_digest': decision['selected_book_digest'],
        'published_book_digest': decision['selected_book_digest'], 'observation_digest': observation['content_digest']}
    flat = lambda row: {**row['key'], 'quantity_exact': row['quantity_exact'], 'average_price_exact': row['average_price_exact']}
    audit = {'id': 100, 'user_id': 101, 'source_app': 'algolens', 'portfolio_id': 'BOOK',
             'strategy_id': key['strategy_id'], 'symbol': key['symbol'], 'before_state': flat(before),
             'after_state': flat(after), 'risk_check_result': reference}
    current = deepcopy(original)
    current['saved_accounting'] = [after]
    current['saved_rows'] = [{name: after[name] for name in ['key', 'quantity_exact', 'average_price_exact']}]
    current['audit_refs'].append({'id': 100, 'user_id': '101', 'source_app': 'algolens',
        'strategy_id': key['strategy_id'], 'symbol': key['symbol'], 'before_digest': source_hash(flat(before)),
        'after_digest': source_hash(flat(after))})
    current['provenance'] = {'status': 'unresolved', 'source_digest': None, 'chain_digest': None, 'seed_digest': None}
    return {'decision': decision, 'preview': preview, 'receipt': receipt, 'observation': observation,
            'result': result, 'audits': [audit], 'current_facts': current,
            'execution_policy': {'enabled': True, 'producer_id': observation['producer_id'],
                                 'policy_version': observation['policy_version']},
            'latest_decision_id': decision['decision_id'], 'checked_at': '2026-09-25T12:00:00Z'}


def reader():
    assert MODULE.is_file(), 'A8 processed publication verifier is missing'
    return importlib.import_module('algolens.infrastructure.portfolio.qt_decision_report_proof')


def test_actual_linked_publication_allows_current_report_ready(monkeypatch):
    evidence = processed_fixture(monkeypatch)
    assert reader().processed_report_blocked_reasons(evidence) == ()


@pytest.mark.parametrize('part', ['receipt', 'observation', 'result', 'audit_actor', 'audit_source',
    'audit_before', 'accounting', 'basis', 'source', 'registry', 'late_pending', 'manifest', 'missing_audit'])
def test_tamper_or_later_authority_change_blocks_without_mutation(monkeypatch, part):
    evidence = processed_fixture(monkeypatch)
    if part == 'receipt': evidence['receipt']['publication_payload']['observation_digest'] = '0' * 64
    elif part == 'observation': evidence['observation']['payload']['fills'][0]['average_price_exact'] = '102'
    elif part == 'result': evidence['result']['payload']['results']['position_count'] = 99
    elif part == 'audit_actor': evidence['audits'][0]['user_id'] = 999
    elif part == 'audit_source': evidence['audits'][0]['source_app'] = 'unknown'
    elif part == 'audit_before': evidence['audits'][0]['before_state'] = None
    elif part == 'accounting': evidence['current_facts']['saved_accounting'][0]['daily_realized_pnl_exact'] = '7'
    elif part == 'basis': evidence['current_facts']['saved_rows'][0]['average_price_exact'] = '999'
    elif part == 'source': evidence['current_facts']['source_rows'][0]['quantity_exact'] = '7'
    elif part == 'registry': evidence['current_facts']['registry'][0]['is_active'] = False
    elif part == 'late_pending': evidence['latest_decision_id'] = '00000000-0000-4000-8000-000000000084'
    elif part == 'manifest': evidence['receipt']['row_manifest_digest'] = '0' * 64
    else: evidence['audits'] = []
    before = deepcopy(evidence)
    assert reader().processed_report_blocked_reasons(evidence) == ('report_snapshot_stale',)
    assert evidence == before


def test_zero_inclusion_and_full_key_mapping_are_independently_required(monkeypatch):
    evidence = processed_fixture(monkeypatch)
    before, after = evidence['receipt']['publication_payload']['before_accounting'], evidence['receipt']['publication_payload']['after_accounting']
    before[0]['quantity_exact'] = '0'
    assert reader().report_row_manifest(before, after, evidence['preview']['payload']['selection_rows']) == qt_digest_v1({'component_keys': [before[0]['key']]})
    before[0]['quantity_exact'] = '1'
    assert reader().report_row_manifest(before, after, evidence['preview']['payload']['selection_rows']) == evidence['receipt']['row_manifest_digest']
    after[0]['key']['strategy_id'] = 'another-owner'
    assert reader().report_row_manifest(before, after, evidence['preview']['payload']['selection_rows']) is None


@pytest.mark.parametrize('asset_type', ['EQUITY', 'FUTURE'])
def test_closing_existing_report_row_retains_before_manifest(monkeypatch, asset_type):
    evidence = processed_fixture(monkeypatch)
    pub = evidence['receipt']['publication_payload']
    before, after = deepcopy(pub['before_accounting']), deepcopy(pub['after_accounting'])
    before[0]['quantity_exact'], after[0]['quantity_exact'] = '5', '0'
    selected = deepcopy(evidence['preview']['payload']['selection_rows'])
    selected[0]['asset_type'] = asset_type
    original = deepcopy((before, after, selected))
    assert reader().report_row_manifest(before, after, selected) == qt_digest_v1({
        'component_keys': [before[0]['key']]})
    assert (before, after, selected) == original


def test_closure_keeps_same_symbol_owners_and_unchanged_hidden_zero(monkeypatch):
    evidence = processed_fixture(monkeypatch)
    row = evidence['receipt']['publication_payload']['before_accounting'][0]
    before, after, selected = [], [], []
    for owner, previous, chosen in [('alpha', '5', '0'), ('beta', '2', '2'), ('hidden', '0', '0')]:
        old = {**row, 'key': {**row['key'], 'strategy_name': owner}, 'quantity_exact': previous}
        before.append(old)
        after.append({**old, 'quantity_exact': chosen})
        selected.append({**evidence['preview']['payload']['selection_rows'][0],
            'key': {**old['key'], 'portfolio_type': 'qt_proposal'}, 'quantity_exact': chosen})
    expected = qt_digest_v1({'component_keys': [row['key'] for row in before[:2]]})
    assert reader().report_row_manifest(before, after, selected) == expected
    after[-1]['quantity_exact'] = '1'
    assert reader().report_row_manifest(before, after, selected) == qt_digest_v1({'component_keys': [row['key'] for row in before]})


def test_exact_closed_existing_row_allows_full_current_report_proof(monkeypatch):
    evidence = processed_fixture(monkeypatch)
    p, d, r, o, output = (evidence[name] for name in ['preview', 'decision', 'receipt', 'observation', 'result'])
    pub, audit = r['publication_payload'], evidence['audits'][0]
    p['payload']['selection_rows'][0]['quantity_exact'] = '0'
    selected = qt_book_digest_v1(p['payload']['selection_rows'], source_portfolio_type='qt_proposal')
    p['selected_book_digest'] = p['payload']['selected_book_digest'] = selected
    for stage in ['selected_risk', 'selected_costs']:
        p['payload']['evaluation'][stage]['evaluated_book_digest'] = selected
    cost = p['payload']['evaluation']['selected_costs']['by_component'][0]
    cost['prior_quantity_exact'], cost['selected_quantity_exact'] = '1', '0'
    p['payload_digest'] = p['payload']['payload_digest'] = qt_digest_v1({
        key: value for key, value in p['payload'].items() if key != 'payload_digest'})
    d['selected_book_digest'] = d['payload']['selected_book_digest'] = selected
    d['payload']['preview_payload_digest'] = p['payload_digest']
    r['published_book_digest'] = pub['selected_book_digest'] = pub['published_book_digest'] = selected
    pub['preview_payload_digest'] = p['payload_digest']
    pub['after_accounting'][0]['quantity_exact'] = '0'
    o['payload']['fills'][0]['selected_quantity_exact'] = '0'
    o['content_digest'] = pub['observation_digest'] = sha256(canonical_qt_input_bytes(o['payload'])).hexdigest()
    output['payload']['selected_book_digest'] = selected
    output['content_digest'] = pub['results_digest'] = sha256(canonical_qt_input_bytes(output['payload'])).hexdigest()
    audit['after_state']['quantity_exact'] = '0'
    for name in ['preview_payload_digest', 'selected_book_digest', 'published_book_digest', 'observation_digest']:
        audit['risk_check_result'][name] = pub[name]
    current = evidence['current_facts']
    current['saved_rows'][0]['quantity_exact'] = '0'
    current['audit_refs'][-1]['after_digest'] = source_hash(audit['after_state'])
    before = deepcopy(evidence)
    assert reader().processed_report_blocked_reasons(evidence) == ()
    assert evidence == before


@pytest.mark.parametrize('change', ['missing', 'disabled', 'producer', 'version'])
def test_current_execution_policy_authority_remains_required(monkeypatch, change):
    evidence = processed_fixture(monkeypatch)
    if change == 'missing': evidence['execution_policy'] = None
    elif change == 'disabled': evidence['execution_policy']['enabled'] = False
    else: evidence['execution_policy']['producer_id' if change == 'producer' else 'policy_version'] = 'changed'
    assert reader().processed_report_blocked_reasons(evidence) == ('report_snapshot_stale',)


def test_durable_observation_expiry_does_not_expire_proven_execution(monkeypatch):
    evidence = processed_fixture(monkeypatch)
    evidence['observation']['valid_until'] = '2026-09-25T12:00:00Z'
    assert reader().processed_report_blocked_reasons(evidence) == ()


def test_historical_chain_proof_is_separate_from_current_source_authority(monkeypatch):
    from algolens.infrastructure.portfolio.qt_publication_proof import validate_qt_publication_chain
    evidence = processed_fixture(monkeypatch)
    evidence['current_facts']['source_rows'][0]['quantity_exact'] = '999'
    evidence['execution_policy'] = None
    proof = validate_qt_publication_chain(evidence)
    assert set(proof) == {'before', 'after', 'audit_additions', 'payload', 'original'}
    assert len(proof['audit_additions']) == 1
    assert reader().processed_report_blocked_reasons(evidence) == ('report_snapshot_stale',)
