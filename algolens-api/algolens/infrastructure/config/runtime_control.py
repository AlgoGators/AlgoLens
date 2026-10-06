"""Read an explicitly provisioned static allowlist; never load engine secrets."""
import json
import os
from pathlib import Path
import re

from algolens.application.runtime_control import RuntimeControlError, canonical_book, validate_snapshot


class RuntimeControlConfig:
    def __init__(self, environment=None, *, selected_scope_loader=None):
        self.selected_scope_loader = selected_scope_loader
        self.environment = os.environ if environment is None else environment

    @property
    def enabled(self):
        return self.environment.get('QT_RUNTIME_CONTROL_ENABLED') == 'true'

    def approval_eligible(self, user_id, current_role):
        raw = self.environment.get('QT_RUNTIME_APPROVER_IDS', '')
        if not self.enabled or current_role != 'admin' or not re.fullmatch(r'\d+(?:,\d+)*', raw):
            return False
        return str(user_id) in raw.split(',')

    def scope(self, registry_id, portfolio_id):
        if self.selected_scope_loader is not None:
            return self.selected_scope_loader(registry_id, portfolio_id)
        filename = self.environment.get('QT_RUNTIME_CONFIG_MANIFEST')
        if not filename:
            raise RuntimeControlError('runtime_scope_unsupported')
        try:
            target = Path(filename)
            if not target.is_absolute() or target.is_symlink() or not target.is_file():
                raise ValueError('invalid manifest file')
            with target.open('rb') as source:
                contents = source.read(1_048_577)
            if len(contents) > 1_048_576:
                raise ValueError('oversize manifest')
            def unique_object(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError('duplicate key')
                    result[key] = value
                return result
            def bad_constant(_):
                raise ValueError('nonfinite number')
            data = json.loads(contents, object_pairs_hook=unique_object, parse_constant=bad_constant)
            if (not isinstance(data, dict) or set(data) != {'version', 'scopes'}
                    or type(data['version']) is not int or data['version'] != 1
                    or not isinstance(data['scopes'], list) or len(data['scopes']) > 100):
                raise ValueError('invalid manifest')
            scopes = {}
            for scope in data['scopes']:
                if not isinstance(scope, dict) or set(scope) != {'registry_id', 'portfolio_id', 'engine_strategy_id', 'config_snapshot'}:
                    raise ValueError('invalid scope')
                if (not isinstance(scope['registry_id'], str) or not scope['registry_id']
                        or not isinstance(scope['engine_strategy_id'], str)
                        or canonical_book(scope['portfolio_id']) != scope['portfolio_id']):
                    raise ValueError('invalid identity')
                validate_snapshot(scope['config_snapshot'], scope['portfolio_id'], scope['engine_strategy_id'])
                key = (scope['registry_id'], scope['portfolio_id'])
                if key in scopes:
                    raise ValueError('duplicate scope')
                scopes[key] = scope
        except (OSError, ValueError, TypeError, KeyError, RuntimeControlError):
            raise RuntimeControlError('runtime_configuration_unavailable', 503) from None
        scope = scopes.get((registry_id, portfolio_id))
        if scope is None:
            raise RuntimeControlError('runtime_scope_unsupported')
        return scope
