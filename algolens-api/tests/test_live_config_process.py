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
from algolens.application.live_config import LiveConfigError
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
    elif change=='executable': manifest['artifacts'][0]['name']='qt_evaluator'
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
    file.write_text(json.dumps(data)); config=LiveConfigConfig({'LIVE_CONFIG_MANIFEST':str(file)})
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
    file.write_text(json.dumps(data)); config=LiveConfigConfig({'LIVE_CONFIG_MANIFEST':str(file)})
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
