"""Offline behavioral tests. No git, Docker, SSH, services or HTTP are invoked."""
import importlib.util
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SOURCE = Path(__file__).with_name('release.py')
SHA = 'a' * 40


class FakeCommands:
    def __init__(self):
        self.calls = []
        self.sha = SHA
        self.dirty = ''
        self.legacy_active = False
        self.api_sha = SHA
        self.ui_sha = SHA
        self.ids = {'backend': 'b' * 64, 'frontend': 'f' * 64}
        self.labels = {'backend': 'backend', 'frontend': 'frontend'}
        self.ports = {'backend': '5000', 'frontend': '3000'}
        self.image_ids = {'backend': 'sha256:' + '1' * 64, 'frontend': 'sha256:' + '2' * 64}
        self.running_images = dict(self.image_ids)
        self.preflight_ready = True
        self.preflight_evidence = {
            'schema': 'algolens-readiness-evidence/v1',
            'status': 'ready',
            'release_sha': SHA,
            'proof': 'candidate-and-installed',
        }
        self.installed_preflight_evidence = dict(self.preflight_evidence)
        self.readiness_ready = True
        self.readiness_payload = {
            'status': 'ready',
            'checks': {name: 'ok' for name in (
                'artifacts', 'capability', 'configuration', 'database', 'evaluator',
                'role', 'runtime_config', 'schema', 'worker',
            )},
        }
        self.deployed = False

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))
        output, code = '', 0
        if args == ['git', 'rev-parse', 'HEAD']:
            output = self.sha
        elif args[:3] == ['git', 'status', '--porcelain']:
            output = self.dirty
        elif args[:2] == ['systemctl', 'is-active']:
            code = 0 if self.legacy_active else 3
        elif args[0:3] == ['docker', 'image', 'inspect']:
            service = 'backend' if 'backend' in args[-1] else 'frontend'
            output = self.image_ids[service]
        elif args[0:2] == ['docker', 'inspect']:
            service = 'backend' if args[-1] == self.ids['backend'] else 'frontend'
            output = json.dumps([{'Config': {'Labels': {
                'com.docker.compose.project': 'reviewed-project',
                'com.docker.compose.service': self.labels[service]}},
                'Image': self.running_images[service] if self.deployed else 'sha256:' + '0' * 64,
                'NetworkSettings': {'Ports': {('5000/tcp' if service == 'backend' else '80/tcp'): [
                    {'HostIp': '127.0.0.1', 'HostPort': self.ports[service]}]}}}])
        elif 'run' in args and args[-2:] == ['scripts/production_readiness.py', '--evidence']:
            output = json.dumps(self.preflight_evidence if self.preflight_ready else {'status': 'not_ready'})
            code = 0 if self.preflight_ready else 1
        elif 'exec' in args and args[-2:] == ['scripts/production_readiness.py', '--evidence']:
            output = json.dumps(self.installed_preflight_evidence)
        elif 'up' in args:
            self.deployed = True
        elif 'ps' in args:
            output = self.ids[args[-1]]
        elif args[0] == 'curl':
            if args[-1].endswith('/ready'):
                output = json.dumps(self.readiness_payload if self.readiness_ready
                                    else {'status': 'not_ready'})
                code = 0 if self.readiness_ready else 22
            else:
                output = json.dumps({'release': self.api_sha}
                                    if args[-1].endswith('/version') else {'release': self.ui_sha})
        if kwargs.get('check', False) and code:
            raise subprocess.CalledProcessError(code, args)
        return subprocess.CompletedProcess(args, code, output, '')


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('release', SOURCE)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.temporary = tempfile.TemporaryDirectory(prefix='algolens-release-test-')
        root = Path(self.temporary.name)
        self.bundle = root / 'bundle'
        self.bundle.mkdir()
        self.artifact_manifest = root / 'release-artifacts.json'
        self.database_manifest = root / 'database-identity.json'
        self.runtime_manifest = root / 'runtime-control.json'
        self.evidence_dir = root / 'evidence'
        self.evidence_dir.mkdir()
        self.artifact = {
            'schema': 'release-artifacts/v1',
            'source': {'git_sha_full':'b'*40, 'git_sha_short':'b'*12, 'dirty':False},
            'build': {'build_type':'Release', 'compiler':{'id':'GNU','version':'14.2.0'},
                      'cxx_standard':'20', 'toolchain_image_digest':'sha256:'+'3'*64,
                      'cmake_inputs':['CMAKE_BUILD_TYPE=Release']},
            'image': {'digest':'sha256:'+'4'*64},
            'evaluator': {'evaluator_build':'b'*12, 'evaluator_sha256':'5'*64,
                          'evaluator_bundle_sha256':'6'*64,
                          'bundle_manifest_sha256':'7'*64,
                          'install_path':'qt-evaluator-bundle'},
            'artifacts': [],
            'integration': {'pending_artifacts': []},
        }
        kinds = {
            'libtrade_ngin.so':'engine', 'live_equity_mean_reversion':'system_publisher',
            'live_portfolio':'system_publisher', 'live_portfolio_conservative':'system_publisher',
            'qt_desk_prepare_sources':'desk_tool', 'qt_desk_run':'desk_tool',
            'qt_desk_worker':'desk_worker', 'qt_evaluator':'evaluator',
        }
        self.artifact['artifacts'] = [
            {'name':name, 'kind':kind, 'install_path':f'bin/Release/{name}',
             'size':100+slot, 'sha256':('5'*64 if name == 'qt_evaluator' else f'{slot:x}'*64)}
            for slot, (name, kind) in enumerate(sorted(kinds.items()), start=1)
        ]
        unsigned = json.dumps(self.artifact, sort_keys=True, separators=(',', ':')).encode('ascii')
        self.artifact['manifest_sha256'] = sha256(unsigned).hexdigest()
        self.database = {
            'schema': 'algolens-database-identity/v1', 'state': 'resolved',
            'database': {'name':'new_algo_data','server_addr':'192.0.2.10',
                         'data_directory':'/approved/postgres/data',
                         'role':'algolens_api_runtime','role_contract_sha256':'0'*64,
                         'schema_sha256':'7'*64},
            'live_books': [{'registry_id':'trendfollowing','strategy_id':'LIVE_TREND_FOLLOWING',
                            'book_id':'CONSERVATIVE_PORTFOLIO','lifecycle':'live',
                            'evaluator_build':'b'*12,
                            'evaluator_sha256':'5'*64,'evaluator_bundle_sha256':'6'*64}],
            'dependencies': {
                'capability': {'schema':'qt-capabilities/v1','state':'resolved','sha256':'8'*64},
                'worker': {'schema':'qt-worker-service/v1','state':'resolved','sha256':'9'*64}}}
        self.artifact_manifest.write_text(json.dumps(self.artifact))
        self.database_manifest.write_text(json.dumps(self.database))
        self.runtime_manifest.write_text('{"version":1,"scopes":[]}\n')
        self.fake = self.configured_fake()
        self.options = dict(sha=SHA, project='reviewed-project',
                            env_file='/approved/runtime.env',
                            origin='https://example.invalid',
                            evaluator_bundle_dir=str(self.bundle),
                            release_artifact_manifest=str(self.artifact_manifest),
                            database_identity_manifest=str(self.database_manifest),
                            runtime_config_manifest=str(self.runtime_manifest),
                            evidence_dir=str(self.evidence_dir),
                            rollout_approved=True, schema_verified=True,
                            backup_verified=True, maintenance_approved=True)

    def tearDown(self):
        self.temporary.cleanup()

    def configured_fake(self):
        fake = FakeCommands()
        expected = {
            'database': {key:self.database['database'][key] for key in
                         ('name','server_addr','role','role_contract_sha256','schema_sha256')},
            'artifact': {
                **{key:self.artifact['evaluator'][key] for key in
                   ('evaluator_build','evaluator_sha256','evaluator_bundle_sha256',
                    'bundle_manifest_sha256')},
                'source_git_sha_full': self.artifact['source']['git_sha_full'],
                'image_digest': self.artifact['image']['digest'],
                'manifest_sha256': self.artifact['manifest_sha256'],
                'handshake_response_sha256': 'a'*64,
            },
            'live_books': self.database['live_books'],
            'dependencies': self.database['dependencies'],
            'runtime_config_sha256': sha256(self.runtime_manifest.read_bytes()).hexdigest(),
            'manifests': {
                'release_artifacts_sha256': sha256(self.artifact_manifest.read_bytes()).hexdigest(),
                'database_identity_sha256': sha256(self.database_manifest.read_bytes()).hexdigest(),
            },
        }
        fake.preflight_evidence.update(expected)
        fake.installed_preflight_evidence.update(expected)
        return fake

    def run_release(self):
        return self.module.release(self.options, run=self.fake, now=lambda: '2026-10-06T08:00:00Z')

    def test_every_gate_is_required_before_any_command(self):
        for gate in ('rollout_approved', 'schema_verified', 'backup_verified', 'maintenance_approved'):
            with self.subTest(gate=gate):
                self.options[gate] = False
                with self.assertRaises(ValueError):
                    self.run_release()
                self.assertEqual(self.fake.calls, [])
                self.options[gate] = True

    def test_mismatch_and_dirty_source_stop_before_build(self):
        for field, value in [('sha', 'c' * 40), ('dirty', ' M app.py')]:
            with self.subTest(field=field):
                self.fake = self.configured_fake()
                setattr(self.fake, field, value)
                with self.assertRaises(ValueError):
                    self.run_release()
                self.assertFalse(any('build' in args for args, _ in self.fake.calls))

    def test_refuses_legacy_frontend_port_owner_without_stopping_it(self):
        self.fake.legacy_active = True
        with self.assertRaises(ValueError):
            self.run_release()
        self.assertFalse(any('stop' in args for args, _ in self.fake.calls))
        self.assertFalse(any('up' in args for args, _ in self.fake.calls))

    def test_builds_and_recreates_serving_compose_pair_at_exact_sha(self):
        evidence = self.run_release()
        builds = [(a, k) for a, k in self.fake.calls if 'build' in a]
        self.assertEqual(len(builds), 1)
        self.assertEqual(builds[0][0][-2:], ['backend', 'frontend'])
        self.assertEqual(builds[0][1]['env']['ALGOLENS_RELEASE_SHA'], SHA)
        self.assertEqual(builds[0][1]['env']['ALGOLENS_RUNTIME_MANIFEST_FILE'],
                         str(self.runtime_manifest))
        updates = [a for a, _ in self.fake.calls if 'up' in a]
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0][-2:], ['backend', 'frontend'])
        self.assertIn('--no-build', updates[0])
        self.assertFalse(any('algolens-backend' in a for a, _ in self.fake.calls))
        self.assertFalse(any('pull' in a or 'migrate' in a for a, _ in self.fake.calls))
        preflight = [a for a, _ in self.fake.calls if 'run' in a]
        self.assertEqual(len(preflight), 1)
        self.assertLess(self.fake.calls.index(next(c for c in self.fake.calls if c[0] == preflight[0])),
                        self.fake.calls.index(next(c for c in self.fake.calls if 'up' in c[0])))
        installed = [a for a, _ in self.fake.calls if 'exec' in a]
        self.assertEqual(len(installed), 1)
        self.assertGreater(self.fake.calls.index(next(c for c in self.fake.calls if c[0] == installed[0])),
                           self.fake.calls.index(next(c for c in self.fake.calls if 'up' in c[0])))
        self.assertEqual(evidence['schema'], 'algolens-release-evidence/v1')

    def test_mismatched_installed_api_or_frontend_is_not_success(self):
        for field in ('api_sha', 'ui_sha'):
            with self.subTest(field=field):
                self.fake = self.configured_fake()
                setattr(self.fake, field, 'c' * 40)
                with self.assertRaises(ValueError):
                    self.run_release()

    def test_invalid_sha_project_or_origin_is_rejected_before_commands(self):
        for field, value in [('sha', 'main'), ('project', '--all'),
                             ('origin', 'http://example.invalid'),
                             ('env_file', 'relative.env')]:
            with self.subTest(field=field):
                original = self.options[field]
                self.options[field] = value
                with self.assertRaises(ValueError):
                    self.run_release()
                self.assertEqual(self.fake.calls, [])
                self.options[field] = original

    def test_contract_paths_and_resolved_state_are_required_before_commands(self):
        for field, value in [('evaluator_bundle_dir', 'relative'),
                             ('release_artifact_manifest', 'relative.json'),
                             ('database_identity_manifest', 'relative.json'),
                             ('runtime_config_manifest', 'relative.json'),
                             ('evidence_dir', 'relative')]:
            with self.subTest(field=field):
                original = self.options[field]
                self.options[field] = value
                with self.assertRaises(ValueError):
                    self.run_release()
                self.assertEqual(self.fake.calls, [])
                self.options[field] = original
        self.artifact['state'] = 'dependency-placeholder'
        self.artifact_manifest.write_text(json.dumps(self.artifact))
        with self.assertRaises(ValueError):
            self.run_release()
        self.assertEqual(self.fake.calls, [])

    def test_existing_immutable_evidence_refuses_before_any_command(self):
        (self.evidence_dir / f'{SHA}.json').write_text('{"already":"recorded"}\n')
        with self.assertRaises(ValueError, msg='immutable evidence must never be overwritten'):
            self.run_release()
        self.assertEqual(self.fake.calls, [])

    def test_duplicate_manifest_keys_refuse_before_any_command(self):
        self.artifact_manifest.write_text(
            '{"schema":"release-artifacts/v1","schema":"release-artifacts/v1"}'
        )
        with self.assertRaises(ValueError, msg='ambiguous JSON must never be accepted'):
            self.run_release()
        self.assertEqual(self.fake.calls, [])

    def test_absent_multiple_foreign_or_misbound_targets_fail_before_build(self):
        for service in ('backend', 'frontend'):
            for mapping, value in [('ids', ''), ('ids', 'b' * 64 + '\n' + 'c' * 64),
                                   ('labels', 'foreign'), ('ports', '9999')]:
                with self.subTest(service=service, mapping=mapping, value=value):
                    self.fake = self.configured_fake()
                    getattr(self.fake, mapping)[service] = value
                    with self.assertRaises(ValueError):
                        self.run_release()
                    self.assertFalse(any('build' in args or 'up' in args for args, _ in self.fake.calls))

    def test_verifies_all_four_exact_public_and_loopback_endpoints(self):
        self.run_release()
        self.assertEqual([a[-1] for a, _ in self.fake.calls if a[0] == 'curl'], [
            'http://127.0.0.1:5000/version', 'http://127.0.0.1:3000/release.json',
            'http://127.0.0.1:5000/ready', 'https://example.invalid/version',
            'https://example.invalid/release.json', 'https://example.invalid/ready'])

    def test_candidate_preflight_or_running_image_mismatch_cannot_succeed(self):
        self.fake.preflight_ready = False
        with self.assertRaises((ValueError, subprocess.CalledProcessError)):
            self.run_release()
        self.assertFalse(any('up' in args for args, _ in self.fake.calls))
        self.fake = self.configured_fake()
        self.fake.running_images['backend'] = 'sha256:' + 'a' * 64
        with self.assertRaises(ValueError, msg='running backend image must equal built image'):
            self.run_release()

    def test_installed_readiness_must_match_candidate_evidence(self):
        self.fake.installed_preflight_evidence['proof'] = 'different-installed-state'
        with self.assertRaises(ValueError, msg='installed readiness must prove the same runtime identity'):
            self.run_release()

    def test_candidate_readiness_must_match_approved_manifests(self):
        self.fake.preflight_evidence['artifact']['evaluator_sha256'] = '0' * 64
        with self.assertRaises(ValueError, msg='candidate evidence must bind the approved inputs'):
            self.run_release()
        self.assertFalse(any('up' in args for args, _ in self.fake.calls))

    def test_readiness_stub_payload_cannot_succeed(self):
        self.fake.readiness_payload = {'status': 'ready'}
        with self.assertRaises(ValueError, msg='ready status without exact checks is not proof'):
            self.run_release()

    def test_release_evidence_is_secret_free_complete_and_self_hashed(self):
        evidence = self.run_release()
        digest = evidence.pop('evidence_sha256')
        canonical = json.dumps(evidence, sort_keys=True, separators=(',', ':')).encode('ascii')
        self.assertEqual(digest, sha256(canonical).hexdigest())
        self.assertEqual(evidence, {
            'schema': 'algolens-release-evidence/v1',
            'released_at': '2026-10-06T08:00:00Z',
            'algolens_release_sha': SHA,
            'images': {
                'built': self.fake.image_ids,
                'running': self.fake.running_images,
            },
            'trade_ngin': {
                'git_sha_full':'b'*40, 'git_sha_short':'b'*12,
                'image_digest':'sha256:'+'4'*64,
                'toolchain_image_digest':'sha256:'+'3'*64,
                'manifest_sha256':self.artifact['manifest_sha256'],
            },
            'evaluator': {key:self.artifact['evaluator'][key] for key in
                          ('evaluator_build','evaluator_sha256','evaluator_bundle_sha256',
                           'bundle_manifest_sha256')},
            'database': {'name':'new_algo_data','server_addr':'192.0.2.10',
                         'role':'algolens_api_runtime','role_contract_sha256':'0'*64,
                         'schema_sha256':'7'*64},
            'live_books': self.database['live_books'],
            'dependencies': self.database['dependencies'],
            'runtime_config_sha256': sha256(self.runtime_manifest.read_bytes()).hexdigest(),
            'manifests': {
                'release_artifacts_sha256': sha256(self.artifact_manifest.read_bytes()).hexdigest(),
                'database_identity_sha256': sha256(self.database_manifest.read_bytes()).hexdigest(),
            },
            'endpoint_payload_sha256': {
                'loopback_api_version': sha256(json.dumps(
                    {'release': SHA}, sort_keys=True, separators=(',', ':')).encode('ascii')).hexdigest(),
                'loopback_frontend_release': sha256(json.dumps(
                    {'release': SHA}, sort_keys=True, separators=(',', ':')).encode('ascii')).hexdigest(),
                'loopback_readiness': sha256(json.dumps(
                    self.fake.readiness_payload, sort_keys=True,
                    separators=(',', ':')).encode('ascii')).hexdigest(),
                'public_api_version': sha256(json.dumps(
                    {'release': SHA}, sort_keys=True, separators=(',', ':')).encode('ascii')).hexdigest(),
                'public_frontend_release': sha256(json.dumps(
                    {'release': SHA}, sort_keys=True, separators=(',', ':')).encode('ascii')).hexdigest(),
                'public_readiness': sha256(json.dumps(
                    self.fake.readiness_payload, sort_keys=True,
                    separators=(',', ':')).encode('ascii')).hexdigest(),
            },
            'candidate_readiness_sha256': sha256(
                json.dumps(self.fake.preflight_evidence, sort_keys=True,
                           separators=(',', ':')).encode('ascii')).hexdigest(),
            'installed_readiness_sha256': sha256(
                json.dumps(self.fake.installed_preflight_evidence, sort_keys=True,
                           separators=(',', ':')).encode('ascii')).hexdigest(),
        })
        evidence_path = self.evidence_dir / f'{SHA}.json'
        stored = json.loads(evidence_path.read_text())
        self.assertEqual(stored['evidence_sha256'], digest)
        self.assertNotIn('data_directory', json.dumps(stored))
        self.assertEqual(os.stat(evidence_path).st_mode & 0o777, 0o600)


if __name__ == '__main__':
    unittest.main()
