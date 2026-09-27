"""Immutable original-processing closure for one historical predecessor.

This verifies recorded history only. It neither replays current authority nor
walks earlier ledgers, grants action permission, or accepts a processed flag.
SQL supplies exactly the actual rows named by PROCESSING_CONTEXT_FIELDS.
"""
from datetime import datetime, timezone
from decimal import Decimal, localcontext
from hashlib import sha256
from uuid import UUID

from algolens.domain.portfolio.qt_canonical import qt_digest_v1, qt_book_digest_v1
from algolens.domain.portfolio.qt_workflow_errors import QtWorkflowError
from algolens.domain.portfolio.qt_workflow_models import QtKey, QtPreviewResponse
from algolens.domain.shared.fixed_decimal8 import parse_fixed_decimal8
from algolens.infrastructure.portfolio.qt_evaluation_inputs import canonical_qt_input_bytes
from algolens.infrastructure.portfolio.qt_read_set import canonical_internal_snapshot_bytes

PROCESSING_CONTEXT_FIELDS = frozenset({
    'decision', 'preview', 'receipt', 'observation', 'result', 'model_publication'})
ACCOUNTING_FIELDS = frozenset({'key', 'quantity_exact', 'average_price_exact',
    'daily_realized_pnl_exact', 'daily_unrealized_pnl_exact', 'last_update'})
PUBLICATION_FIELDS = frozenset({'schema_version', 'decision_id', 'attempt_id', 'observation_id',
    'book_id', 'source_day', 'model_publication_id', 'preview_payload_digest', 'read_set_digest',
    'selected_book_digest', 'published_book_digest', 'observation_digest', 'results_digest',
    'before_accounting', 'after_accounting', 'report_scope'})
FILL_FIELDS = frozenset({'key', 'observation_kind', 'selected_quantity_exact', 'average_price_exact',
    'actual_cash_cost_exact', 'currency', 'execution_id', 'accounting_source_id',
    'daily_unrealized_pnl_exact', 'daily_realized_pnl_exact', 'last_update'})
MODEL_REFERENCE_FIELDS = frozenset({'publication_id', 'strategy_id', 'publication_version',
    'seed_digest', 'proposal_manifest_digest', 'producer_version'})


def _need(value):
    if not value:
        raise ValueError('unproven_original_processing')


def _digest(value):
    return sha256(canonical_qt_input_bytes(value)).hexdigest()


def _time(value):
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace('Z', '+00:00'))
    _need(parsed.tzinfo is not None)
    return parsed.astimezone(timezone.utc)


def _uuid(value):
    wire = str(value)
    _need(str(UUID(wire)) == wire)
    return wire


def _exact(value):
    _need(type(value) is str and parse_fixed_decimal8(value) is not None)
    return Decimal(value)


def _archived_bindings(snapshot, publication, decision, preview, book, day):
    """Bind only facts captured for this original immutable confirmation."""
    from algolens.infrastructure.portfolio.qt_empty_owner_sql import OwnerPublication, owner_publication_reference
    if type(publication) is OwnerPublication:
        document = publication.document
        _need((document['book_id'], document['source_day'], document['publication_id']) ==
            (book, day, str(decision['model_publication_id'])))
        matching = [row for row in snapshot['publication_refs']
            if row['publication_id'] == document['publication_id']]
        _need(matching == [owner_publication_reference(publication)])
        expected = [{name: row[name] for name in
            ('key', 'quantity_exact', 'average_price_exact', 'position_revision')}
            for row in document['proposal_components']]
        _need(snapshot['system_rows'] == [] and snapshot['source_rows'] == expected)
        _archived_authorizations(snapshot, publication, decision, preview)
        return
    matching = [row for row in snapshot['publication_refs']
                if row['publication_id'] == str(publication['publication_id'])]
    _need(len(matching) == 1 and matching[0] == {
        field: str(publication[field]) if field == 'publication_id' else publication[field]
        for field in MODEL_REFERENCE_FIELDS})
    proposals = publication['proposal_components']
    _need(type(proposals) is list and bool(proposals) and sha256(canonical_internal_snapshot_bytes(
        'qt-proposal-manifest/v1', {'proposal_rows': proposals})).hexdigest() == publication['proposal_manifest_digest'])
    seed = publication['system_components']
    _need(type(seed) is list and 0 < len(seed) <= 4096)
    rows = {}
    for row in seed:
        _need(type(row) is dict and set(row) == {'key', 'quantity_exact', 'average_price_exact'})
        key = QtKey.from_wire(row['key'])
        _need(key.portfolio_id == book and key.date == day and key.portfolio_type == 'system'
              and key.strategy_id == publication['strategy_id'] and key not in rows)
        _exact(row['quantity_exact'])
        _need(_exact(row['average_price_exact']) >= 0)
        rows[key] = row
    ordered = [rows[key] for key in sorted(rows)]
    captured = [row for row in snapshot['system_rows']
                if row['key']['strategy_id'] == publication['strategy_id']]
    _need(ordered == captured and publication['seed_digest'] == qt_digest_v1({'seed_rows': ordered}))
    _archived_authorizations(snapshot, publication, decision, preview)


def _archived_authorizations(snapshot, publication, decision, preview):
    provenance = snapshot['provenance']
    _need(provenance['status'] == 'ready' and provenance['seed_digest'] == publication['seed_digest']
          and provenance['source_digest'] == preview['source_digest']
          and provenance['chain_digest'] == preview['provenance_digest'])
    evaluator = snapshot['evaluator']
    _need(evaluator['status'] == 'available' and evaluator['build'] == preview['evaluator_build']
          and evaluator['policy_version'] == preview['policy_version'])
    capability = snapshot['capability']
    _need(capability['status'] == 'present' and capability['enabled'] is True
          and capability['version'] == decision['workflow_capability_version'])
    grant = [row for row in snapshot['grants']
             if row['user_id'] == str(decision['created_by']) and row['capability'] == 'qt_submit']
    _need(len(grant) == 1 and grant[0]['active'] is True
          and grant[0]['version'] == decision['submitter_grant_version'])


def _fill_results(observation, after, source, executions, selection_rows):
    """Close the recorded fills and exact currency aggregates without ledger recursion."""
    totals = {}
    _need(type(source['previous_positions']) is list and len(source['previous_positions']) <= 4096
          and type(executions) is list and len(executions) <= 4096)
    previous = {}
    for row in source['previous_positions']:
        _need(type(row) is dict and set(row) == {'key', 'quantity_exact', 'average_price_exact'})
        key = QtKey.from_wire(row['key'])
        _need(key.portfolio_id == observation['book_id'] and key.date == source['previous_day']
              and key.date < observation['source_day'] and key.portfolio_type == 'qt')
        current = QtKey.from_wire({**row['key'], 'date': observation['source_day']})
        _need(current not in previous)
        _exact(row['quantity_exact'])
        _need(_exact(row['average_price_exact']) > 0)
        previous[current] = row
    executed_keys = {QtKey.from_wire(row['key']) for row in executions}
    selected = {QtKey.from_wire({**row['key'], 'portfolio_type': 'qt'}): row for row in selection_rows}
    with localcontext() as arithmetic:
        arithmetic.prec = 80
        for fill in observation['fills']:
            _need(type(fill) is dict and set(fill) == FILL_FIELDS)
            key = QtKey.from_wire(fill['key'])
            _need(key in after and fill['observation_kind'] in {'executed', 'carried'})
            for field in ('accounting_source_id', 'currency'):
                _need(type(fill[field]) is str and bool(fill[field].strip()))
            cost = _exact(fill['actual_cash_cost_exact'])
            _need(cost >= 0)
            if fill['observation_kind'] == 'carried':
                _need(fill['execution_id'] is None and cost == 0 and key in previous
                      and key not in executed_keys and selected[key]['asset_type'] == 'FUTURE'
                      and fill['selected_quantity_exact'] == previous[key]['quantity_exact'] == selected[key]['quantity_exact']
                      and fill['average_price_exact'] == previous[key]['average_price_exact'] == selected[key]['average_price_exact'])
            else:
                _need(type(fill['execution_id']) is str and bool(fill['execution_id'].strip()))
            values = totals.setdefault(fill['currency'], [Decimal(0), Decimal(0), Decimal(0)])
            for index, value in enumerate((cost, _exact(fill['daily_unrealized_pnl_exact']),
                                           _exact(fill['daily_realized_pnl_exact']))):
                values[index] += value
    reported = observation['results']
    _need(type(reported) is dict and set(reported) == {'position_count', 'currency_totals'}
          and type(reported['position_count']) is int and reported['position_count'] == len(after))
    _need(type(reported['currency_totals']) is list and len(reported['currency_totals']) <= 4096)
    actual = {}
    for row in reported['currency_totals']:
        _need(type(row) is dict and set(row) == {'currency', 'actual_cash_cost_exact',
            'daily_unrealized_pnl_exact', 'daily_realized_pnl_exact'}
            and type(row['currency']) is str and bool(row['currency'].strip())
            and row['currency'] not in actual)
        actual[row['currency']] = [_exact(row[field]) for field in (
            'actual_cash_cost_exact', 'daily_unrealized_pnl_exact', 'daily_realized_pnl_exact')]
    _need(actual == totals)


def _accounting(rows, book, day):
    _need(type(rows) is list and len(rows) <= 4096)
    result = {}
    for row in rows:
        _need(type(row) is dict and set(row) == ACCOUNTING_FIELDS)
        key = QtKey.from_wire(row['key'])
        _need(key.portfolio_id == book and key.date == day and key.portfolio_type == 'qt' and key not in result)
        for field in ACCOUNTING_FIELDS - {'key', 'last_update'}:
            _need(type(row[field]) is str and parse_fixed_decimal8(row[field]) is not None)
        _need(_exact(row['average_price_exact']) >= 0)
        _time(row['last_update'])
        result[key] = row
    return result


def _prove(accounting):
    context = accounting['processing_context']
    _need(type(context) is dict and set(context) == PROCESSING_CONTEXT_FIELDS)
    decision, preview, receipt, observed, result, publication = (
        context[name] for name in ('decision', 'preview', 'receipt', 'observation', 'result', 'model_publication'))
    inputs, output = accounting['input_row'], accounting['payload']
    book, day, identity = decision['book_id'], str(decision['source_day']), _uuid(decision['decision_id'])
    _need(decision['status'] == 'confirmed_decision' and preview['state'] == 'confirmed_decision'
          and preview['availability'] == 'ready' and receipt['status'] == 'processed')
    for field in ('draft_revision', 'workflow_capability_version', 'submitter_grant_version', 'created_by'):
        _need(type(decision[field]) is int and decision[field] > 0)
    for field in ('preview_id', 'draft_id', 'model_publication_id'):
        _uuid(decision[field])
    for field in ('evaluator_build', 'policy_version'):
        _need(type(preview[field]) is str and bool(preview[field]))
    payload = QtPreviewResponse.from_wire(preview['payload']).to_wire()
    _need(payload['availability'] == 'ready' and payload['confirmable'] is True)
    for field in ('preview_id', 'book_id', 'source_day', 'draft_id', 'draft_revision',
                  'selected_book_digest', 'read_set_digest', 'provenance_digest', 'policy_version'):
        _need(str(decision[field]) == str(preview[field]))
    for field in ('preview_id', 'book_id', 'source_day', 'draft_id', 'draft_revision', 'source_digest',
                  'provenance_digest', 'read_set_digest', 'selected_book_digest', 'payload_digest'):
        _need(str(payload[field]) == str(preview[field]))
    _need(decision['payload'] == {'schema_version': 'qt-desk-decision/v1', 'decision_id': identity,
        'preview_id': str(decision['preview_id']), 'book_id': book, 'source_day': day,
        'preview_payload_digest': preview['payload_digest'],
        'selected_book_digest': decision['selected_book_digest'], 'read_set_digest': decision['read_set_digest']})
    snapshot = preview['read_set_payload']
    _need(snapshot['book_id'] == book and snapshot['source_day'] == day)
    _need(sha256(canonical_internal_snapshot_bytes('qt-read-set/v1', snapshot)).hexdigest() == decision['read_set_digest'])
    _need(str(publication['publication_id']) == str(decision['model_publication_id'])
          and publication['portfolio_id'] == book and str(publication['source_day']) == day)
    _archived_bindings(snapshot, publication, decision, preview, book, day)

    _need(str(accounting['decision_id']) == str(inputs['decision_id']) == identity
          and accounting['portfolio_id'] == book and str(accounting['date']) == day)
    input_id = _uuid(inputs['input_id'])
    _need(str(accounting['input_id']) == str(observed['observation_id']) == input_id)
    _need(accounting['content_digest'] == _digest(output) and output['schema_version'] == 'qt-futures-accounting/v1')
    _need(output['input_digest'] == inputs['content_digest'] == _digest(inputs['payload']))
    for field, expected in (('decision_id', identity), ('book_id', book), ('source_day', day)):
        _need(inputs['payload'][field] == expected)
    observation = observed['payload']
    _need(type(observation) is dict and set(observation) == {
        'schema_version', 'decision_id', 'book_id', 'source_day', 'accounting_input_id', 'fills', 'results'})
    _need(observation['schema_version'] == 'qt-execution/v2' and observation['accounting_input_id'] == input_id
          and output['observation'] == observation and str(observed['decision_id']) == identity)
    for field, expected in (('decision_id', identity), ('book_id', book), ('source_day', day)):
        _need(observation[field] == expected)
    for field in ('producer_id', 'policy_version', 'source_version'):
        _need(type(inputs[field]) is str and bool(inputs[field]) and inputs[field] == observed[field])
    _need(_time(inputs['as_of']) == _time(observed['as_of'])
          and _time(inputs['valid_until']) == _time(observed['valid_until']))
    _need(_time(observed['as_of']) <= _time(receipt['processed_at']) <= _time(observed['valid_until']))

    envelope = receipt['publication_payload']
    _need(type(envelope) is dict and set(envelope) == PUBLICATION_FIELDS
          and envelope['schema_version'] == 'qt-desk-publication/v1' and str(receipt['decision_id']) == identity)
    for field in ('decision_id', 'book_id', 'source_day', 'model_publication_id', 'read_set_digest', 'selected_book_digest'):
        _need(envelope[field] == str(decision[field]))
    _need(envelope['attempt_id'] == _uuid(receipt['attempt_id'])
          and envelope['preview_payload_digest'] == preview['payload_digest']
          and envelope['published_book_digest'] == receipt['published_book_digest'] == decision['selected_book_digest']
          and envelope['observation_id'] == input_id
          and envelope['observation_digest'] == observed['content_digest'] == _digest(observation))
    before = _accounting(envelope['before_accounting'], book, day)
    _need(before == _accounting(snapshot['saved_accounting'], book, day)
          and envelope['before_accounting'] == snapshot['saved_accounting'])
    after = _accounting(envelope['after_accounting'], book, day)
    _need(type(observation['fills']) is list and 0 < len(observation['fills']) <= 4096)
    original_rows = [{**{field: fill[field] for field in ACCOUNTING_FIELDS - {'quantity_exact'}},
                      'quantity_exact': fill['selected_quantity_exact']} for fill in observation['fills']]
    _need(after == _accounting(original_rows, book, day))
    _fill_results(observation, after, inputs['payload'], output['executions'], payload['selection_rows'])
    selected = {QtKey.from_wire({**row['key'], 'portfolio_type': 'qt'}): row['quantity_exact']
                for row in payload['selection_rows']}
    _need(len(selected) == len(payload['selection_rows']) and set(selected) == set(after)
          and all(row['quantity_exact'] == selected[key] for key, row in after.items()))
    _need(qt_book_digest_v1([{'key': key.to_wire(), 'quantity_exact': row['quantity_exact']}
        for key, row in after.items()], source_portfolio_type='qt') == decision['selected_book_digest'])

    _need(str(result['decision_id']) == identity and str(result['attempt_id']) == str(receipt['attempt_id'])
          and str(result['observation_id']) == input_id)
    results = result['payload']
    _need(type(results) is dict and set(results) == {
        'schema_version', 'decision_id', 'observation_id', 'book_id', 'source_day', 'selected_book_digest', 'results'})
    _need(results['schema_version'] == 'qt-desk-result/v1' and results['observation_id'] == input_id)
    for field in ('decision_id', 'book_id', 'source_day', 'selected_book_digest'):
        _need(results[field] == str(decision[field]))
    _need(results['results'] == observation['results'] and
          envelope['results_digest'] == result['content_digest'] == _digest(results))


def verify_original_processing(accounting):
    """Require actual immutable context for this one original processed result."""
    try:
        _prove(accounting)
    except (KeyError, TypeError, ValueError, ArithmeticError, AttributeError, QtWorkflowError) as exc:
        raise ValueError('unproven_original_processing') from exc
