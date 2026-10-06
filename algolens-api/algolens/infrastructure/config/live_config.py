"""Provisioned native baseline and closed validator bundle, reread at each gate."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import tempfile
from algolens.application.live_config import LiveConfigError, native_reply
from algolens.application.runtime_control import validate_snapshot, RuntimeControlError
from algolens.infrastructure.portfolio.qt_evaluator_bundle import LiveConfigValidatorBundle, QtEvaluatorBundleUnavailable, verify_bundle, _LIVE_CONFIG_PROFILE
from algolens.infrastructure.portfolio.qt_evaluator_process import QtEvaluatorProcess, QtEvaluatorUnavailable, _object


def _constant(_):
    raise ValueError('nonfinite')


class NativeValidator:
    # Only the pipe exchange is shared: evaluator request/response rules are not.
    timeout_seconds = 15.0
    max_output_bytes = 1_048_576
    _exchange = QtEvaluatorProcess._exchange

    def __init__(self, pin):
        self.pin = pin

    def validate(self, scope, changes, operation):
        baseline = operation == 'reset_to_baseline'
        payload = {'schema': 'live-config-baseline-validation/v1' if baseline else 'live-config-validation/v1',
                   'base_snapshot': scope['config_snapshot']}
        if not baseline:
            payload['changes'] = changes
        try:
            encoded = json.dumps(payload, allow_nan=False, separators=(',', ':')).encode()
            if len(encoded) > 1_048_576:
                raise ValueError()
            pin = self.pin
            bundle = LiveConfigValidatorBundle(Path(pin['bundle_directory']), pin['bundle_sha256'],
                                               pin['executable_sha256'], pin['build'])
            with bundle.launch() as launch, tempfile.TemporaryDirectory(prefix='live-config-') as scratch:
                process = subprocess.Popen(launch.argv, pass_fds=launch.pass_fds, cwd=scratch,
                    env={'PATH':'/usr/bin:/bin', 'TZ':'UTC', 'PYTHON_DOTENV_DISABLED':'1'},
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
                raw = self._exchange(process, encoded)
            result = json.loads(raw.decode('utf-8'), object_pairs_hook=_object, parse_constant=_constant)
        except (OSError, ValueError, TypeError, KeyError, UnicodeError, RecursionError,
                QtEvaluatorUnavailable, QtEvaluatorBundleUnavailable):
            raise LiveConfigError('live_config_validator_unavailable', 503) from None
        return native_reply(result, scope, changes, operation)


class LiveConfigConfig:
    def __init__(self, environment=None, *, validator_factory=NativeValidator):
        self.environment = os.environ if environment is None else environment
        self.validator_factory = validator_factory

    def load(self, registry_id, portfolio_id):
        try:
            path = Path(self.environment['LIVE_CONFIG_MANIFEST'])
            if not path.is_absolute() or path.is_symlink() or path.resolve() != path:
                raise ValueError()
            with path.open('rb') as source:
                raw = source.read(1_048_577)
            if len(raw) > 1_048_576:
                raise ValueError()
            data = json.loads(raw, object_pairs_hook=_object, parse_constant=_constant)
            if (not isinstance(data, dict) or set(data) != {'version','expires_at','validator','scopes'}
                    or type(data['version']) is not int or data['version'] != 1):
                raise ValueError()
            expiry = datetime.fromisoformat(data['expires_at'])
            if expiry.tzinfo is None or expiry <= datetime.now(timezone.utc):
                raise ValueError()
            pin = data['validator']
            if not isinstance(pin, dict) or set(pin) != {'bundle_directory','bundle_sha256','executable_sha256','build'}:
                raise ValueError()
            LiveConfigValidatorBundle(Path(pin['bundle_directory']),pin['bundle_sha256'],pin['executable_sha256'],pin['build'])
            if not isinstance(data['scopes'], list) or not 0 < len(data['scopes']) <= 100:
                raise ValueError()
            scopes = {}
            for scope in data['scopes']:
                if not isinstance(scope, dict) or set(scope) != {'registry_id','portfolio_id','engine_strategy_id','config_snapshot'}:
                    raise ValueError()
                validate_snapshot(scope['config_snapshot'],scope['portfolio_id'],scope['engine_strategy_id'],governed=True)
                key = (scope['registry_id'],scope['portfolio_id'])
                if key in scopes:
                    raise ValueError()
                scopes[key] = scope
            scope = scopes.get((registry_id,portfolio_id))
            if scope is None:
                raise LiveConfigError('live_config_scope_unsupported')
            return {'scope':scope, 'pin':pin, 'expires_at':data['expires_at']}
        except LiveConfigError:
            raise
        except (OSError, ValueError, TypeError, KeyError, RuntimeControlError, RecursionError):
            raise LiveConfigError('live_config_configuration_unavailable', 503) from None

    def validate(self, provision, changes, operation):
        return self.validator_factory(provision['pin']).validate(provision['scope'],changes,operation)

    def recheck(self, provision):
        scope = provision['scope']
        if self.load(scope['registry_id'],scope['portfolio_id']) != provision:
            raise LiveConfigError('live_config_configuration_changed')
        try:
            pin = provision['pin']
            manifest = verify_bundle(Path(pin['bundle_directory']),pin['bundle_sha256'],_profile=_LIVE_CONFIG_PROFILE)
            executable = next(row for row in manifest['artifacts'] if row['role']=='executable')
            if manifest['validator_build'] != pin['build'] or executable['sha256'] != pin['executable_sha256']:
                raise ValueError()
        except (OSError,ValueError,TypeError,KeyError,StopIteration):
            raise LiveConfigError('live_config_validator_unavailable',503) from None
