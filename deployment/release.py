"""Explicitly approved release only; never applies database migrations.

Run from a clean checkout of the exact green-CI SHA, after the separately
approved host cutover to the Compose frontend/backend pair. Unit tests inject
all commands. Importing this module performs no commands or network access.
"""
import argparse
from datetime import datetime, timezone
from hashlib import sha256 as sha256_digest
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
from urllib.parse import urlsplit

_DIGEST = re.compile(r'[0-9a-f]{64}\Z')
_IMAGE_DIGEST = re.compile(r'sha256:[0-9a-f]{64}\Z')
_RELEASE_ARTIFACT_KINDS = {
    'libtrade_ngin.so': 'engine',
    'live_equity_mean_reversion': 'system_publisher',
    'live_portfolio': 'system_publisher',
    'live_portfolio_conservative': 'system_publisher',
    'qt_desk_prepare_sources': 'desk_tool',
    'qt_desk_run': 'desk_tool',
    'qt_desk_worker': 'desk_worker',
    'qt_evaluator': 'evaluator',
}


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def _approved_path(value, *, directory):
    path = Path(value)
    if (not path.is_absolute() or path.is_symlink()
            or (not path.is_dir() if directory else not path.is_file())
            or path.resolve() != path.absolute()):
        raise ValueError('An existing absolute non-symlink production contract path is required')
    return path


def _manifest(path, schema):
    def object_without_duplicates(pairs):
        value = {}
        for name, item in pairs:
            if name in value:
                raise ValueError('duplicate_json_key')
            value[name] = item
        return value
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode('utf-8', 'strict'), object_pairs_hook=object_without_duplicates)
    except (OSError, ValueError, UnicodeError):
        raise ValueError('A readable versioned production contract is required') from None
    if not isinstance(value, dict) or value.get('schema') != schema:
        raise ValueError('A resolved versioned production contract is required')
    if schema == 'algolens-database-identity/v1' and value.get('state') != 'resolved':
        raise ValueError('A resolved versioned production contract is required')
    if schema == 'release-artifacts/v1' and not _valid_release_artifact(value):
        raise ValueError('A complete T2 release-artifacts/v1 contract is required')
    return value, sha256_digest(raw).hexdigest()


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')


def _valid_release_artifact(value):
    try:
        if set(value) != {'schema','source','build','image','evaluator','artifacts',
                          'integration','manifest_sha256'}:
            return False
        source, build, image, evaluator = (value[name] for name in
                                           ('source','build','image','evaluator'))
        rows = value['artifacts']
        if (set(source) != {'git_sha_full','git_sha_short','dirty'}
                or not re.fullmatch('[0-9a-f]{40}', source['git_sha_full'])
                or not re.fullmatch('[0-9a-f]{7,40}', source['git_sha_short'])
                or not source['git_sha_full'].startswith(source['git_sha_short'])
                or source['dirty'] is not False
                or set(build) != {'build_type','compiler','cxx_standard','toolchain_image_digest','cmake_inputs'}
                or build['build_type'] != 'Release' or build['cxx_standard'] != '20'
                or not _IMAGE_DIGEST.fullmatch(str(build['toolchain_image_digest']))
                or set(build['compiler']) != {'id','version'}
                or any(not isinstance(build['compiler'][key], str)
                       or not build['compiler'][key].strip() for key in ('id','version'))
                or not isinstance(build['cmake_inputs'], list) or not build['cmake_inputs']
                or build['cmake_inputs'] != sorted(set(build['cmake_inputs']))
                or any(not isinstance(item, str) or not item or len(item) > 512
                       for item in build['cmake_inputs'])
                or set(image) != {'digest'} or not _IMAGE_DIGEST.fullmatch(str(image['digest']))
                or set(evaluator) != {'evaluator_build','evaluator_sha256','evaluator_bundle_sha256',
                                      'bundle_manifest_sha256','install_path'}
                or evaluator['evaluator_build'] != source['git_sha_short']
                or evaluator['install_path'] != 'qt-evaluator-bundle'
                or not all(_DIGEST.fullmatch(str(evaluator[key])) for key in
                           ('evaluator_sha256','evaluator_bundle_sha256','bundle_manifest_sha256'))
                or value['integration'] != {'pending_artifacts': []}
                or not isinstance(rows, list) or len(rows) != 8
                or [row.get('name') for row in rows] != sorted(_RELEASE_ARTIFACT_KINDS)
                or any(set(row) != {'name','kind','install_path','size','sha256'}
                       or row['kind'] != _RELEASE_ARTIFACT_KINDS.get(row['name'])
                       or row['install_path'] != f"bin/Release/{row['name']}"
                       or type(row['size']) is not int or not 0 < row['size'] <= 1024**3
                       or not _DIGEST.fullmatch(str(row['sha256'])) for row in rows)):
            return False
        evaluator_row = next(row for row in rows if row['name'] == 'qt_evaluator')
        unsigned = {key:item for key,item in value.items() if key != 'manifest_sha256'}
        return (evaluator_row['sha256'] == evaluator['evaluator_sha256']
                and _DIGEST.fullmatch(str(value['manifest_sha256'])) is not None
                and sha256_digest(_canonical(unsigned)).hexdigest() == value['manifest_sha256'])
    except (KeyError, TypeError, ValueError, StopIteration):
        return False


def release(options, *, run=subprocess.run, now=_now):
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
    bundle = _approved_path(options['evaluator_bundle_dir'], directory=True)
    artifact_path = _approved_path(options['release_artifact_manifest'], directory=False)
    database_path = _approved_path(options['database_identity_manifest'], directory=False)
    runtime_config_path = _approved_path(options['runtime_config_manifest'], directory=False)
    evidence_directory = _approved_path(options['evidence_dir'], directory=True)
    artifact, artifact_manifest_sha256 = _manifest(artifact_path, 'release-artifacts/v1')
    database, database_manifest_sha256 = _manifest(database_path, 'algolens-database-identity/v1')
    runtime_config_sha256 = sha256_digest(runtime_config_path.read_bytes()).hexdigest()
    destination = evidence_directory / f'{sha}.json'
    if destination.exists() or destination.is_symlink():
        raise ValueError('Immutable release evidence already exists for this SHA')

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
               ALGOLENS_EVALUATOR_BUNDLE_DIR=str(bundle),
               ALGOLENS_RUNTIME_MANIFEST_FILE=str(runtime_config_path),
               ALGOLENS_RUNTIME_CONFIG_SHA256=runtime_config_sha256,
               ALGOLENS_RELEASE_ARTIFACT_MANIFEST_FILE=str(artifact_path),
               ALGOLENS_DATABASE_IDENTITY_MANIFEST_FILE=str(database_path),
               VITE_API_URL=options['origin'].rstrip('/'))
    compose = ['docker', 'compose', '--project-name', project, '-f', 'docker-compose.prod.yml']
    command([*compose, 'config', '--quiet'], env=env)
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
    images = {}
    for service in ('backend', 'frontend'):
        image = command(['docker', 'image', 'inspect', '--format={{.Id}}',
                         f'algolens-{service}:{sha}'], env=env)
        if not re.fullmatch('sha256:[0-9a-f]{64}', image):
            raise ValueError('Built image identity is unavailable for ' + service)
        images[service] = image
    preflight = json.loads(command([*compose, 'run', '--rm', '--no-deps', 'backend',
                                    'python3', 'scripts/production_readiness.py', '--evidence'], env=env))
    evaluator = artifact['evaluator']
    db = database['database']
    expected_readiness = {
        'database': {key: db[key] for key in
                     ('name', 'server_addr', 'role', 'role_contract_sha256', 'schema_sha256')},
        'artifact': {key: evaluator[key] for key in
                     ('evaluator_build', 'evaluator_sha256', 'evaluator_bundle_sha256',
                      'bundle_manifest_sha256')},
        'live_books': [{key: book[key] for key in
                        ('registry_id', 'strategy_id', 'book_id', 'lifecycle',
                         'evaluator_build', 'evaluator_sha256', 'evaluator_bundle_sha256')}
                       for book in database['live_books']],
        'dependencies': {name: {key: database['dependencies'][name][key]
                                for key in ('schema', 'state', 'sha256')}
                         for name in ('capability', 'worker')},
        'runtime_config_sha256': runtime_config_sha256,
        'manifests': {
            'release_artifacts_sha256': artifact_manifest_sha256,
            'database_identity_sha256': database_manifest_sha256,
        },
    }
    expected_readiness['artifact'].update({
        'source_git_sha_full': artifact['source']['git_sha_full'],
        'image_digest': artifact['image']['digest'],
        'manifest_sha256': artifact['manifest_sha256'],
    })
    preflight_artifact = preflight.get('artifact') if isinstance(preflight, dict) else None
    if (not isinstance(preflight, dict)
            or preflight.get('schema') != 'algolens-readiness-evidence/v1'
            or preflight.get('status') != 'ready'
            or preflight.get('release_sha') != sha
            or not isinstance(preflight_artifact, dict)
            or {key: preflight_artifact.get(key) for key in expected_readiness['artifact']}
               != expected_readiness['artifact']
            or not _DIGEST.fullmatch(str(preflight_artifact.get('handshake_response_sha256', '')))
            or any(preflight.get(key) != value for key, value in expected_readiness.items()
                   if key != 'artifact')):
        raise ValueError('Candidate container production readiness failed')
    command([*compose, 'up', '-d', '--no-build', '--wait', '--wait-timeout', '120',
             'backend', 'frontend'], env=env)
    running_images = {}
    for service in ('backend', 'frontend'):
        installed = command([*compose, 'ps', '-q', service], env=env)
        container = json.loads(command(['docker', 'inspect', installed], env=env))[0]
        if container.get('Image') != images[service]:
            raise ValueError('Running container image mismatch for ' + service)
        running_images[service] = container['Image']
    installed_preflight = json.loads(command([
        *compose, 'exec', '-T', 'backend', 'python3',
        'scripts/production_readiness.py', '--evidence'], env=env))
    if (not isinstance(installed_preflight, dict)
            or installed_preflight.get('schema') != 'algolens-readiness-evidence/v1'
            or installed_preflight.get('status') != 'ready'
            or installed_preflight.get('release_sha') != sha
            or _canonical(installed_preflight) != _canonical(preflight)):
        raise ValueError('Installed production readiness does not match candidate evidence')
    endpoint_targets = (
        ('loopback_api_version', 'http://127.0.0.1:5000/version'),
        ('loopback_frontend_release', 'http://127.0.0.1:3000/release.json'),
        ('loopback_readiness', 'http://127.0.0.1:5000/ready'),
        ('public_api_version', options['origin'].rstrip('/') + '/version'),
        ('public_frontend_release', options['origin'].rstrip('/') + '/release.json'),
        ('public_readiness', options['origin'].rstrip('/') + '/ready'),
    )
    expected_ready_payload = {
        'status': 'ready',
        'checks': {name: 'ok' for name in (
            'artifacts', 'capability', 'configuration', 'database', 'evaluator',
            'role', 'runtime_config', 'schema', 'worker',
        )},
    }
    endpoint_payloads = {}
    for name, endpoint in endpoint_targets:
        payload = json.loads(command(['curl', '--fail', '--silent', '--show-error',
                                      '--max-time', '10', endpoint]))
        endpoint_payloads[name] = payload
        if endpoint.endswith('/ready') and payload != expected_ready_payload:
            raise ValueError('Installed readiness mismatch at ' + endpoint)
        if not endpoint.endswith('/ready') and payload.get('release') != sha:
            raise ValueError('Installed release identity mismatch at ' + endpoint)
    for loopback, public in (
        ('loopback_api_version', 'public_api_version'),
        ('loopback_frontend_release', 'public_frontend_release'),
        ('loopback_readiness', 'public_readiness'),
    ):
        if endpoint_payloads[loopback] != endpoint_payloads[public]:
            raise ValueError('Public endpoint payload does not match loopback')
    evidence = {
        'schema': 'algolens-release-evidence/v1',
        'released_at': now(),
        'algolens_release_sha': sha,
        'images': {'built': images, 'running': running_images},
        'trade_ngin': {
            'git_sha_full': artifact['source']['git_sha_full'],
            'git_sha_short': artifact['source']['git_sha_short'],
            'image_digest': artifact['image']['digest'],
            'toolchain_image_digest': artifact['build']['toolchain_image_digest'],
            'manifest_sha256': artifact['manifest_sha256'],
        },
        'evaluator': {key: evaluator[key] for key in
                      ('evaluator_build', 'evaluator_sha256', 'evaluator_bundle_sha256',
                       'bundle_manifest_sha256')},
        'database': expected_readiness['database'],
        'live_books': expected_readiness['live_books'],
        'dependencies': expected_readiness['dependencies'],
        'runtime_config_sha256': runtime_config_sha256,
        'manifests': expected_readiness['manifests'],
        'endpoint_payload_sha256': {
            name: sha256_digest(_canonical(payload)).hexdigest()
            for name, payload in endpoint_payloads.items()
        },
        'candidate_readiness_sha256': sha256_digest(_canonical(preflight)).hexdigest(),
        'installed_readiness_sha256': sha256_digest(_canonical(installed_preflight)).hexdigest(),
    }
    evidence['evidence_sha256'] = sha256_digest(_canonical(evidence)).hexdigest()
    descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, 'w', encoding='ascii') as stream:
        os.fchmod(stream.fileno(), 0o600)
        json.dump(evidence, stream, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    directory_descriptor = os.open(evidence_directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_descriptor)
    finally:
        os.close(directory_descriptor)
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ('sha', 'project', 'env-file', 'origin', 'evaluator-bundle-dir',
                'release-artifact-manifest', 'database-identity-manifest',
                'runtime-config-manifest', 'evidence-dir'):
        parser.add_argument('--' + arg, required=True)
    for gate in ('rollout-approved', 'schema-verified', 'backup-verified', 'maintenance-approved'):
        parser.add_argument('--' + gate, action='store_true')
    options = vars(parser.parse_args())
    print(json.dumps(release(options), sort_keys=True, separators=(',', ':')))


if __name__ == '__main__':
    main()
