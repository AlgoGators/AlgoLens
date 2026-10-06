"""Synthetic ELF release contract tests; these are not production release pins."""
from datetime import datetime,timedelta,timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import sys
import pytest
from algolens.application.live_config import LiveConfigError
from algolens.infrastructure.config.live_config import LiveConfigConfig
from tests.test_live_config import baseline

@pytest.fixture
def provision(tmp_path):
    source=os.environ.get('TRADE_NGIN_TEST_SOURCE_DIR')
    if not source:pytest.skip('explicit native source required for cross-repository release contract')
    root=Path(source);sys.path[:0]=[str(root/'tests/contracts'),str(root/'apps/tools')]
    import test_release_artifacts as fixtures
    import qt_evaluator_bundle as bundles
    import live_config_release as release
    f=fixtures.ReleaseArtifactsContract(methodName='runTest');f.setUp()
    try:
        worker=f.installed/'bin/Release/qt_desk_worker';worker.write_bytes(b'synthetic worker')
        f.artifacts['qt_desk_worker']={'source':worker,'install_path':'bin/Release/qt_desk_worker','kind':'desk_worker'}
        f.generate(require_worker=True)
        qt=f.installed/'qt-evaluator-bundle';shutil.copytree(f.bundle_fixture.destination,qt)
        rows=[dict(r) for r in f.bundle_fixture.artifacts];row=next(r for r in rows if r['role']=='executable');row['name']='live_config_validate'
        (f.installed/'bin/Release/live_config_validate').write_bytes(Path(row['source']).read_bytes())
        metadata={'validator_build':f.source['git_sha_short'],'compiler':f.build['compiler'],'abi':f.bundle_fixture.metadata['abi']}
        target=f.installed/'live-config-validator-bundle'
        bundle=bundles.stage_bundle(root/'apps/tools/live_config_validator_manifest.json',rows,metadata,target,profile=bundles.LIVE_CONFIG_PROFILE)
        sidecar=f.root/'live-config-release.json';release.create_manifest(sidecar,f.output,f.installed,qt,target)
        pin={'bundle_directory':str(target),'bundle_sha256':bundle['bundle_sha256'],'executable_sha256':next(r['sha256'] for r in bundle['artifacts'] if r['role']=='executable'),'build':metadata['validator_build']}
        s=baseline();scope={'registry_id':'test','portfolio_id':s['portfolio_id'],'engine_strategy_id':'LIVE_TREND_FOLLOWING','config_snapshot':s}
        data={'version':2,'expires_at':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),'validator':pin,'scopes':[scope],
            'release':{'sidecar_path':str(sidecar),'sidecar_sha256':sha256(sidecar.read_bytes()).hexdigest(),'core_manifest_path':str(f.output),'core_manifest_sha256':sha256(f.output.read_bytes()).hexdigest(),'installed_root':str(f.installed),'qt_bundle_directory':str(qt)}}
        path=tmp_path/'provision.json';path.write_text(json.dumps(data))
        yield path,data,LiveConfigConfig({'LIVE_CONFIG_MANIFEST':str(path)})
    finally:f.doCleanups()

def test_version2_verifies_actual_installed_closure_and_core(provision):
    path,data,config=provision
    from algolens.infrastructure.config.live_config_release import verify_release
    verify_release(data['validator'],data['release'])
    result=config.load('test',data['scopes'][0]['portfolio_id']);config.recheck(result)
    assert result['release']==data['release']

@pytest.mark.parametrize('damage',['publisher','engine','validator','sidecar','core','profile','build','legacy','core_array'])
def test_provisioning_fails_closed(provision,damage):
    path,data,config=provision
    result=config.load('test',data['scopes'][0]['portfolio_id'])
    root=Path(data['release']['installed_root'])
    if damage in ('publisher','engine','validator'):
        (root/'bin/Release'/dict(publisher='live_portfolio',engine='libtrade_ngin.so',validator='live_config_validate')[damage]).write_bytes(b'changed')
    elif damage in ('sidecar','core'):
        Path(data['release']['sidecar_path' if damage=='sidecar' else 'core_manifest_path']).write_text('{}')
    elif damage=='core_array':
        core=Path(data['release']['core_manifest_path']);core.write_text('[]')
        data['release']['core_manifest_sha256']=sha256(core.read_bytes()).hexdigest()
    elif damage=='profile':data['validator']['bundle_directory']=data['release']['qt_bundle_directory']
    elif damage=='build':data['validator']['build']='other'
    elif damage=='legacy':data.pop('release');data['version']=1
    path.write_text(json.dumps(data))
    with pytest.raises(LiveConfigError):config.recheck(result)

def test_legacy_provisioning_requires_explicit_test_injection(tmp_path):
    data={'version':1,'expires_at':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),
          'validator':{'bundle_directory':str(tmp_path),'bundle_sha256':'a'*64,'executable_sha256':'b'*64,'build':'test'},
          'scopes':[{'registry_id':'test','portfolio_id':baseline()['portfolio_id'],'engine_strategy_id':'LIVE_TREND_FOLLOWING','config_snapshot':baseline()}]}
    path=tmp_path/'manifest.json';path.write_text(json.dumps(data));env={'LIVE_CONFIG_MANIFEST':str(path)}
    with pytest.raises(LiveConfigError):LiveConfigConfig(env).load('test',baseline()['portfolio_id'])
    assert LiveConfigConfig(env,allow_legacy_provisioning=True).load('test',baseline()['portfolio_id'])['pin']==data['validator']


def test_core_uses_exact_native_executable_name(provision):
    from algolens.infrastructure.config.production_readiness import _valid_release_artifact, canonical_json
    _,data,_=provision
    core=json.loads(Path(data['release']['core_manifest_path']).read_text())
    assert _valid_release_artifact(core)
    row=next(row for row in core['artifacts'] if row['name']=='live_equity_mr')
    row['name']='live_equity_mean_reversion';row['install_path']='bin/Release/live_equity_mean_reversion'
    core['artifacts'].sort(key=lambda row:row['name'])
    core['manifest_sha256']=sha256(canonical_json({k:v for k,v in core.items() if k!='manifest_sha256'})).hexdigest()
    assert not _valid_release_artifact(core)
