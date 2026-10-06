#!/usr/bin/env python3
"""Non-deploying exact-commit Docker smoke, synthetic artifacts only."""
import argparse
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile
import uuid


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sha', required=True)
    args = parser.parse_args(argv)
    if not re.fullmatch('[0-9a-f]{40}', args.sha):
        parser.error('an exact full Git SHA is required')
    repository = Path(__file__).resolve().parents[2]
    def git(*command, **kwargs):
        return subprocess.run(['git', '-C', str(repository), *command], check=True, capture_output=True, **kwargs).stdout
    if git('rev-parse', 'HEAD', text=True).strip() != args.sha:
        parser.error('SHA must equal checked-out HEAD')
    # No daemon environment/context override can select a remote host.
    docker = ['docker', '--host', 'unix:///var/run/docker.sock']
    clean_env = {key: os.environ[key] for key in ('PATH', 'HOME') if key in os.environ}
    def run(command, **kwargs):
        return subprocess.run(command, env=clean_env, check=True, capture_output=True, text=True, timeout=1200, **kwargs)
    run([*docker, 'version'])
    identity = uuid.uuid4().hex
    fixture_name = 'qt-smoke-fixture-' + identity
    smoke_name = 'qt-smoke-' + identity
    fixture_image = 'algolens-qt-fixture:' + args.sha
    image = 'algolens-qt-smoke:' + args.sha
    with tempfile.TemporaryDirectory(prefix='qt-container-smoke-') as temporary:
        root = Path(temporary)
        source = root / 'source'
        source.mkdir()
        # Build only committed bytes; working-tree files never enter either image.
        archive = git('archive', '--format=tar', args.sha)
        with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
            stream.extractall(source, filter='data')
        try:
            run([*docker, 'build', '--build-arg', 'APP_RELEASE_SHA='+args.sha,
                 '--tag', image, str(source / 'algolens-api')])
            metadata = json.loads(run([*docker, 'image', 'inspect', image]).stdout)[0]
            assert metadata['Config']['Labels']['org.opencontainers.image.revision'] == args.sha
            run([*docker, 'build', '--file', str(source / 'deployment/qt_container_smoke/Dockerfile.fixture'),
                 '--tag', fixture_image, str(source)])
            run([*docker, 'create', '--name', fixture_name, fixture_image])
            run([*docker, 'cp', fixture_name+':/bundle', str(root / 'bundle')])
            clean_env.update(APP_RELEASE_SHA=args.sha, QT_SMOKE_BUNDLE=str(root / 'bundle'),
                             QT_SMOKE_SCRIPT=str(source / 'deployment/qt_container_smoke/probe.py'))
            compose = [*docker, 'compose', '--project-name', smoke_name, '--file',
                       str(source / 'deployment/qt_container_smoke/compose.yml')]
            run([*compose, 'config', '--quiet'])
            result = run([*compose, 'run', '--name', smoke_name, '--no-deps', 'smoke'])
            container = json.loads(run([*docker, 'inspect', smoke_name]).stdout)[0]
            assert container['Image'] == metadata['Id']
            assert container['State']['ExitCode'] == 0
            assert container['HostConfig']['NetworkMode'] == 'none'
            mounts = {row['Destination']:row for row in container['Mounts']}
            assert mounts['/app/qt-evaluator-bundle']['RW'] is False
            evidence = json.loads(result.stdout)
            assert evidence['source_sha'] == args.sha
            evidence.update(image_id=metadata['Id'], installed_image_verified=True)
            print(json.dumps(evidence, sort_keys=True))
        finally:
            for name in (smoke_name, fixture_name):
                subprocess.run([*docker, 'rm', '--force', name], env=clean_env,
                               capture_output=True, timeout=30, check=False)


if __name__ == '__main__':
    main()
