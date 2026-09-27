"""Staged exact QT continuity, independent of an empty MODEL recommendation.

The SQL reader supplies complete actual rows. Matching hashes or caller flags
cannot grant human ownership. Equity receipt mathematics remains delegated to
the retained-bundle producer proof through the existing receipt validator.
"""
from datetime import date,datetime,timezone

from algolens.domain.portfolio.qt_workflow_models import QtKey
from algolens.domain.portfolio.qt_workflow_errors import QtWorkflowError
from algolens.infrastructure.portfolio.qt_provenance import _verified_qt_overlay, _target_key
from algolens.infrastructure.portfolio.qt_read_set import _rows, _accounting_row, _array
from algolens.infrastructure.portfolio.qt_receipt_provenance import verified_receipt_chain, audit_is_other_qt_day
from algolens.infrastructure.portfolio.qt_empty_owner_protocol import validate_empty_model_owner_document


def _need(condition):
    if not condition: raise ValueError('empty_owner_qt_continuity_unavailable')


def _positions(rows):
    normalized = _rows(rows)
    return {QtKey.from_wire(row['key']): row for row in normalized}


def _project(rows):
    return _positions([{name: row[name] for name in ('key', 'quantity_exact', 'average_price_exact')}
        for row in rows])


def _legacy(document, saved, audits, archive):
    book, day = document['book_id'], date.fromisoformat(document['source_day'])
    keys = {_target_key(key) for key in set(archive) | set(saved)}
    overlay, traces, events = _verified_qt_overlay(book, day, keys, list(saved.values()), audits)
    changed = {key for key in set(saved) | set(archive) if saved.get(key) != archive.get(key)}
    traced = {trace.source_key for trace in traces}
    _need(changed <= traced and set(saved) == set(archive))
    # An audited prior QT state is not an invented MODEL origin. For changes
    # from this publication snapshot, the first exact state must join it.
    for trace in traces:
        event = next(row for row in events if row['id'] == trace.audit_ids[0])
        _need(event['before'] == archive[trace.source_key])
    return overlay, traces, events

def _verify(document, saved_rows, saved_accounting, audits,
        processed_publications, *, recompute_client_factory=None,
        finalization_recompute_client_factory=None,archived_at=None):
    doc = validate_empty_model_owner_document(document)
    saved, archive = _positions(saved_rows), _positions(doc['qt_components'])
    for key in saved:
        _need(key.portfolio_id == doc['book_id'] and key.strategy_id == doc['strategy_id']
            and key.strategy_name in doc['configured_owner_names'] and key.date == doc['source_day']
            and key.portfolio_type == 'qt')
    accounts = _array(saved_accounting, _accounting_row,
        identity=lambda row: QtKey.from_wire(row['key']))
    _need(_project(accounts) == saved)
    _need(type(audits) is list and len(audits) <= 4096
        and type(processed_publications) is list and len(processed_publications) <= 4096)
    # The v2 empty owner is specifically equity. Old consumer-only execution
    # observations cannot stand in for its independently proved producer math.
    for evidence in processed_publications:
        _need(evidence['observation']['payload']['schema_version'] == 'qt-execution/v2')
        financial = evidence['accounting']
        _need(type(financial) is dict and (financial['input_row']['payload']['schema_version'],
            financial['payload']['schema_version']) in {('qt-equity-accounting-input/v1','qt-equity-accounting/v1'),
                ('qt-equity-accounting-input-empty-owner/v2','qt-equity-accounting-empty-owner/v2')})
    receipt = verified_receipt_chain(doc['book_id'], date.fromisoformat(doc['source_day']),
        processed_publications, audits, accounts, recompute_client_factory=recompute_client_factory,
        finalization_recompute_client_factory=finalization_recompute_client_factory)
    if receipt is None:
        overlay, traces, events = _legacy(doc, saved, audits, archive)
        return dict(rows=list(saved.values()), accounting=accounts, overlay=overlay,
            traces=traces, audit_events=events, receipt_links=(), receipt_decisions=())
    before = _project(receipt['before'].values())
    # Only exact legacy events before the first independently proved receipt
    # can bridge an existing archive key. A new key requires that receipt.
    legacy = [row for row in audits if row['id'] not in receipt['audit_ids']]
    checkpoint=False
    if archived_at is not None and before!=archive:
        _need(type(archived_at) is datetime and archived_at.tzinfo is not None
            and archived_at.utcoffset()==timezone.utc.utcoffset(archived_at))
        for point in receipt['checkpoints']:
            text=point['processed_at']
            _need(type(text) is str and text.endswith('Z'))
            stamp=datetime.fromisoformat(text.replace('Z','+00:00'))
            _need(stamp.isoformat().replace('+00:00','Z')==text)
            if stamp<=archived_at and _project(point['after'].values())==archive:
                checkpoint=True
    if checkpoint:
        # This complete accounting checkpoint was independently proved by the
        # receipt validator, whose subsequent chain ends at actual physical QT.
        # Equality to MODEL/owner hashes alone never enters this branch.
        overlay,traces,events=(),(),()
    else:
        overlay, traces, events = _legacy(doc, before, legacy, archive)
    from algolens.infrastructure.portfolio.qt_provenance import QtExactPosition, QtVerifiedQtEdit
    human = set(receipt['choices'])
    overlay = {row.key: row for row in overlay}
    traces = [trace for trace in traces if trace.source_key not in human]
    for key in sorted(human):
        current = saved[key]
        overlay[_target_key(key)] = QtExactPosition(_target_key(key), current['quantity_exact'], current['average_price_exact'])
        identities = tuple(row['id'] for row in sorted(audits, key=lambda item: item['id'])
            if row['id'] in receipt['audit_ids'] and type(row.get('after_state')) is dict
            and all(row['after_state'].get(name) == value for name, value in key.to_wire().items()))
        _need(bool(identities))
        traces.append(QtVerifiedQtEdit(key, _target_key(key), identities, origin='verified_qt_decision'))
    return dict(rows=list(saved.values()), accounting=accounts,
        overlay=tuple(overlay[key] for key in sorted(overlay)), traces=tuple(traces), audit_events=events,
        receipt_links=receipt['links'], receipt_decisions=receipt['decisions'])


def verify_owner_qt_continuity(document, saved_rows, saved_accounting, audits,
        processed_publications, *, recompute_client_factory=None,
        finalization_recompute_client_factory=None,archived_at=None):
    try:
        return _verify(document, saved_rows, saved_accounting, audits, processed_publications,
            recompute_client_factory=recompute_client_factory,
            finalization_recompute_client_factory=finalization_recompute_client_factory,archived_at=archived_at)
    except (KeyError, TypeError, ValueError, AttributeError, ArithmeticError, QtWorkflowError):
        raise ValueError('empty_owner_qt_continuity_unavailable') from None
