"""Read-only QT presentation and independently proven current report readiness."""
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
import json
from collections.abc import Mapping
from psycopg2 import Error as PostgresError

from algolens.domain.portfolio.qt_canonical import qt_digest_v1, qt_book_digest_v1
from algolens.domain.portfolio.qt_workflow_errors import QtWorkflowError
from algolens.domain.portfolio.qt_workflow_models import QtKey, QtPreviewResponse
from algolens.domain.shared.fixed_decimal8 import parse_fixed_decimal8
from algolens.infrastructure.portfolio.qt_evaluation_inputs import canonical_qt_input_bytes
from algolens.infrastructure.portfolio.qt_read_set import capture_qt_read_set, canonical_internal_snapshot_bytes
from algolens.infrastructure.portfolio.qt_accounting_proof import producer_prior_carries


_ACCOUNTING = {'key', 'quantity_exact', 'average_price_exact', 'daily_unrealized_pnl_exact',
               'daily_realized_pnl_exact', 'last_update'}
_PUBLICATION = {'schema_version', 'decision_id', 'attempt_id', 'observation_id', 'book_id',
                'source_day', 'model_publication_id', 'preview_payload_digest', 'read_set_digest',
                'selected_book_digest', 'published_book_digest', 'observation_digest', 'results_digest',
                'before_accounting', 'after_accounting', 'report_scope'}
_FILL = {'key', 'observation_kind', 'selected_quantity_exact', 'average_price_exact',
         'actual_cash_cost_exact', 'currency', 'execution_id', 'accounting_source_id',
         'daily_unrealized_pnl_exact', 'daily_realized_pnl_exact', 'last_update'}


def _require(value):
    if not value:
        raise ValueError('unproven_publication')


def require_legacy_qt_disabled(cursor, book_id):
    """Call under the canonical book fence, before any legacy write."""
    try:
        cursor.execute('SELECT enabled,version FROM trading.qt_workflow_capabilities WHERE book_id=%s', (book_id,))
        raw = cursor.fetchone()
    except PostgresError:
        raise QtWorkflowError('workflow_unavailable') from None
    if raw is None: raise QtWorkflowError('workflow_unavailable')
    row = raw if isinstance(raw, Mapping) else {'enabled': raw[0], 'version': raw[1]}
    if type(row.get('enabled')) is not bool or type(row.get('version')) is not int or row['version'] <= 0:
        raise QtWorkflowError('workflow_unavailable')
    if row['enabled']: raise QtWorkflowError('preview_required')


def _exact(value):
    _require(type(value) is str and parse_fixed_decimal8(value) is not None)
    return Decimal(value)


def _utc(value):
    _require(type(value) is str and value.endswith('Z'))
    stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    _require(stamp.tzinfo is not None and stamp.utcoffset().total_seconds() == 0)
    return stamp


def _source_hash(value):
    # This is the legacy source/audit JSON spelling, not public QT wire JSON.
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                             ensure_ascii=False, allow_nan=False).encode('utf-8')).hexdigest()


def _accounting(rows, book, day):
    _require(type(rows) is list and len(rows) <= 4096)
    result = {}
    for row in rows:
        _require(type(row) is dict and set(row) == _ACCOUNTING)
        key = QtKey.from_wire(row['key'])
        _require(key.portfolio_id == book and key.date == day and key.portfolio_type == 'qt' and key not in result)
        for name in ['quantity_exact', 'average_price_exact', 'daily_unrealized_pnl_exact', 'daily_realized_pnl_exact']:
            _exact(row[name])
        _require(_exact(row['average_price_exact']) >= 0)
        _utc(row['last_update'])
        result[key] = row
    return result


def _flat(row):
    return {**row['key'], 'quantity_exact': row['quantity_exact'], 'average_price_exact': row['average_price_exact']}


def report_row_manifest(before, after, selection_rows):
    """Mirror the native saved-position row rule; never group owners.

    `after` must cover every key `before` has: a `before` key missing from
    `after` refuses (a saved row the report would silently drop). An
    `after`-only key -- a symbol that never had an earlier position row, for
    example a genuinely new key the desk opened today -- is not a refusal:
    it is treated as `before = 0` for the closed-today/shown-row rule below,
    exactly like a key that already had an explicit zero row. It still goes
    through the same asset-type and whole-FUTURE-quantity checks as every
    other shown row, from its own selection row.
    """
    try:
        _require(bool(after))
        first = QtKey.from_wire(after[0]['key'])
        old = _accounting(before, first.portfolio_id, first.date)
        new = _accounting(after, first.portfolio_id, first.date)
        _require(set(old) <= set(new) and len({key.strategy_id for key in new}) == 1)
        types = {}
        for row in selection_rows:
            key = QtKey.from_wire({**row['key'], 'portfolio_type': 'qt'})
            _require(key not in types and row['asset_type'] in {'EQUITY', 'FUTURE'})
            types[key] = row['asset_type']
        _require(set(types) == set(new))
        display = set()
        keys = []
        for key in sorted(new):
            previous = _exact(old[key]['quantity_exact']) if key in old else Decimal(0)
            current = _exact(new[key]['quantity_exact'])
            if types[key] == 'FUTURE':
                _require(previous == previous.to_integral_value() and current == current.to_integral_value())
            # Shown rows: saved nonzero, or closed today (nonzero before, zero after).
            # An after-only key with current == 0 is absent -> 0: not shown.
            if previous != 0 or current != 0:
                row_identity = (key.strategy_name, key.symbol)
                _require(row_identity not in display)
                display.add(row_identity)
                keys.append(key.to_wire())
        return qt_digest_v1({'component_keys': keys})
    except (ValueError, TypeError, KeyError, ArithmeticError, QtWorkflowError):
        return None


def validate_qt_publication_chain(evidence, *, recompute_client_factory=None, finalization_recompute_client_factory=None):
    """Verify one immutable publication; current source authority is separate.

    Evidence supplies actual decision/preview/receipt/observation/result rows
    and this publication's raw audit records. Historical callers independently
    reconcile later audits; current readers supply every current audit record.
    """
    d, p, r = (evidence[name] for name in ['decision', 'preview', 'receipt'])
    _require(d['status'] == 'confirmed_decision' and r['status'] == 'processed')
    book, day = d['book_id'], str(d['source_day'])
    _require(type(d['created_by']) is int and d['created_by'] > 0)
    payload = QtPreviewResponse.from_wire(p['payload']).to_wire()
    _require(p['state'] == 'confirmed_decision' and p['availability'] == 'ready')
    for name in ['preview_id', 'book_id', 'source_day', 'draft_id', 'draft_revision', 'provenance_digest']:
        _require(str(p[name]) == str(d[name]))
    _require(payload['book_id'] == book and payload['source_day'] == day and payload['preview_id'] == str(d['preview_id']))
    for name in ['payload_digest', 'read_set_digest', 'selected_book_digest']:
        _require(payload[name] == p[name])
    _require(payload['read_set_digest'] == d['read_set_digest'] and payload['selected_book_digest'] == d['selected_book_digest'])
    reference = {'schema_version': 'qt-desk-decision/v1', 'decision_id': str(d['decision_id']),
        'preview_id': str(d['preview_id']), 'book_id': book, 'source_day': day,
        'preview_payload_digest': p['payload_digest'], 'selected_book_digest': d['selected_book_digest'],
        'read_set_digest': d['read_set_digest']}
    _require(d['payload'] == reference and str(r['decision_id']) == str(d['decision_id']))
    pub = r['publication_payload']
    _require(type(pub) is dict and set(pub) == _PUBLICATION and pub['schema_version'] == 'qt-desk-publication/v1')
    for name in ['decision_id', 'book_id', 'source_day', 'model_publication_id', 'read_set_digest', 'selected_book_digest']:
        _require(pub[name] == str(d[name]))
    _require(pub['attempt_id'] == str(r['attempt_id']) and pub['preview_payload_digest'] == p['payload_digest'])
    _require(pub['published_book_digest'] == r['published_book_digest'] == d['selected_book_digest'])
    original = p['read_set_payload']
    _require(original['book_id'] == book and original['source_day'] == day)
    _require(sha256(canonical_internal_snapshot_bytes('qt-read-set/v1', original)).hexdigest() == d['read_set_digest'])
    old, new = _accounting(pub['before_accounting'], book, day), _accounting(pub['after_accounting'], book, day)
    _require(old == _accounting(original['saved_accounting'], book, day))
    selected = {QtKey.from_wire({**row['key'], 'portfolio_type': 'qt'}): row['quantity_exact'] for row in payload['selection_rows']}
    _require(set(selected) == set(new) and all(selected[key] == new[key]['quantity_exact'] for key in new))
    _require(qt_book_digest_v1([{'key': key.to_wire(), 'quantity_exact': row['quantity_exact']} for key, row in new.items()],
                              source_portfolio_type='qt') == pub['published_book_digest'])
    o, result = evidence['observation'], evidence['result']
    _require(_utc(o['as_of']) <= _utc(r['processed_at']) <= _utc(o['valid_until']))
    observed = o['payload']
    _require(str(o['observation_id']) == pub['observation_id'] and str(o['decision_id']) == str(d['decision_id']))
    _require(o['content_digest'] == pub['observation_digest'] == sha256(canonical_qt_input_bytes(observed)).hexdigest())
    _require(type(observed) is dict)
    producer = observed.get('schema_version') == 'qt-execution/v2'
    fields = {'schema_version', 'decision_id', 'book_id', 'source_day', 'fills', 'results'}
    _require(set(observed) == fields | ({'accounting_input_id'} if producer else set()))
    _require(producer or observed['schema_version'] == 'qt-execution/v1')
    if producer:
        _require(observed['accounting_input_id'] == str(o['observation_id']) and evidence.get('accounting') is not None)
    for name in ['decision_id', 'book_id', 'source_day']:
        _require(observed[name] == str(d[name]))
    producer_carries = producer_prior_carries(evidence, recompute_client_factory=recompute_client_factory,
        finalization_recompute_client_factory=finalization_recompute_client_factory)
    empty_owner = None
    financial = evidence.get('accounting')
    if (producer and isinstance(financial, dict) and
            financial['payload'].get('schema_version') == 'qt-equity-accounting-empty-owner/v2'):
        # producer_prior_carries above has completed source/SQL/retained-native
        # mathematical proof. The exact archived document supplies owner scope;
        # an empty selection or a caller flag cannot select this branch.
        from algolens.infrastructure.portfolio.qt_empty_owner_sql import OwnerPublication
        model = financial['equity_sources']['model_publication']
        _require(type(model) is OwnerPublication)
        empty_owner = model.document
        _require(not old and not new and not selected and not observed['fills'] and
            all(original[name] == [] for name in ('system_rows','source_rows','saved_rows','saved_accounting')) and
            all(empty_owner[name] == [] for name in ('system_components','proposal_components','qt_components')))
        _require(pub['report_scope'] == dict(portfolio_id=book, strategy_id=empty_owner['strategy_id'],
            strategy_names=empty_owner['configured_owner_names'], portfolio_type='qt', date=day))
    fills, totals = {}, {}
    if empty_owner is not None:
        # Compare to the actual produced aggregate, already proved from source
        # and native output. Do not invent currency/financial defaults here.
        produced = financial['payload']['observation']['results']
        _require(observed['results'] == produced)
        for row in produced['currency_totals']:
            totals[row['currency']] = [_exact(row[name]) for name in
                ('actual_cash_cost_exact','daily_unrealized_pnl_exact','daily_realized_pnl_exact')]
    for fill in observed['fills']:
        _require(type(fill) is dict and set(fill) == _FILL)
        key = QtKey.from_wire(fill['key'])
        _require(key in new and key not in fills and fill['observation_kind'] in {'executed', 'carried'})
        accounting = {'key': fill['key'], 'quantity_exact': fill['selected_quantity_exact'],
                      **{name: fill[name] for name in _ACCOUNTING - {'key', 'quantity_exact'}}}
        _require(accounting == new[key] and type(fill['accounting_source_id']) is str and fill['accounting_source_id'].strip())
        cost = _exact(fill['actual_cash_cost_exact'])
        _require(cost >= 0 and type(fill['currency']) is str and fill['currency'].strip())
        if fill['observation_kind'] == 'carried':
            unchanged = (key in old and old[key]['quantity_exact'] == accounting['quantity_exact'] and
                         old[key]['average_price_exact'] == accounting['average_price_exact'])
            _require(fill['execution_id'] is None and cost == 0 and
                     (unchanged or producer_carries.get(key) == fill))
        else:
            _require(type(fill['execution_id']) is str and fill['execution_id'].strip())
        values = totals.setdefault(fill['currency'], [Decimal(0), Decimal(0), Decimal(0)])
        for index, value in enumerate([cost, _exact(fill['daily_unrealized_pnl_exact']), _exact(fill['daily_realized_pnl_exact'])]):
            values[index] += value
        fills[key] = accounting
    _require(fills == new)
    reported = observed['results']
    _require(set(reported) == {'position_count', 'currency_totals'} and type(reported['position_count']) is int and reported['position_count'] == len(new))
    reported_totals = {}
    for row in reported['currency_totals']:
        _require(set(row) == {'currency', 'actual_cash_cost_exact', 'daily_unrealized_pnl_exact', 'daily_realized_pnl_exact'} and row['currency'] not in reported_totals)
        reported_totals[row['currency']] = [_exact(row[name]) for name in ['actual_cash_cost_exact', 'daily_unrealized_pnl_exact', 'daily_realized_pnl_exact']]
    _require(reported_totals == totals)
    output = result['payload']
    _require(str(result['decision_id']) == str(d['decision_id']) and str(result['attempt_id']) == pub['attempt_id'] and str(result['observation_id']) == pub['observation_id'])
    _require(result['content_digest'] == pub['results_digest'] == sha256(canonical_qt_input_bytes(output)).hexdigest())
    _require(set(output) == {'schema_version', 'decision_id', 'observation_id', 'book_id', 'source_day', 'selected_book_digest', 'results'} and output['schema_version'] == 'qt-desk-result/v1')
    for name in ['decision_id', 'book_id', 'source_day', 'selected_book_digest']:
        _require(output[name] == str(d[name]))
    _require(output['observation_id'] == pub['observation_id'] and output['results'] == reported)
    audit_reference = {'schema_version': 'qt-desk-audit/v1',
                       **{name: reference[name] for name in ['decision_id', 'preview_id',
                          'preview_payload_digest', 'read_set_digest', 'selected_book_digest']},
                       'attempt_id': pub['attempt_id'], 'published_book_digest': pub['published_book_digest'],
                       'observation_digest': pub['observation_digest']}
    prior_ids = {row['id'] for row in original['audit_refs']}
    additions, covered = {}, set()
    for audit in evidence['audits']:
        if audit['id'] in prior_ids:
            continue
        _require(type(audit['id']) is int and audit['id'] > 0 and type(audit['user_id']) is int and
                 audit['id'] not in additions and audit['risk_check_result'] == audit_reference and
                 audit['source_app'] == 'algolens' and audit['user_id'] == d['created_by'])
        matches = [key for key, row in new.items() if _flat(row) == audit['after_state']]
        _require(len(matches) == 1 and matches[0] not in covered)
        key = matches[0]
        _require(audit['before_state'] == (_flat(old[key]) if key in old else None) and
                 audit['portfolio_id'] == book and audit['strategy_id'] == key.strategy_id and audit['symbol'] == key.symbol)
        covered.add(key)
        additions[audit['id']] = {'id': audit['id'], 'user_id': str(audit['user_id']), 'source_app': audit['source_app'],
            'strategy_id': audit['strategy_id'], 'symbol': audit['symbol'],
            'before_digest': _source_hash(audit['before_state']), 'after_digest': _source_hash(audit['after_state'])}
    _require(covered == set(new))
    proof = {'before': old, 'after': new, 'audit_additions': additions, 'payload': payload, 'original': original}
    if empty_owner is not None:
        proof['empty_owner'] = empty_owner
    return proof
