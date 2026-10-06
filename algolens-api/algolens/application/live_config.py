"""Authenticated governed candidates; activation never authorizes execution."""
import json
import re
from uuid import UUID
from algolens.application.runtime_control import canonical_book, RuntimeControlError, validate_snapshot
from algolens.domain.identity.capabilities import CANONICAL_APPROVERS

class LiveConfigError(Exception):
    def __init__(self, code, status=409):
        super().__init__(code)
        self.code, self.status = code, status


def version_id(value, *, nullable=False):
    if value is None and nullable:
        return None
    try:
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError()
    except (ValueError, TypeError):
        raise LiveConfigError('live_config_invalid_request', 400) from None
    return value


def body_fields(body, *, approval=False):
    required = {'portfolio_id', 'reason', 'expected_active_version'}
    if not approval:
        required.add('changes')
    if (not isinstance(body, dict) or not required <= set(body)
            or set(body) - required - (set() if approval else {'operation'})):
        raise LiveConfigError('live_config_invalid_request', 400)
    try:
        book = canonical_book(body['portfolio_id'])
    except RuntimeControlError:
        raise LiveConfigError('live_config_invalid_request', 400) from None
    reason = body['reason']
    if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > 2000:
        raise LiveConfigError('live_config_invalid_request', 400)
    result = dict(body, portfolio_id=book, reason=reason.strip(),
                  expected_active_version=version_id(body['expected_active_version'], nullable=True))
    if not approval:
        result.setdefault('operation', 'override')
        if result['operation'] not in ('override', 'reset_to_baseline') or not isinstance(result['changes'], dict):
            raise LiveConfigError('live_config_invalid_request', 400)
        if ((result['operation'] == 'override' and not result['changes']) or
                (result['operation'] == 'reset_to_baseline' and
                 (result['changes'] or result['expected_active_version'] is None))):
            raise LiveConfigError('live_config_invalid_request', 400)
        try:
            if len(json.dumps(result, allow_nan=False).encode()) > 262144:
                raise ValueError()
        except (ValueError, TypeError, RecursionError):
            raise LiveConfigError('live_config_invalid_request', 400) from None
    return result


def resolve_person(user_id, authority, capability):
    """Current locked facts, independent of QT enabled state and quorum."""
    account = authority['account']
    grants = [r for r in authority['grants'] if r['active'] is True and r['capability'] == capability]
    mappings = [r for r in authority['mappings'] if r['active'] is True]
    if (type(user_id) is not int or user_id <= 0 or account.get('id') != user_id
            or account.get('role') not in {'admin', 'general_member', 'exec_board'}
            or authority.get('retired') or len(grants) != 1 or len(mappings) != 1
            or mappings[0]['person_id'] not in CANONICAL_APPROVERS
            or any(type(v) is not int or v <= 0 for v in
                   (grants[0]['version'], mappings[0]['mapping_version']))):
        raise LiveConfigError('live_config_authorization_changed', 403)
    return {'user_id': user_id, 'person_id': mappings[0]['person_id'],
            'grant_version': grants[0]['version'], 'mapping_version': mappings[0]['mapping_version']}


def native_reply(result, scope, changes, operation):
    schema = 'live-config-baseline-validation/v1' if operation == 'reset_to_baseline' else 'live-config-validation/v1'
    try:
        if (not isinstance(result, dict) or set(result) != {'schema', 'base_sha256', 'effective_sha256', 'effective_snapshot', 'changed_paths'}
                or result['schema'] != schema or
                any(not isinstance(result[k], str) or not re.fullmatch('[0-9a-f]{64}', result[k]) for k in ('base_sha256','effective_sha256'))
                or result['changed_paths'] != sorted(changes)
                or (operation == 'reset_to_baseline' and result['base_sha256'] != result['effective_sha256'])
                or (operation == 'override' and result['base_sha256'] == result['effective_sha256'])):
            raise ValueError()
        validate_snapshot(result['effective_snapshot'], scope['portfolio_id'], scope['engine_strategy_id'], governed=True)
    except (ValueError, KeyError, TypeError, RuntimeControlError, RecursionError):
        raise LiveConfigError('live_config_validator_unavailable', 503) from None
    return result


class LiveConfigService:
    def __init__(self, repository, config):
        self.repository, self.config = repository, config

    def preview(self, strategy_id, body, user_id):
        return self.repository.candidate(strategy_id, body_fields(body), int(user_id), self.config, persist=False)

    def submit(self, strategy_id, body, user_id):
        return self.repository.candidate(strategy_id, body_fields(body), int(user_id), self.config, persist=True)

    def approve(self, strategy_id, request_id, body, user_id):
        return self.repository.approve(strategy_id, version_id(request_id), body_fields(body, approval=True), int(user_id), self.config)

    def status(self, strategy_id, portfolio_id):
        try:
            book = canonical_book(portfolio_id)
        except RuntimeControlError:
            raise LiveConfigError('live_config_invalid_request', 400) from None
        return self.repository.status(strategy_id, book, self.config)
