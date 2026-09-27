"""Staged closed reference union, preserving unchanged v1 canonical bytes.

The syntactic encoder proves no SQL authority. Binding is a separate operation
requiring the server-owned current publication proof. Native v2 admission and
live composition remain a coordinated 023-boundary change.
"""
from copy import deepcopy
import json
from uuid import UUID

from algolens.infrastructure.portfolio.qt_read_set import (
    _array, _digest, _nonempty, _positive, _publication, _read_set, _shape, _int,
    canonical_internal_snapshot_bytes,
)
from algolens.infrastructure.portfolio.qt_empty_owner_sql import OwnerPublication, owner_publication_reference, ENGINE

REFERENCE = 'qt-empty-model-owner-reference/v2'


def _revision(value):
    value = _int(value)
    if value < 0: raise ValueError('invalid_owner_registry_revision')
    return value


def _owner_names(value):
    names = _array(value, _nonempty, identity=lambda name: name)
    if not names or value != names: raise ValueError('invalid_configured_owner_names')
    return names


def _owner_uuid(value):
    if type(value) is not str or str(UUID(value)) != value or UUID(value).int == 0:
        raise ValueError('invalid_owner_publication_id')
    return value


def _reference(value):
    if type(value) is not dict: raise ValueError('invalid_publication_reference')
    if 'schema_version' not in value: return _publication(value)
    def schema(item):
        if item != REFERENCE: raise ValueError('unknown_owner_reference_schema')
        return item
    def engine(item):
        if item != ENGINE: raise ValueError('foreign_owner_reference_engine')
        return item
    return _shape(value, dict(schema_version=schema, publication_id=_owner_uuid,
        strategy_id=engine, publication_version=_positive, seed_digest=_digest,
        proposal_manifest_digest=_digest, producer_version=_nonempty,
        owner_document_digest=_digest, configuration_digest=_digest, qt_digest=_digest,
        registry_id=_nonempty, registry_revision=_revision, configured_owner_names=_owner_names))


def canonical_owner_read_set_bytes(payload):
    if type(payload) is not dict: raise ValueError('invalid_owner_read_set')
    refs = payload.get('publication_refs')
    if type(refs) is not list: raise ValueError('invalid_publication_reference_set')
    if all(type(item) is dict and 'schema_version' not in item for item in refs):
        return canonical_internal_snapshot_bytes('qt-read-set/v1', payload)
    # Reuse every existing closed field validator without weakening the v1
    # reference parser. Restore the separately validated union before hashing.
    source = deepcopy(payload); source['publication_refs'] = []
    normalized = _read_set(source)
    normalized['publication_refs'] = _array(refs, _reference,
        identity=lambda item: item['publication_id'])
    raw = json.dumps(normalized, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode('utf-8', 'strict')
    if len(raw) > 1048576: raise ValueError('oversize_owner_read_set')
    return raw


def bind_owner_read_set(payload, publication):
    if type(publication) is not OwnerPublication or not publication.current_inventory_verified:
        raise ValueError('current_owner_publication_proof_missing')
    doc = publication.document
    current = publication.current_qt
    if type(current) is not dict: raise ValueError('current_owner_qt_proof_missing')
    if (payload.get('book_id'), payload.get('source_day')) != (doc['book_id'], doc['source_day']):
        raise ValueError('foreign_owner_read_set')
    # Current proof has verified these complete physical arrays. This encoder
    # cannot hide an extra engine, symbol, row, or changed quantity/basis.
    expected = [{name: deepcopy(row[name]) for name in
        ('key', 'quantity_exact', 'average_price_exact', 'position_revision')}
        for row in doc['proposal_components']]
    if (payload.get('source_rows') != expected or payload.get('system_rows') != []
            or payload.get('saved_rows') != current['rows']):
        raise ValueError('owner_physical_inventory_mismatch')
    accounting = payload.get('saved_accounting')
    if type(accounting) is not list or [{name: row.get(name) for name in
            ('key', 'quantity_exact', 'average_price_exact')} for row in accounting] != current['rows']:
        raise ValueError('owner_accounting_inventory_mismatch')
    if accounting != current['accounting']:
        raise ValueError('owner_actual_accounting_mismatch')
    result = deepcopy(payload)
    reference = owner_publication_reference(publication)
    refs = result.get('publication_refs')
    if type(refs) is not list: raise ValueError('invalid_publication_reference_set')
    present = [row for row in refs if row.get('publication_id') == reference['publication_id']]
    if present and present != [reference]: raise ValueError('owner_reference_mismatch')
    if not present: refs.append(reference)
    return canonical_owner_read_set_bytes(result)
