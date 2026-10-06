"""Local Debug artifacts are test evidence, never release provisioning."""
import atexit
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from tests.qt_native_artifacts import require_native_artifact_paths
from algolens.infrastructure.portfolio.qt_evaluator_bundle import read_elf, _canonical, _ABI, verify_bundle, _LIVE_CONFIG_PROFILE

@lru_cache(maxsize=1)
def native_pin():
    paths=require_native_artifact_paths()
    executable=paths.artifact('live_config_validate')
    result=subprocess.run(['/usr/bin/ldd',str(executable)],capture_output=True,text=True,check=True)
    sources={'live_config_validate':executable}
    for line in result.stdout.splitlines():
        if 'linux-vdso' in line: continue
        match=re.search(r'(?:([^ ]+) => )?(/[^ ]+) \(0x[0-9a-f]+\)',line.strip())
        assert match, line
        name,path=match.groups(); sources[name or Path(path).name]=Path(path)
    temporary=tempfile.TemporaryDirectory(prefix='live-config-test-bundle-'); atexit.register(temporary.cleanup)
    directory=Path(temporary.name)
    cache=(paths.build_dir/'CMakeCache.txt').read_text()
    cmake_version='.'.join(re.search(r'CMAKE_CACHE_'+part+r'_VERSION:INTERNAL=(\d+)',cache).group(1) for part in ('MAJOR','MINOR','PATCH'))
    text=(paths.build_dir/'CMakeFiles'/cmake_version/'CMakeCXXCompiler.cmake').read_text()
    def setting(name): return re.search(r'set\('+name+r' "([^"\n]+)"\)',text).group(1)
    # Generated CMake build identity used by the binary's engine library.
    headers=list(paths.build_dir.rglob('version_config.hpp'))
    if not headers: headers=list(paths.build_dir.rglob('version.hpp'))
    identity=None
    for path in paths.build_dir.rglob('*version*.h*'):
        match=re.search(r'TRADE_NGIN_GIT_SHA\s+"([^"\n]+)"',path.read_text())
        if match: identity=match.group(1); break
    assert identity, 'real generated build identity required'
    rows=[]
    for name,path in sorted(sources.items()):
        role={'live_config_validate':'executable','libtrade_ngin.so':'engine','ld-linux-x86-64.so.2':'loader'}.get(name,'dependency')
        relative=('bin/' if role=='executable' else 'lib/')+name
        target=directory/relative; target.parent.mkdir(exist_ok=True); shutil.copyfile(path,target)
        raw=target.read_bytes()
        rows.append({'name':name,'role':role,'path':relative,'size':len(raw),'sha256':sha256(raw).hexdigest(),'elf':read_elf(raw)})
    manifest={'schema':'live-config-validator-bundle/v1','wire_schema':'live-config-validation/v1',
        'validator_build':identity,'compiler':{'id':setting('CMAKE_CXX_COMPILER_ID'),'version':setting('CMAKE_CXX_COMPILER_VERSION')},
        'abi':_ABI,'artifacts':rows}
    manifest['bundle_sha256']=sha256(_canonical(manifest)).hexdigest()
    (directory/_LIVE_CONFIG_PROFILE.manifest).write_bytes(_canonical(manifest))
    verify_bundle(directory,manifest['bundle_sha256'],_profile=_LIVE_CONFIG_PROFILE)
    return {'bundle_directory':str(directory),'bundle_sha256':manifest['bundle_sha256'],
            'executable_sha256':next(r['sha256'] for r in rows if r['role']=='executable'),'build':identity}
