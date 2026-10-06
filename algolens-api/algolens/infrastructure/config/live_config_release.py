"""Verify detached immutable configuration release evidence against installed bytes."""
from hashlib import sha256
import json
from pathlib import Path
from .production_readiness import _valid_release_artifact
from algolens.infrastructure.portfolio.qt_evaluator_bundle import verify_bundle, _LIVE_CONFIG_PROFILE, _canonical, _pairs


def _path(value):
    path=Path(value)
    if not path.is_absolute() or path.is_symlink() or path.resolve(strict=True)!=path:
        raise ValueError('invalid_live_config_release_path')
    return path


def _read(path,limit=1024*1024*1024):
    path=_path(path);before=path.stat()
    if not path.is_file() or not 0<before.st_size<=limit:raise ValueError('invalid_live_config_release_file')
    with path.open('rb') as stream:data=stream.read(limit+1)
    after=path.stat()
    if (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns) or len(data)!=before.st_size:raise ValueError('live_config_release_changed')
    return data


def _json(path,digest):
    data=_read(path,4*1024*1024)
    if sha256(data).hexdigest()!=digest:raise ValueError('live_config_release_pin_mismatch')
    return json.loads(data,object_pairs_hook=_pairs)


def verify_release(pin,release):
    if type(release) is not dict or set(release)!={'sidecar_path','sidecar_sha256','core_manifest_path','core_manifest_sha256','installed_root','qt_bundle_directory'}:
        raise ValueError('invalid_live_config_release')
    core=_json(release['core_manifest_path'],release['core_manifest_sha256'])
    if not _valid_release_artifact(core):raise ValueError('invalid_live_config_core')
    root=_path(release['installed_root']);qt_path=_path(release['qt_bundle_directory'])
    if qt_path!=root/'qt-evaluator-bundle':raise ValueError('live_config_release_path_mismatch')
    for row in core['artifacts']:
        raw=_read(root/row['install_path'])
        if len(raw)!=row['size'] or sha256(raw).hexdigest()!=row['sha256']:raise ValueError('live_config_core_bytes_changed')
    qt=verify_bundle(qt_path,core['evaluator']['evaluator_bundle_sha256'])
    if sha256(_read(qt_path/'qt_evaluator_manifest.json')).hexdigest()!=core['evaluator']['bundle_manifest_sha256']:
        raise ValueError('live_config_core_bundle_changed')
    core_engine=next(r for r in core['artifacts'] if r['name']=='libtrade_ngin.so')['sha256']
    if (qt['evaluator_build']!=core['source']['git_sha_short'] or
        next(r for r in qt['artifacts'] if r['role']=='executable')['sha256']!=core['evaluator']['evaluator_sha256'] or
        next(r for r in qt['artifacts'] if r['role']=='engine')['sha256']!=core_engine):
        raise ValueError('live_config_core_linkage_mismatch')
    bundle_path=_path(pin['bundle_directory'])
    if bundle_path!=root/'live-config-validator-bundle':raise ValueError('live_config_release_path_mismatch')
    bundle=verify_bundle(bundle_path,pin['bundle_sha256'],_profile=_LIVE_CONFIG_PROFILE)
    executable=next(r for r in bundle['artifacts'] if r['role']=='executable')
    engine=next(r for r in bundle['artifacts'] if r['role']=='engine')
    if (bundle['validator_build']!=pin['build'] or pin['build']!=core['source']['git_sha_short'] or
        bundle['compiler']!=core['build']['compiler'] or engine['sha256']!=core_engine or
        executable['sha256']!=pin['executable_sha256'] or
        sha256(_read(root/'bin/Release/live_config_validate')).hexdigest()!=executable['sha256']):
        raise ValueError('live_config_validator_linkage_mismatch')
    expected={'schema':'live-config-release/v1','core_manifest_sha256':core['manifest_sha256'],
        'source':core['source'],'build':core['build'],'image':core['image'],
        'validator':{'build':pin['build'],'executable_sha256':executable['sha256'],'engine_sha256':core_engine,
            'bundle_sha256':pin['bundle_sha256'],
            'bundle_manifest_sha256':sha256(_read(bundle_path/'live_config_validator_manifest.json')).hexdigest(),
            'install_path':'live-config-validator-bundle','executable_install_path':'bin/Release/live_config_validate'}}
    expected['manifest_sha256']=sha256(_canonical(expected)).hexdigest()
    if _json(release['sidecar_path'],release['sidecar_sha256'])!=expected:raise ValueError('live_config_release_mismatch')
    return expected
