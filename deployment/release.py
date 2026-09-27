"""Explicitly approved release only; never applies database migrations.

Run from a clean checkout of the exact green-CI SHA, after the separately
approved host cutover to the Compose frontend/backend pair. Unit tests inject
all commands. Importing this module performs no commands or network access.
"""
import argparse
import json
import os
from pathlib import PurePosixPath
import re
import subprocess
from urllib.parse import urlsplit


def release(options, *, run=subprocess.run):
    for gate in ('rollout_approved', 'schema_verified', 'backup_verified', 'maintenance_approved'):
        if options.get(gate) is not True:
            raise ValueError('Explicit operational gate missing: ' + gate)
    sha, project = options['sha'], options['project']
    if not re.fullmatch('[0-9a-f]{40}', sha):
        raise ValueError('An exact 40-character tested commit SHA is required')
    if not re.fullmatch('[a-z0-9][a-z0-9_-]*', project):
        raise ValueError('A verified existing Compose project name is required')
    origin = urlsplit(options['origin'])
    if (origin.scheme != 'https' or not origin.hostname or origin.username or origin.password
            or origin.query or origin.fragment or origin.path not in ('', '/')):
        raise ValueError('An HTTPS public origin without credentials/path is required')
    if not PurePosixPath(options['env_file']).is_absolute():
        raise ValueError('An explicitly verified absolute runtime environment path is required')

    def command(args, **kwargs):
        return run(args, text=True, capture_output=True, check=True, timeout=1800, **kwargs).stdout.strip()

    if command(['git', 'rev-parse', 'HEAD']) != sha:
        raise ValueError('Checkout does not match tested release SHA')
    if command(['git', 'status', '--porcelain', '--untracked-files=normal']):
        raise ValueError('Release checkout is not clean')
    legacy = run(['systemctl', 'is-active', '--quiet', 'algolens.service'], check=False)
    if legacy.returncode == 0:
        raise ValueError('Legacy frontend still owns port 3000; approved host cutover is required')
    if legacy.returncode not in (3, 4):
        raise ValueError('Cannot verify legacy frontend is inactive')

    env = dict(os.environ, ALGOLENS_RELEASE_SHA=sha,
               ALGOLENS_RUNTIME_ENV_FILE=options['env_file'],
               VITE_API_URL=options['origin'].rstrip('/'))
    compose = ['docker', 'compose', '--project-name', project, '-f', 'docker-compose.prod.yml']
    for service, container_port, host_port in (('backend', '5000/tcp', '5000'),
                                               ('frontend', '80/tcp', '3000')):
        existing = command([*compose, 'ps', '-q', service], env=env)
        if not re.fullmatch('[0-9a-f]{12,64}', existing):
            raise ValueError('Exactly one existing serving ' + service + ' must be identified')
        container = json.loads(command(['docker', 'inspect', existing]))[0]
        labels = container['Config']['Labels']
        ports = container['NetworkSettings']['Ports'].get(container_port)
        if (labels.get('com.docker.compose.project') != project
                or labels.get('com.docker.compose.service') != service
                or ports != [{'HostIp': '127.0.0.1', 'HostPort': host_port}]):
            raise ValueError('Existing ' + service + ' is not the verified loopback serving target')

    # Build both before updating either. No latest tags, migration or host pip install.
    command([*compose, 'build', 'backend', 'frontend'], env=env)
    command([*compose, 'up', '-d', '--no-build', '--wait', '--wait-timeout', '120',
             'backend', 'frontend'], env=env)
    for endpoint in ('http://127.0.0.1:5000/version',
                     'http://127.0.0.1:3000/release.json',
                     options['origin'].rstrip('/') + '/version',
                     options['origin'].rstrip('/') + '/release.json'):
        payload = json.loads(command(['curl', '--fail', '--silent', '--show-error',
                                      '--max-time', '10', endpoint]))
        if payload.get('release') != sha:
            raise ValueError('Installed release identity mismatch at ' + endpoint)
    return sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ('sha', 'project', 'env-file', 'origin'):
        parser.add_argument('--' + arg, required=True)
    for gate in ('rollout-approved', 'schema-verified', 'backup-verified', 'maintenance-approved'):
        parser.add_argument('--' + gate, action='store_true')
    options = vars(parser.parse_args())
    print('Verified installed frontend/API release: ' + release(options))


if __name__ == '__main__':
    main()
