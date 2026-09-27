"""Current report proof against actual receipt and recaptured source inventory."""
from copy import deepcopy
from algolens.domain.portfolio.qt_workflow_errors import QtWorkflowError
from algolens.domain.portfolio.qt_canonical import qt_digest_v1
from algolens.infrastructure.portfolio.qt_publication_proof import (validate_qt_publication_chain, report_row_manifest, _require, _accounting)
from algolens.infrastructure.portfolio.qt_read_set import capture_qt_read_set
from algolens.infrastructure.portfolio.qt_accounting_proof import current_accounting_after

def _prove_processed(evidence, *, recompute_client_factory=None, finalization_recompute_client_factory=None):
    d, r, o = (evidence[name] for name in ['decision', 'receipt', 'observation'])
    _require(evidence['latest_decision_id'] == d['decision_id'])
    policy = evidence['execution_policy']
    _require(policy is not None and policy['enabled'] is True and policy['producer_id'] == o['producer_id'] and policy['policy_version'] == o['policy_version'])
    if o['payload'].get('schema_version') == 'qt-execution/v2':
        accounting = evidence.get('accounting')
        _require(type(accounting) is dict and type(accounting.get('financial_rows')) is dict)
        profile = accounting['payload'].get('schema_version')
        _require(profile in {'qt-futures-accounting/v1', 'qt-equity-accounting/v1','qt-equity-accounting-empty-owner/v2'})
        tables = {'executions', 'live_results', 'equity_curve'}
        if profile in {'qt-equity-accounting/v1','qt-equity-accounting-empty-owner/v2'}:
            tables.add('positions')
        _require(set(accounting['financial_rows']) == tables and
                 all(type(rows) is list for rows in accounting['financial_rows'].values()))
    proof = validate_qt_publication_chain(evidence, recompute_client_factory=recompute_client_factory,
        finalization_recompute_client_factory=finalization_recompute_client_factory)
    old, new, additions, payload, original = (proof[name] for name in ['before', 'after', 'audit_additions', 'payload', 'original'])
    pub, book, day = r['publication_payload'], d['book_id'], str(d['source_day'])
    current = deepcopy(evidence['current_facts'])
    _require(_accounting(current['saved_accounting'], book, day) == current_accounting_after(evidence,new,
        recompute_client_factory=recompute_client_factory,finalization_recompute_client_factory=finalization_recompute_client_factory))
    from algolens.domain.portfolio.qt_workflow_models import QtKey
    actual_saved = {QtKey.from_wire(row['key']): row for row in current['saved_rows']}
    expected_saved = {key: {name: row[name] for name in ['key', 'quantity_exact', 'average_price_exact']} for key, row in new.items()}
    _require(actual_saved == expected_saved and len(actual_saved) == len(current['saved_rows']))
    prior_ids = {row['id'] for row in original['audit_refs']}
    refs = {row['id']: row for row in current['audit_refs']}
    _require(len(refs) == len(current['audit_refs']) and set(refs) == prior_ids | set(additions) and all(refs[identity] == row for identity, row in additions.items()))
    # Only these fully proven receipt effects are normalized back. Current
    # proposal tokens/system/publication/registry/input authority remain actual.
    current['audit_refs'] = [row for row in current['audit_refs'] if row['id'] not in additions]
    current['saved_rows'] = deepcopy(original['saved_rows'])
    current['saved_accounting'] = deepcopy(original['saved_accounting'])
    current['provenance'] = deepcopy(original['provenance'])
    current['captured_at'] = evidence['checked_at']
    capture = capture_qt_read_set(current)
    _require(capture.available and capture.digest == d['read_set_digest'])
    owner = proof.get('empty_owner')
    if owner is not None:
        _require(accounting['payload']['schema_version']=='qt-equity-accounting-empty-owner/v2'
                 and not old and not new and payload['selection_rows']==[])
        manifest = qt_digest_v1({'component_keys':[]})
        scope = {'portfolio_id': book, 'strategy_id': owner['strategy_id'],
                 'strategy_names': owner['configured_owner_names'], 'portfolio_type':'qt','date':day}
    else:
        manifest = report_row_manifest(pub['before_accounting'], pub['after_accounting'], payload['selection_rows'])
        first = next(iter(old))
        scope = {'portfolio_id': book, 'strategy_id': first.strategy_id,
                 'strategy_names': sorted({key.strategy_name for key in old}), 'portfolio_type': 'qt', 'date': day}
    _require(manifest is not None and r['report_eligibility_status'] == 'eligible' and not r['report_reason_codes'] and manifest == r['row_manifest_digest'])
    _require(pub['report_scope'] == scope)


def processed_report_blocked_reasons(evidence, *, recompute_client_factory=None, finalization_recompute_client_factory=None):
    try:
        _prove_processed(evidence, recompute_client_factory=recompute_client_factory,
            finalization_recompute_client_factory=finalization_recompute_client_factory)
        return ()
    except (ValueError, TypeError, KeyError, ArithmeticError, QtWorkflowError, StopIteration):
        return ('report_snapshot_stale',)
