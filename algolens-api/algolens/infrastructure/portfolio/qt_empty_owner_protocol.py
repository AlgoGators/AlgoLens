"""Pure staged v2 wire guard, never executed-owner or SQL readiness evidence."""
from copy import deepcopy
from datetime import date
from hashlib import sha256
import json
import re

SCHEMA='qt-empty-model-owner-publication/v2'
ENGINE='LIVE_EQUITY_MEAN_REVERSION'
FIELDS=frozenset(('schema_version','publication_id','book_id','strategy_id','source_day',
    'configured_owner_names','configuration_digest','system_components','seed_digest',
    'proposal_components','proposal_manifest_digest','qt_components','qt_digest'))
KEY_FIELDS=('portfolio_id','strategy_id','strategy_name','date','symbol','portfolio_type')
UUID=re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z')
HASH=re.compile(r'[0-9a-f]{64}\Z')
EXACT=re.compile(r'-?(?:0|[1-9][0-9]*)(?:\.[0-9]{1,8})?\Z')

def _need(condition):
    if not condition:raise ValueError('qt_empty_model_owner_invalid')

def _text(value):
    _need(type(value) is str and 0<len(value)<=4096 and '\x00' not in value)
    try:value.encode('utf-8')
    except UnicodeError:raise ValueError('qt_empty_model_owner_invalid') from None
    return value

def _canonical(value):
    try:return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf-8')
    except (ValueError,TypeError,UnicodeError,RecursionError):raise ValueError('qt_empty_model_owner_invalid') from None

def _exact(value):
    _need(type(value) is str and len(value)<=21 and EXACT.fullmatch(value) is not None)
    negative=value.startswith('-');unsigned=value[1:] if negative else value
    whole,_,fraction=unsigned.partition('.')
    raw=int(whole)*100000000+int(fraction.ljust(8,'0') or '0')
    _need(raw<=(1<<63) if negative else raw<(1<<63))
    _need(not negative or raw!=0)
    _need(not fraction or not fraction.endswith('0'))

def _rows(doc,name,stream,owners):
    rows=doc[name];_need(type(rows) is list and len(rows)<=4096)
    previous=None
    for row in rows:
        fields={'key','quantity_exact','average_price_exact'}
        if stream=='qt_proposal':fields|={'action','position_revision','origin_publication_id'}
        _need(type(row) is dict and set(row)==fields)
        key=row['key'];_need(type(key) is dict and set(key)==set(KEY_FIELDS))
        physical=tuple(_text(key[field]) for field in KEY_FIELDS)
        _need(key['portfolio_id']==doc['book_id'] and key['strategy_id']==ENGINE
            and key['strategy_name'] in owners and key['date']==doc['source_day']
            and key['portfolio_type']==stream)
        _need(previous is None or previous<physical);previous=physical
        _exact(row['quantity_exact']);_exact(row['average_price_exact'])
        if stream=='qt_proposal':
            _need(type(row['action']) is str and row['action'] in ('inserted','preserved'))
            for field in ('position_revision','origin_publication_id'):
                value=row[field];_need(value is None or type(value) is str and UUID.fullmatch(value) is not None)
            _need(row['action']!='inserted' or row['position_revision'] is not None and row['origin_publication_id'] is not None)
            _need(row['position_revision'] is not None or row['origin_publication_id'] is None)

def validate_empty_model_owner_document(document):
    _need(type(document) is dict and set(document)==FIELDS)
    _need(document['schema_version']==SCHEMA and document['strategy_id']==ENGINE)
    _need(type(document['publication_id']) is str and UUID.fullmatch(document['publication_id']) is not None)
    _text(document['book_id']);day=_text(document['source_day'])
    try:_need(date.fromisoformat(day).isoformat()==day)
    except ValueError:raise ValueError('qt_empty_model_owner_invalid') from None
    owners=document['configured_owner_names'];_need(type(owners) is list and 0<len(owners)<=4096)
    for owner in owners:_text(owner)
    _need(owners==sorted(set(owners)))
    _need(type(document['system_components']) is list and document['system_components']==[])
    for field in ('configuration_digest','seed_digest','proposal_manifest_digest','qt_digest'):
        _need(type(document[field]) is str and HASH.fullmatch(document[field]) is not None)
    _rows(document,'proposal_components','qt_proposal',owners)
    _rows(document,'qt_components','qt',owners)
    for field,kind,rows in (('seed_digest','seed_rows',[]),
            ('proposal_manifest_digest','proposal_rows',document['proposal_components']),
            ('qt_digest','qt_rows',document['qt_components'])):
        _need(document[field]==sha256(_canonical({kind:rows})).hexdigest())
    _need(len(_canonical(document))<=1048576)
    return deepcopy(document)

def canonical_empty_model_owner_bytes(document):
    return (SCHEMA+'\n').encode()+_canonical(validate_empty_model_owner_document(document))
