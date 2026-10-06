"""Staged immutable v2 SQL proof; no live composition or financial readiness.

The caller owns the existing ordered transaction/locks. These SELECTs borrow
its cursor; they do not start another transaction or change isolation. Historical
proof never reads today's mutable registry/metadata as old authority.
"""
from copy import deepcopy
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from uuid import UUID

from psycopg2 import Error as SqlError
from algolens.domain.portfolio.equity_configuration_inspection import parse_publication
from algolens.domain.portfolio.position_decimal import canonical_position_decimal8
from algolens.infrastructure.portfolio.qt_empty_owner_protocol import FIELDS, KEY_FIELDS, SCHEMA, canonical_empty_model_owner_bytes
from algolens.infrastructure.portfolio.qt_empty_owner_producer import configuration_digest, configured_members
from algolens.infrastructure.portfolio.qt_empty_owner_snapshot import resolve_empty_model_owner_snapshot

ENGINE = 'LIVE_EQUITY_MEAN_REVERSION'
ARCHIVE = (FIELDS - {'book_id'}) | {'portfolio_id', 'attempt_id', 'publication_version',
    'producer_version', 'configuration_snapshot', 'created_at', 'registry_id', 'registry_revision',
    'fresh_empty_batches', 'inspection_capture'}


def _need(condition):
    if not condition: raise ValueError('empty_owner_authority_unavailable')


def _uuid(value):
    _need(type(value) is str and str(UUID(value)) == value and UUID(value).int != 0)
    return value


def _integer(value, *, positive=False):
    _need(type(value) is int and (1 if positive else 0) <= value < 1 << 63)


def _day(value):
    _need(type(value) is date)
    return value.isoformat()


def _utc(value):
    _need(type(value) is datetime and value.tzinfo is not None and value.utcoffset().total_seconds() == 0)
    return value.astimezone(timezone.utc)


def _all(cursor, sql, params=()):
    cursor.execute(sql, params)
    rows = cursor.fetchall()
    _need(type(rows) is list and len(rows) <= 4096)
    return [dict(row) for row in rows]


def _one(cursor, sql, params=()):
    rows = _all(cursor, sql, params)
    _need(len(rows) == 1)
    return rows[0]


@dataclass(frozen=True)
class LegacyPublication:
    _row: dict = field(repr=False)
    kind: str = 'v1'
    @property
    def row(self): return deepcopy(self._row)


@dataclass(frozen=True)
class OwnerPublication(Mapping):
    _row: dict = field(repr=False)
    _document: dict = field(repr=False)
    control_mode: str
    current_inventory_verified: bool
    _current_qt: dict | None = field(default=None, repr=False)
    kind: str = 'v2'
    @property
    def row(self): return deepcopy(self._row)
    @property
    def document(self): return deepcopy(self._document)
    @property
    def current_qt(self): return deepcopy(self._current_qt)
    def __getitem__(self, key): return deepcopy(self._row[key])
    def __iter__(self): return iter(self._row)
    def __len__(self): return len(self._row)


def _archive(row):
    _need(set(row) == ARCHIVE and row['schema_version'] == SCHEMA)
    _uuid(row['publication_id'])
    _integer(row['publication_version'], positive=True)
    _integer(row['registry_revision'])
    _need(type(row['registry_id']) is str and bool(row['registry_id'].strip()))
    created = _utc(row['created_at'])
    doc = {name: deepcopy(row[name]) for name in FIELDS - {'book_id', 'source_day'}}
    doc.update(book_id=row['portfolio_id'], source_day=_day(row['source_day']))
    config = row['configuration_snapshot']
    _need(doc['configuration_digest'] == configuration_digest(config))
    _need(doc['configured_owner_names'] == configured_members(config))
    batches = row['fresh_empty_batches']
    _need(type(batches) is list and len(batches) == len(doc['configured_owner_names']))
    owners = []
    for batch in batches:
        _need(type(batch) is dict and set(batch) == {'portfolio_id', 'strategy_id', 'strategy_name', 'source_day'})
        _need((batch['portfolio_id'], batch['strategy_id'], batch['source_day']) ==
            (doc['book_id'], ENGINE, doc['source_day']))
        owners.append(batch['strategy_name'])
    _need(sorted(owners) == doc['configured_owner_names'])
    # Complete archived arrays are canonical/closed, without claiming that a
    # matching digest by itself proves an actual MODEL invocation.
    from algolens.infrastructure.portfolio.qt_empty_owner_protocol import validate_empty_model_owner_document
    doc = validate_empty_model_owner_document(doc)
    scope = dict(registry_id=row['registry_id'], registry_revision=row['registry_revision'],
        engine_strategy_id=ENGINE, portfolio_id=doc['book_id'], run_date=doc['source_day'])
    child = parse_publication(json.dumps(row['inspection_capture'], allow_nan=False), scope, created)
    _need(child['status'] == 'available' and child['equity_run_consumption']['complete'] is True)
    # The currently admitted actual runner emits one full owner invocation.
    # A syntactically plural owner document cannot borrow that single trace.
    _need(doc['configured_owner_names'] == [child['equity_run_consumption']['run_key']['strategy_name']])
    identity = child['identity']
    _need(identity['publication_id'] == doc['publication_id'] and identity['producer_version'] == row['producer_version'])
    _need(datetime.fromisoformat(child['publication_recorded_at'].replace('Z', '+00:00')) <= created)
    if identity['control_mode'] == 'controlled':
        _need(row['attempt_id'] == identity['runtime_attempt_id'] == doc['publication_id'])
    else:
        _need(row['attempt_id'] is None and identity['runtime_attempt_id'] is None
            and row['registry_revision'] == 0)
    return doc, identity['control_mode']


def _runtime(cursor, row, doc):
    actual = _one(cursor, '''SELECT a.id::text AS attempt_id,a.publication_id::text,
        a.registry_revision,a.run_date,a.producer_version,a.status,a.outcome,a.config_snapshot,
        i.registry_id AS intent_registry_id,i.registry_revision AS intent_registry_revision,
        i.engine_strategy_id AS intent_strategy_id,i.portfolio_id AS intent_portfolio_id,
        i.action AS intent_action,i.status AS intent_status,i.config_snapshot AS intent_config_snapshot
        FROM trading.runtime_attempts a JOIN trading.runtime_intents i ON i.id=a.intent_id
        WHERE a.id=%s''', (row['attempt_id'],))
    _need((actual['attempt_id'], actual['publication_id'], actual['registry_revision'],
        _day(actual['run_date']), actual['producer_version'], actual['status'], actual['outcome']) ==
        (row['attempt_id'], row['publication_id'], row['registry_revision'], doc['source_day'],
         row['producer_version'], 'applied', 'published'))
    _integer(actual['registry_revision'])
    _integer(actual['intent_registry_revision'])
    _need((actual['intent_registry_id'], actual['intent_registry_revision'], actual['intent_strategy_id'],
        actual['intent_portfolio_id'], actual['intent_action'], actual['intent_status']) ==
        (row['registry_id'], row['registry_revision'], ENGINE, doc['book_id'], 'run', 'approved'))
    _need(configuration_digest(actual['config_snapshot']) == row['configuration_digest']
        and configuration_digest(actual['intent_config_snapshot']) == row['configuration_digest'])


def _physical(rows, doc):
    grouped = {'system': [], 'qt_proposal': [], 'qt': []}
    for row in rows:
        stream = row['portfolio_type']
        _need(stream in grouped)
        key = {name: row[name] for name in KEY_FIELDS}
        key['date'] = _day(key['date'])
        # SQL numerics must be real Decimal/int values; float or arbitrary string
        # coercion never establishes exact accounting/position authority.
        from decimal import Decimal
        _need(type(row['quantity']) in (Decimal, int) and type(row['average_price']) in (Decimal, int))
        value = dict(key=key, quantity_exact=canonical_position_decimal8(row['quantity']),
            average_price_exact=canonical_position_decimal8(row['average_price']))
        if stream == 'qt_proposal':
            value['position_revision'] = row['position_revision']
        grouped[stream].append(value)
    for values in grouped.values():
        values.sort(key=lambda item: tuple(item['key'][name] for name in KEY_FIELDS))
    return grouped


def _current(cursor, row, doc, transaction):
    heads = _all(cursor, '''SELECT publication_id::text,publication_version FROM trading.qt_model_seed_publications
        WHERE portfolio_id=%s AND source_day=%s UNION ALL
        SELECT publication_id::text,publication_version FROM trading.qt_empty_model_owner_publications
        WHERE portfolio_id=%s AND source_day=%s ORDER BY publication_version DESC LIMIT 4097''',
        (doc['book_id'], row['source_day'], doc['book_id'], row['source_day']))
    for head in heads: _integer(head['publication_version'], positive=True)
    _need(heads and len({head['publication_version'] for head in heads}) == len(heads))
    head = max(heads, key=lambda item: item['publication_version'])
    _need(head['publication_id'] == row['publication_id'] and head['publication_version'] == row['publication_version'])
    registry = _one(cursor, '''SELECT id,strategy_type,portfolio_id,runtime_revision,lifecycle,is_active
        FROM trading.strategy_registry WHERE id=%s''', (row['registry_id'],))
    _integer(registry['runtime_revision'])
    _need(registry['strategy_type'] == ENGINE and registry['runtime_revision'] == row['registry_revision']
        and registry['lifecycle'] == 'live' and registry['is_active'] is True)
    memberships = _all(cursor, '''SELECT portfolio_id FROM trading.strategy_book_memberships
        WHERE strategy_id=%s ORDER BY portfolio_id''', (row['registry_id'],))
    books = [item['portfolio_id'] for item in memberships] or [registry['portfolio_id']]
    _need(doc['book_id'] in books)
    metadata = _one(cursor, '''SELECT date,portfolio_config->'config_inspection' AS inspection_capture
        FROM trading.live_run_metadata WHERE strategy_id=%s AND portfolio_id=%s ORDER BY date DESC LIMIT 1''',
        (ENGINE, doc['book_id']))
    _need(_day(metadata['date']) == doc['source_day'] and json.dumps(metadata['inspection_capture'], sort_keys=True, allow_nan=False) ==
        json.dumps(row['inspection_capture'], sort_keys=True, allow_nan=False))
    inputs = _one(cursor, '''SELECT portfolio_id,strategy_id,date,config_snapshot,trade_ngin_sha
        FROM trading.run_inputs WHERE portfolio_id=%s AND strategy_id=%s AND date=%s''',
        (doc['book_id'], ENGINE, row['source_day']))
    _need((inputs['portfolio_id'], inputs['strategy_id'], _day(inputs['date']), inputs['trade_ngin_sha']) ==
        (doc['book_id'], ENGINE, doc['source_day'], row['producer_version']) and
        configuration_digest(inputs['config_snapshot']) == row['configuration_digest'])
    physical = _all(cursor, '''SELECT portfolio_id,strategy_id,strategy_name,date,symbol,portfolio_type,
        quantity,average_price,qt_proposal_revision::text AS position_revision,
        daily_unrealized_pnl,daily_realized_pnl,last_update FROM trading.positions
        WHERE portfolio_id=%s AND date=%s AND portfolio_type IN ('system','qt_proposal','qt')
        ORDER BY portfolio_id,strategy_id,strategy_name,date,symbol,portfolio_type''',
        (doc['book_id'], row['source_day']))
    values = _physical(physical, doc)
    # Only the immutable MODEL/proposal inventory uses snapshot equality.
    # Actual saved QT rows may advance through exact audited human decisions.
    resolve_empty_model_owner_snapshot(doc, row['configuration_snapshot'],
        values['system'], values['qt_proposal'], doc['qt_components'])
    accounts = []
    from decimal import Decimal
    for actual in physical:
        if actual['portfolio_type'] != 'qt': continue
        key = {name: actual[name] for name in KEY_FIELDS}; key['date'] = _day(actual['date'])
        fields = {'quantity_exact': 'quantity', 'average_price_exact': 'average_price',
            'daily_unrealized_pnl_exact': 'daily_unrealized_pnl',
            'daily_realized_pnl_exact': 'daily_realized_pnl'}
        _need(all(type(actual.get(source)) in (Decimal, int) for source in fields.values()))
        accounts.append(dict(key=key, **{name: canonical_position_decimal8(actual[source])
            for name, source in fields.items()},
            last_update=_utc(actual['last_update']).isoformat().replace('+00:00', 'Z')))
    accounts.sort(key=lambda value: tuple(value['key'][name] for name in KEY_FIELDS))
    audits = _all(cursor, '''SELECT o.id,o.user_id,o.portfolio_id,o.strategy_id,o.symbol,
        o.source_app,o.before_state,o.after_state,to_jsonb(o)->'risk_check_result' AS risk_check_result,
        o.created_at,s.portfolio_id AS legacy_scope_book FROM trading.position_overrides o
        LEFT JOIN trading.position_override_legacy_scopes s ON s.override_id=o.id
        WHERE o.portfolio_id=%s OR s.portfolio_id=%s ORDER BY o.id LIMIT 4097''',
        (doc['book_id'], doc['book_id']))
    publications = []
    if transaction is not None:
        publications = transaction.read_processed_publications(row['source_day'])
        _need(type(publications) is list and len(publications) <= 4096)
        # Historical original proof and current full financial inventory are
        # distinct. Require the actual current SQL anchors for readiness here.
        from algolens.infrastructure.portfolio.qt_accounting_proof import load_accounting_evidence
        for evidence in publications:
            evidence['accounting'] = load_accounting_evidence(cursor, evidence['decision'],
                evidence['receipt']['publication_payload']['observation_id'], current=True)
    from algolens.infrastructure.portfolio.qt_empty_owner_continuity import verify_owner_qt_continuity
    result = verify_owner_qt_continuity(doc, values['qt'], accounts, audits, publications,
        archived_at=_utc(row['created_at']),
        recompute_client_factory=getattr(transaction, '_recompute_client_factory', None),
        finalization_recompute_client_factory=getattr(transaction, '_finalization_recompute_client_factory', None))
    result['source_audits'] = deepcopy(audits)
    return result


def load_model_owner_publication(cursor, publication_id, *, current=False, transaction=None):
    try:
        _uuid(publication_id); _need(type(current) is bool)
        if transaction is not None:
            _need(current and transaction.cursor is cursor)
            transaction._require_mutable()
        capability = _one(cursor, '''SELECT capability_version FROM trading.qt_storage_capabilities
            WHERE capability_name='qt_empty_model_owner_publication_v2' ''')
        _need(type(capability['capability_version']) is int and capability['capability_version'] == 1)
        legacy = _all(cursor, 'SELECT p.*,p.publication_id::text AS publication_id,'
            'p.attempt_id::text AS attempt_id FROM trading.qt_model_seed_publications p '
            'WHERE publication_id=%s', (publication_id,))
        owner = _all(cursor, 'SELECT p.*,p.publication_id::text AS publication_id,'
            'p.attempt_id::text AS attempt_id FROM trading.qt_empty_model_owner_publications p '
            'WHERE publication_id=%s', (publication_id,))
        _need(len(legacy) + len(owner) == 1)
        if legacy:
            _need(legacy[0]['publication_id'] == publication_id and type(legacy[0]['system_components']) is list
                and bool(legacy[0]['system_components']))
            # The unchanged v1 verifier remains responsible for v1 lineage.
            return LegacyPublication(deepcopy(legacy[0]))
        row = owner[0]; _need(row['publication_id'] == publication_id)
        doc, mode = _archive(row)
        if transaction is not None: _need(transaction.book_id == doc['book_id'])
        if mode == 'controlled': _runtime(cursor, row, doc)
        qt = _current(cursor, row, doc, transaction) if current else None
        return OwnerPublication(deepcopy(row), doc, mode, current, qt)
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError, SqlError):
        raise ValueError('empty_owner_authority_unavailable') from None


def owner_publication_reference(publication):
    _need(type(publication) is OwnerPublication)
    doc, row = publication.document, publication.row
    return dict(schema_version='qt-empty-model-owner-reference/v2',
        publication_id=doc['publication_id'], strategy_id=doc['strategy_id'],
        publication_version=row['publication_version'], seed_digest=doc['seed_digest'],
        proposal_manifest_digest=doc['proposal_manifest_digest'], producer_version=row['producer_version'],
        owner_document_digest=sha256(canonical_empty_model_owner_bytes(doc)).hexdigest(),
        configuration_digest=doc['configuration_digest'], qt_digest=doc['qt_digest'],
        registry_id=row['registry_id'], registry_revision=row['registry_revision'],
        configured_owner_names=list(doc['configured_owner_names']))


def load_original_model_publication(cursor, publication_id):
    """Explicit SQL presence dispatch; the pre023 v1 path remains unchanged."""
    _uuid(publication_id)
    catalog = _one(cursor, "SELECT to_regclass('trading.qt_empty_model_owner_publications') "
        "IS NOT NULL AS owner_v2_table_present")
    _need(type(catalog['owner_v2_table_present']) is bool)
    if not catalog['owner_v2_table_present']:
        rows = _all(cursor, 'SELECT * FROM trading.qt_model_seed_publications WHERE publication_id=%s',
            (publication_id,))
        _need(len(rows) <= 1)
        return rows[0] if rows else None
    publication = load_model_owner_publication(cursor, publication_id)
    return publication.row if type(publication) is LegacyPublication else publication


def load_current_model_publications(transaction, source_day, legacy_publications):
    """Actual locked union; no capability-v2 lookup on the pre023 path."""
    transaction._require_mutable()
    cursor = transaction.cursor
    presence = _one(cursor, "SELECT to_regclass('trading.qt_empty_model_owner_publications') "
        "IS NOT NULL AS owner_v2_table_present")
    _need(type(presence['owner_v2_table_present']) is bool)
    if not presence['owner_v2_table_present']: return legacy_publications
    capability = _one(cursor, "SELECT capability_version FROM trading.qt_storage_capabilities "
        "WHERE capability_name='qt_empty_model_owner_publication_v2'")
    _need(type(capability['capability_version']) is int and capability['capability_version'] == 1)
    heads = _all(cursor, '''SELECT publication_id::text,publication_version FROM trading.qt_model_seed_publications
        WHERE portfolio_id=%s AND source_day=%s UNION ALL
        SELECT publication_id::text,publication_version FROM trading.qt_empty_model_owner_publications
        WHERE portfolio_id=%s AND source_day=%s ORDER BY publication_version ASC LIMIT 4097''',
        (transaction.book_id,source_day,transaction.book_id,source_day))
    versions,ids = set(),set()
    for row in heads:
        _uuid(row['publication_id']); _integer(row['publication_version'],positive=True)
        _need(row['publication_id'] not in ids and row['publication_version'] not in versions)
        ids.add(row['publication_id']); versions.add(row['publication_version'])
    if not heads: return []
    heads.sort(key=lambda row:row['publication_version'])
    result=[]
    for index,row in enumerate(heads):
        proof=load_model_owner_publication(cursor,row['publication_id'],
            current=index==len(heads)-1, transaction=transaction if index==len(heads)-1 else None)
        actual=proof.row
        _need(actual['publication_version']==row['publication_version']
            and actual['portfolio_id']==transaction.book_id and actual['source_day']==source_day)
        result.append(actual if type(proof) is LegacyPublication else proof)
    return result


def require_empty_current_owner(publication, book, day, model):
    _need(type(publication) is OwnerPublication and publication.current_inventory_verified)
    doc,qt=publication.document,publication.current_qt
    _need((doc['book_id'],doc['source_day'],doc['publication_id'])==(book,day,model)
        and len(doc['configured_owner_names'])==1
        and doc['system_components']==doc['proposal_components']==doc['qt_components']==[]
        and type(qt) is dict and qt['rows']==qt['accounting']==[])


def load_evaluation_model_publication(transaction, source_day, model_id):
    transaction._require_mutable()
    cursor=transaction.cursor
    presence=_one(cursor,"SELECT to_regclass('trading.qt_empty_model_owner_publications') "
        "IS NOT NULL AS owner_v2_table_present")
    _need(type(presence['owner_v2_table_present']) is bool)
    if not presence['owner_v2_table_present']:
        _one(cursor,"SELECT publication_id FROM trading.qt_model_seed_publications "
            "WHERE publication_id=%s AND portfolio_id=%s AND source_day=%s",
            (model_id,transaction.book_id,source_day))
        return None
    proof=load_model_owner_publication(cursor,model_id,current=True,transaction=transaction)
    row=proof.row
    _need(row['portfolio_id']==transaction.book_id and row['source_day']==source_day)
    return proof if type(proof) is OwnerPublication else None
