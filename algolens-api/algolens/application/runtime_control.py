"""Requested metadata is not execution authority or evidence of publication."""
import math
import re


class RuntimeControlError(Exception):
    def __init__(self, code, status=409):
        super().__init__(code)
        self.code = code
        self.status = status


SNAPSHOT_KEYS = frozenset({
    'snapshot_version', 'portfolio_id', 'initial_capital', 'reserve_capital_pct',
    'benchmark_mode', 'execution', 'optimization', 'risk', 'max_drawdown',
    'max_leverage', 'backtest', 'live', 'strategy_defaults', 'strategies',
})


def canonical_book(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value.strip()):
        raise RuntimeControlError('invalid_request', 400)
    return value.strip().upper()


def _finite_number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _safe_tree(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if (not isinstance(key, str) or any(word in key.lower() for word in
                    ('password', 'secret', 'token', 'credential')) or key.lower().startswith('smtp')):
                return False
            if not _safe_tree(item):
                return False
    elif isinstance(value, list):
        return all(_safe_tree(item) for item in value)
    elif isinstance(value, float):
        return math.isfinite(value)
    elif value is not None and type(value) not in (str, int, bool):
        return False
    return True


def validate_snapshot(snapshot, portfolio_id, engine_strategy_id, *, governed=False):
    """Validate the shared versioned, credential-free trading snapshot."""
    invalid = RuntimeControlError('runtime_configuration_unavailable', 503)
    version = snapshot.get('snapshot_version') if isinstance(snapshot, dict) else None
    keys = SNAPSHOT_KEYS | {'use_optimization', 'covariance_history_prices', 'sleeve_risk_modules'} if version == 2 else SNAPSHOT_KEYS
    if (not isinstance(snapshot, dict) or set(snapshot) != keys
            or type(version) is not int or version not in (1, 2) or (governed and version != 2)
            or snapshot['portfolio_id'] != portfolio_id or not _safe_tree(snapshot)):
        raise invalid
    for key in ('initial_capital', 'reserve_capital_pct', 'max_drawdown', 'max_leverage'):
        if not _finite_number(snapshot[key]):
            raise invalid
    if (snapshot['initial_capital'] <= 0 or snapshot['max_leverage'] <= 0
            or not 0 <= snapshot['reserve_capital_pct'] < 1
            or not 0 <= snapshot['max_drawdown'] <= 1
            or snapshot['benchmark_mode'] not in ('live', 'deferred')):
        raise invalid
    for key in ('execution', 'optimization', 'risk', 'backtest', 'live', 'strategy_defaults', 'strategies'):
        if not isinstance(snapshot[key], dict):
            raise invalid
    if version == 2 and (type(snapshot['use_optimization']) is not bool
            or type(snapshot['covariance_history_prices']) is not int
            or snapshot['covariance_history_prices'] < 2
            or not isinstance(snapshot['sleeve_risk_modules'], dict)
            or snapshot['risk'].get('schema') != 2):
        raise invalid
    selected = []
    profiles = set()
    for name, strategy in snapshot['strategies'].items():
        if not isinstance(strategy, dict) or type(strategy.get('enabled_live', False)) is not bool:
            raise invalid
        if strategy.get('enabled_live') is True:
            weight = strategy.get('default_allocation')
            if (not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', name)
                    or not _finite_number(weight) or not 0 < weight <= 1):
                raise invalid
            selected.append((name, weight))
            if version == 2:
                profile = strategy.get('type', 'TrendFollowingStrategy')
                if not isinstance(profile, str):
                    raise invalid
                profiles.add(profile)
    prefix = 'LIVE_'
    if version == 2:
        if profiles == {'MeanReversionStrategy'}:
            prefix = 'LIVE_EQUITY_'
        elif not profiles or not profiles <= {'TrendFollowingStrategy', 'TrendFollowingFastStrategy', 'TrendFollowingSlowStrategy'}:
            raise invalid
    if (not selected or abs(sum(weight for _, weight in selected) - 1) > 1e-9
            or prefix + '_'.join(sorted(name for name, _ in selected)) != engine_strategy_id):
        raise invalid


def financial_summary(snapshot):
    """The HTTP DTO never returns an unrestricted configuration blob."""
    return {'portfolio_id': snapshot['portfolio_id'], 'initial_capital': snapshot['initial_capital'],
            'allocations': [{'strategy': name, 'allocation': definition['default_allocation']}
                            for name, definition in sorted(snapshot['strategies'].items())
                            if definition.get('enabled_live') is True]}


def _reason(body, keys):
    if not isinstance(body, dict) or set(body) != set(keys):
        raise RuntimeControlError('invalid_request', 400)
    value = body.get('reason')
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 2000:
        raise RuntimeControlError('invalid_request', 400)
    return value.strip()


class RuntimeControlService:
    def __init__(self, repository, config):
        self.repository = repository
        self.config = config

    def request(self, strategy_id, body, user_id):
        if not self.config.enabled:
            raise RuntimeControlError('runtime_disabled')
        reason = _reason(body, ('action', 'portfolio_id', 'reason'))
        if body['action'] not in ('run', 'stop'):
            raise RuntimeControlError('invalid_request', 400)
        scope = self.config.scope(strategy_id, canonical_book(body['portfolio_id']))
        validate_snapshot(scope['config_snapshot'],scope['portfolio_id'],scope['engine_strategy_id'],governed=True)
        return self.repository.request(strategy_id=strategy_id, action=body['action'],
                                       reason=reason, user_id=str(user_id), scope=scope)

    def approve(self, strategy_id, intent_id, body, user_id, current_role):
        if not self.config.approval_eligible(user_id, current_role):
            raise RuntimeControlError('runtime_approval_forbidden', 403)
        if not self.config.enabled:
            raise RuntimeControlError('runtime_disabled')
        reason = _reason(body, ('reason',))
        if type(intent_id) is not int or intent_id <= 0:
            raise RuntimeControlError('invalid_request', 400)
        return self.repository.approve(strategy_id=strategy_id, intent_id=intent_id,
                                       reason=reason, user_id=str(user_id), scope_loader=self.config.scope)

    def status(self, strategy_id, portfolio_id, user_id, current_role):
        book = canonical_book(portfolio_id)
        result = self.repository.status(strategy_id=strategy_id, portfolio_id=book)
        supported = False
        if self.config.enabled:
            try:
                self.config.scope(strategy_id, book)
                supported = True
            except RuntimeControlError:
                # Historical status remains readable if today's manifest is
                # absent/invalid; new requests and approvals still fail closed.
                pass
        return {**result, 'enabled': self.config.enabled, 'engine_enabled': None,
                'scope_supported': supported,
                'approval_eligible': self.config.approval_eligible(user_id, current_role)}
