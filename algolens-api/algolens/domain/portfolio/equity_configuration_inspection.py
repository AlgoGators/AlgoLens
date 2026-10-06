"""Closed equity publication3 inspection; preserves the futures parser."""
from datetime import date
import json
from algolens.domain.portfolio import configuration_inspection as legacy
from .qt_equity_run_consumption import validate_equity_run_consumption

PublicationError=legacy.PublicationError
ROOT_KEYS=frozenset({'publication_schema_version','profile','authority','stream','identity',
    'captured_at','publication_recorded_at','status','reason','equity_run_consumption'})


def _parse(raw, scope, now):
    legacy._require(type(raw) is str and len(raw.encode('utf-8'))<=legacy.MAX_DOCUMENT_BYTES)
    value=json.loads(raw,object_pairs_hook=legacy._pairs,parse_constant=legacy._reject_constant)
    if type(value) is dict and type(value.get('publication_schema_version')) is int and value['publication_schema_version'] in (4,5):
        from .governed_configuration_inspection import validate_publication
        return validate_publication(value,scope,now)
    if type(value) is not dict or type(value.get('publication_schema_version')) is not int or value['publication_schema_version']!=3:
        return legacy.parse_publication(raw,scope,now)
    legacy._keys(value,ROOT_KEYS)
    legacy._require(value['profile']=='live_equity_mean_reversion' and
        value['authority']=='inspection_only' and value['stream']=='system','unsupported_publication')
    identity=value['identity'];legacy._keys(identity,legacy.IDENTITY_KEYS)
    for name in ('registry_id','engine_strategy_id','portfolio_id'):
        legacy._require(type(identity[name]) is str and legacy.IDENTIFIER.fullmatch(identity[name]) is not None)
    legacy._require(legacy._integer(identity['registry_revision']) and identity['registry_revision']>=0)
    legacy._require(type(identity['run_date']) is str)
    day=date.fromisoformat(identity['run_date'])
    legacy._require(day.isoformat()==identity['run_date'] and day<=now.date())
    for name in ('capture_id','publication_id'):legacy._uuid(identity[name])
    legacy._require(identity['capture_id']==identity['publication_id'])
    legacy._require(identity['control_mode'] in ('controlled','uncontrolled'))
    if identity['control_mode']=='controlled':
        legacy._uuid(identity['runtime_attempt_id'])
        legacy._require(identity['runtime_attempt_id']==identity['publication_id'])
    else:legacy._require(identity['runtime_attempt_id'] is None)
    legacy._require(type(identity['producer_version']) is str and
        legacy.BUILD_TOKEN.fullmatch(identity['producer_version']) is not None and identity['producer_version']!='unversioned')
    captured=legacy._utc(value['captured_at'],now);recorded=legacy._utc(value['publication_recorded_at'],now)
    legacy._require(captured<=recorded and day<=recorded.date())
    names=('registry_id','registry_revision','engine_strategy_id','portfolio_id','run_date')
    legacy._require(tuple(identity[name] for name in names)==tuple(scope[name] for name in names),'scope_changed')
    child=validate_equity_run_consumption(value['equity_run_consumption'],expected_run_key={
        'portfolio_id':identity['portfolio_id'],'strategy_id':identity['engine_strategy_id'],
        'strategy_name':'EQUITY_MEAN_REVERSION','date':identity['run_date']})
    legacy._require((value['status'],value['reason'])==
        (('available','none') if child['available'] else ('unavailable','consumption_unavailable')))
    return value


def parse_publication(raw, scope, now):
    """Admit exact publication3 or delegate exact legacy1/2 unchanged."""
    try:
        return _parse(raw,scope,now)
    except PublicationError:
        raise
    except (ValueError,TypeError,KeyError,AttributeError,UnicodeError,RecursionError,OverflowError):
        raise PublicationError() from None
