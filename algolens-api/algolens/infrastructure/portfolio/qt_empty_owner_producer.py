"""Staged pure MODEL batch composition; not evidence of a SQL publication.

Fresh scopes are typed operands from the future pending native transaction.
This Python counterpart only verifies composition/canonical parity; callers
cannot submit scopes here to establish actual execution or publication.
"""
from copy import deepcopy
from hashlib import sha256
import math
from algolens.infrastructure.portfolio.qt_empty_owner_protocol import SCHEMA,_canonical,_need,_text,validate_empty_model_owner_document

def configuration_digest(configuration_snapshot):
    _need(type(configuration_snapshot) is dict)
    nodes=0
    def visit(value,depth):
        nonlocal nodes
        nodes+=1;_need(nodes<=200000 and depth<=32)
        if type(value) is dict:
            _need(len(value)<=256)
            for key,item in value.items():
                _need(type(key) is str);visit(key,depth+1);visit(item,depth+1)
        elif type(value) is list:
            _need(len(value)<=4096)
            for item in value:visit(item,depth+1)
        elif type(value) is int:_need(-(1<<63)<=value<(1<<63))
        elif type(value) is float:_need(math.isfinite(value))
        elif type(value) is str:
            try:value.encode('utf-8')
            except UnicodeError:raise ValueError('qt_empty_model_owner_invalid') from None
        else:_need(value is None or type(value) is bool)
    visit(configuration_snapshot,0)
    wire=_canonical(configuration_snapshot);_need(len(wire)<=1048576)
    return sha256(wire).hexdigest()

def configured_members(configuration_snapshot):
    configuration_digest(configuration_snapshot)
    strategies=configuration_snapshot.get('strategies');_need(type(strategies) is dict)
    enabled=[]
    for name,definition in strategies.items():
        _text(name);_need(type(definition) is dict)
        if 'enabled_live' in definition:_need(type(definition['enabled_live']) is bool)
        if definition.get('enabled_live',False):enabled.append(name)
    _need(enabled and len(enabled)<=4096)
    return sorted(enabled)

def produce_empty_model_owner_document(publication, configuration_snapshot,
        configured_owner_names, fresh_empty_batches, qt_components):
    _need(type(publication) is dict and set(publication)=={'publication_id','book_id','strategy_id',
        'source_day','system_components','proposal_components','producer_version'})
    _text(publication['producer_version'])
    owners=configured_members(configuration_snapshot)
    _need(type(configured_owner_names) is list and configured_owner_names==owners)
    _need(type(fresh_empty_batches) is list and len(fresh_empty_batches)==len(owners))
    fresh=set()
    for scope in fresh_empty_batches:
        _need(type(scope) is dict and set(scope)=={'portfolio_id','strategy_id','strategy_name','source_day'})
        _need(scope['portfolio_id']==publication['book_id'])
        for name in ('strategy_id','source_day'):_need(scope[name]==publication[name])
        owner=_text(scope['strategy_name']);_need(owner in owners and owner not in fresh);fresh.add(owner)
    _need(fresh==set(owners))
    doc={name:deepcopy(publication[name]) for name in ('publication_id','book_id','strategy_id',
        'source_day','system_components','proposal_components')}
    doc.update(schema_version=SCHEMA,configured_owner_names=list(owners),
        configuration_digest=configuration_digest(configuration_snapshot),qt_components=deepcopy(qt_components))
    for field,kind,rows in (('seed_digest','seed_rows',doc['system_components']),
            ('proposal_manifest_digest','proposal_rows',doc['proposal_components']),
            ('qt_digest','qt_rows',doc['qt_components'])):
        doc[field]=sha256(_canonical({kind:rows})).hexdigest()
    return validate_empty_model_owner_document(doc)
