import copy
import subprocess
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys
import pytest
from tests.test_live_config import baseline
from tests.live_config_native import native_pin
from algolens.application.live_config import LiveConfigError, native_reply
from algolens.infrastructure.config.live_config import NativeValidator,LiveConfigConfig
from algolens.infrastructure.portfolio.qt_evaluator_bundle import (LiveConfigValidatorBundle,QtEvaluatorBundle,
    QtEvaluatorBundleUnavailable, QtBundleLaunch, verify_bundle, _LIVE_CONFIG_PROFILE, _canonical)


def scope():
    data=baseline()
    return {'registry_id':'test','portfolio_id':data['portfolio_id'],'engine_strategy_id':'LIVE_TREND_FOLLOWING','config_snapshot':data}

def test_real_sealed_validator_override_and_baseline():
    validator=NativeValidator(native_pin())
    override=validator.validate(scope(),{'/optimization/cost_penalty_scalar':12.75},'override')
    base=validator.validate(scope(),{},'reset_to_baseline')
    assert base['base_sha256']==base['effective_sha256']==override['base_sha256']
    assert override['effective_snapshot']['optimization']['cost_penalty_scalar']==12.75

@pytest.mark.parametrize('change',['engine','executable','schema','build_key','wire'])
def test_validator_profile_and_closure_substitution_refused(tmp_path,change):
    pin=native_pin(); directory=tmp_path/'bundle'; shutil.copytree(pin['bundle_directory'],directory)
    path=directory/'live_config_validator_manifest.json'; manifest=json.loads(path.read_text())
    if change=='engine':
        target=directory/'lib/libtrade_ngin.so'; target.write_bytes(target.read_bytes()+b'changed')
    elif change=='executable':
        row=next(row for row in manifest['artifacts'] if row['role']=='executable')
        (directory/row['path']).rename(directory/'bin/qt_evaluator')
        row.update(name='qt_evaluator',path='bin/qt_evaluator')
    elif change=='schema': manifest['schema']='qt-evaluator-bundle/v1'
    elif change=='build_key': manifest['evaluator_build']=manifest.pop('validator_build')
    elif change=='wire': manifest['wire_schema']='qt-eval/v1'
    if change!='engine':
        manifest.pop('bundle_sha256'); manifest['bundle_sha256']=sha256(_canonical(manifest)).hexdigest(); path.write_bytes(_canonical(manifest))
    bundle=LiveConfigValidatorBundle(directory,manifest['bundle_sha256'],pin['executable_sha256'],pin['build'])
    with pytest.raises(QtEvaluatorBundleUnavailable):
        with bundle.launch(): pytest.fail('must not launch')
    # The existing QT profile cannot consume the validator bundle either.
    with pytest.raises(QtEvaluatorBundleUnavailable):
        with QtEvaluatorBundle(directory,manifest['bundle_sha256'],pin['executable_sha256'],pin['build']).launch(): pytest.fail('must not launch')

@pytest.mark.parametrize('script',['print("not json")','print("{}")','import sys;sys.stderr.write("private")',
    'import sys;sys.exit(2)','print("x"*2000000)','import time;time.sleep(2)',
    'print(\'{"x":1,"x":2}\')','print(\'{"x":NaN}\')'])
def test_bounded_failure_is_redacted(tmp_path,monkeypatch,script):
    import algolens.infrastructure.config.live_config as module
    program=tmp_path/'child.py'; program.write_text(script)
    class Bundle:
        def __init__(self,*a): pass
        @contextmanager
        def launch(self): yield QtBundleLaunch((sys.executable,str(program)),())
    monkeypatch.setattr(module,'LiveConfigValidatorBundle',Bundle)
    runner=NativeValidator({'bundle_directory':'/tmp','bundle_sha256':'a'*64,'executable_sha256':'b'*64,'build':'fixture'})
    runner.timeout_seconds=.2
    with pytest.raises(LiveConfigError,match='validator_unavailable'): runner.validate(scope(),{'/x':1},'override')


def test_manifest_expiry_change_and_duplicate_refused(tmp_path):
    pin=native_pin(); file=tmp_path/'manifest.json'
    data={'version':1,'expires_at':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),'validator':pin,'scopes':[scope()]}
    file.write_text(json.dumps(data)); config=LiveConfigConfig(allow_legacy_provisioning=True, environment={'LIVE_CONFIG_MANIFEST':str(file)})
    provision=config.load('test',scope()['portfolio_id'])
    data['validator']={**pin,'build':'different'}; file.write_text(json.dumps(data))
    with pytest.raises(LiveConfigError,match='changed'): config.recheck(provision)
    data['expires_at']='2000-01-01T00:00:00+00:00'; file.write_text(json.dumps(data))
    with pytest.raises(LiveConfigError): config.load('test',scope()['portfolio_id'])
    file.write_text('{"version":1,"version":1}')
    with pytest.raises(LiveConfigError): config.load('test',scope()['portfolio_id'])

def test_bundle_changed_after_validation_refuses_commit_gate(tmp_path):
    pin={**native_pin()}; directory=tmp_path/'bundle'; shutil.copytree(pin['bundle_directory'],directory)
    pin['bundle_directory']=str(directory)
    file=tmp_path/'manifest.json'
    data={'version':1,'expires_at':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),'validator':pin,'scopes':[scope()]}
    file.write_text(json.dumps(data)); config=LiveConfigConfig(allow_legacy_provisioning=True, environment={'LIVE_CONFIG_MANIFEST':str(file)})
    provision=config.load('test',scope()['portfolio_id'])
    config.validate(provision,{},'reset_to_baseline')
    library=directory/'lib/libtrade_ngin.so'; library.write_bytes(library.read_bytes()+b'changed')
    with pytest.raises(LiveConfigError,match='validator_unavailable'): config.recheck(provision)

@pytest.mark.parametrize('operation,changes',[('reset_to_baseline',{}),('override',{'/portfolio_id':'PRIVATE'})])
def test_real_native_refusal_envelopes_are_not_success(operation,changes):
    current=scope()
    if operation=='reset_to_baseline': current['config_snapshot']['risk']['schema']=1
    with pytest.raises(LiveConfigError,match='validator_unavailable'):
        NativeValidator(native_pin()).validate(current,changes,operation)

@pytest.mark.parametrize('profile_name',['qt','config'])
@pytest.mark.parametrize('mutation',['executable','schema','build_key'])
def test_both_fixed_profiles_reject_metadata_substitution(tmp_path,profile_name,mutation):
    # Metadata-only synthetic ELF has no machine code and is NEVER launched.
    import importlib.util
    from tests.qt_native_artifacts import require_native_artifact_paths
    from algolens.infrastructure.portfolio.qt_evaluator_bundle import _QT_PROFILE,read_elf,_ABI
    path=require_native_artifact_paths().source_dir/'tests/contracts/test_qt_evaluator_bundle.py'
    spec=importlib.util.spec_from_file_location('metadata_only_elf_fixture',path)
    fixture=importlib.util.module_from_spec(spec); spec.loader.exec_module(fixture)
    profile=_QT_PROFILE if profile_name=='qt' else _LIVE_CONFIG_PROFILE
    names={profile.executable:('executable',['libtrade_ngin.so']),
        'libtrade_ngin.so':('engine',['libcrypto.so.3']),
        'libcrypto.so.3':('dependency',['ld-linux-x86-64.so.2']),
        'ld-linux-x86-64.so.2':('loader',[])}
    rows=[]
    for name,(role,needed) in names.items():
        raw=fixture.synthetic_elf('qt_evaluator' if role=='executable' else name,needed)
        relative=('bin/' if role=='executable' else 'lib/')+name
        target=tmp_path/relative; target.parent.mkdir(exist_ok=True); target.write_bytes(raw)
        rows.append({'name':name,'role':role,'path':relative,'size':len(raw),
                     'sha256':sha256(raw).hexdigest(),'elf':read_elf(raw)})
    manifest={'schema':profile.schema,'wire_schema':profile.wire_schema,profile.build_key:'metadata-only-not-a-native-build',
              'compiler':{'id':'metadata-only','version':'test'},'abi':_ABI,'artifacts':rows}
    def save():
        manifest.pop('bundle_sha256',None)
        manifest['bundle_sha256']=sha256(_canonical(manifest)).hexdigest()
        (tmp_path/profile.manifest).write_bytes(_canonical(manifest))
    save(); verify_bundle(tmp_path,manifest['bundle_sha256'],_profile=profile)
    other=_LIVE_CONFIG_PROFILE if profile_name=='qt' else _QT_PROFILE
    if mutation=='executable':
        row=next(row for row in rows if row['role']=='executable')
        (tmp_path/row['path']).rename(tmp_path/'bin'/other.executable)
        row.update(name=other.executable,path='bin/'+other.executable)
    elif mutation=='schema': manifest['schema']=other.schema
    else: manifest[other.build_key]=manifest.pop(profile.build_key)
    save()
    with pytest.raises(ValueError): verify_bundle(tmp_path,manifest['bundle_sha256'],_profile=profile)


@pytest.mark.parametrize('changes,expected', [
    ({'/optimization/tau': 2.0, '/execution/position_limit_live': 500.0}, ['/optimization/tau']),
    ({'/optimization/tau': 2.0}, ['/optimization/tau']),
    ({'/optimization/tau': 2, '/execution/position_limit_live': 600},
     ['/execution/position_limit_live', '/optimization/tau']),
    ({'/risk/modules/0/var_limit': .3, '/risk/risk_reporting/var_limit': .3},
     ['/risk/modules/0/var_limit', '/risk/risk_reporting/var_limit']),
    ({'/strategies/TREND_FOLLOWING/config/ema_windows': [[4, 16], [8, 32]]},
     ['/strategies/TREND_FOLLOWING/config/ema_windows']),
])
def test_native_to_api_reports_only_actual_changes(changes, expected):
    result = NativeValidator(native_pin()).validate(scope(), changes, 'override')
    assert result['changed_paths'] == expected
    assert result['base_sha256'] != result['effective_sha256']


def test_native_to_api_all_noop_refuses_and_reset_has_empty_paths():
    from tests.qt_native_artifacts import require_native_artifact_paths
    changes = {'/optimization/tau': 1.0, '/execution/position_limit_live': 500}
    process = subprocess.run([str(require_native_artifact_paths().artifact('live_config_validate'))],
        input=json.dumps({'schema': 'live-config-validation/v1',
                          'base_snapshot': scope()['config_snapshot'], 'changes': changes}),
        capture_output=True, text=True, timeout=15)
    assert process.returncode == 2
    assert json.loads(process.stdout)['error']['code'] == 'live_config_noop'
    validator = NativeValidator(native_pin())
    with pytest.raises(LiveConfigError, match='validator_unavailable'):
        validator.validate(scope(), changes, 'override')
    reset = validator.validate(scope(), {}, 'reset_to_baseline')
    assert reset['changed_paths'] == []
    assert reset['effective_snapshot'] == scope()['config_snapshot']
    assert reset['base_sha256'] == reset['effective_sha256']


@pytest.mark.parametrize('mutation', [
    'omitted', 'extra', 'duplicate', 'unsorted', 'not_list', 'non_string',
    'malformed_path', 'unchanged_reported', 'wrong_assignment', 'unrequested_change',
    'missing_snapshot_key', 'noop_with_distinct_hash', 'bool_as_number',
])
def test_native_reply_rejects_inconsistent_actual_changes(mutation):
    current = scope()
    changes = {'/optimization/tau': 2.0, '/execution/position_limit_live': 600.0}
    result = NativeValidator(native_pin()).validate(current, changes, 'override')
    if mutation == 'omitted': result['changed_paths'].pop()
    elif mutation == 'extra': result['changed_paths'].append('/optimization/cost_penalty_scalar')
    elif mutation == 'duplicate': result['changed_paths'].append('/optimization/tau')
    elif mutation == 'unsorted': result['changed_paths'].reverse()
    elif mutation == 'not_list': result['changed_paths'] = '/optimization/tau'
    elif mutation == 'non_string': result['changed_paths'] = [None]
    elif mutation == 'malformed_path': result['changed_paths'][0] = 'execution/position_limit_live'
    elif mutation == 'unchanged_reported':
        changes['/execution/position_limit_live'] = 500.0
        result['effective_snapshot']['execution']['position_limit_live'] = 500.0
    elif mutation == 'wrong_assignment': result['effective_snapshot']['optimization']['tau'] = 3.0
    elif mutation == 'unrequested_change': result['effective_snapshot']['optimization']['cost_penalty_scalar'] = 12.75
    elif mutation == 'missing_snapshot_key': del result['effective_snapshot']['strategies']['TREND_FOLLOWING']['config']['_idm_rationale']
    elif mutation == 'noop_with_distinct_hash':
        changes = {'/optimization/tau': 1.0}
        result['effective_snapshot'] = copy.deepcopy(current['config_snapshot'])
        result['changed_paths'] = []
    elif mutation == 'bool_as_number':
        changes['/optimization/use_buffering'] = 1
        # A boolean true must not pass as a numerical assignment of one.
    with pytest.raises(LiveConfigError, match='validator_unavailable') as refused:
        native_reply(result, current, changes, 'override')
    assert refused.value.status == 503


@pytest.mark.parametrize('mutation', ['changed_paths', 'changed_snapshot', 'assignments'])
def test_native_reply_reset_refuses_override_evidence(mutation):
    current = scope()
    result = NativeValidator(native_pin()).validate(current, {}, 'reset_to_baseline')
    changes = {}
    if mutation == 'changed_paths': result['changed_paths'] = ['/optimization/tau']
    elif mutation == 'changed_snapshot': result['effective_snapshot']['optimization']['tau'] = 2.0
    else: changes = {'/optimization/tau': 1.0}
    with pytest.raises(LiveConfigError, match='validator_unavailable'):
        native_reply(result, current, changes, 'reset_to_baseline')
