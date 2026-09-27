"""Offline behavioral tests. No git, Docker, SSH, services or HTTP are invoked."""
import importlib.util
import json
from pathlib import Path
import subprocess
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

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))
        output, code = '', 0
        if args == ['git', 'rev-parse', 'HEAD']:
            output = self.sha
        elif args[:3] == ['git', 'status', '--porcelain']:
            output = self.dirty
        elif args[:2] == ['systemctl', 'is-active']:
            code = 0 if self.legacy_active else 3
        elif args[0:2] == ['docker', 'inspect']:
            service = 'backend' if args[-1] == self.ids['backend'] else 'frontend'
            output = json.dumps([{'Config': {'Labels': {
                'com.docker.compose.project': 'reviewed-project',
                'com.docker.compose.service': self.labels[service]}},
                'NetworkSettings': {'Ports': {('5000/tcp' if service == 'backend' else '80/tcp'): [
                    {'HostIp': '127.0.0.1', 'HostPort': self.ports[service]}]}}}])
        elif 'ps' in args:
            output = self.ids[args[-1]]
        elif args[0] == 'curl':
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
        self.fake = FakeCommands()
        self.options = dict(sha=SHA, project='reviewed-project',
                            env_file='/approved/runtime.env',
                            origin='https://example.invalid',
                            rollout_approved=True, schema_verified=True,
                            backup_verified=True, maintenance_approved=True)

    def run_release(self):
        self.module.release(self.options, run=self.fake)

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
                self.fake = FakeCommands()
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
        self.run_release()
        builds = [(a, k) for a, k in self.fake.calls if 'build' in a]
        self.assertEqual(len(builds), 1)
        self.assertEqual(builds[0][0][-2:], ['backend', 'frontend'])
        self.assertEqual(builds[0][1]['env']['ALGOLENS_RELEASE_SHA'], SHA)
        updates = [a for a, _ in self.fake.calls if 'up' in a]
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0][-2:], ['backend', 'frontend'])
        self.assertIn('--no-build', updates[0])
        self.assertFalse(any('algolens-backend' in a for a, _ in self.fake.calls))
        self.assertFalse(any('pull' in a or 'migrate' in a for a, _ in self.fake.calls))

    def test_mismatched_installed_api_or_frontend_is_not_success(self):
        for field in ('api_sha', 'ui_sha'):
            with self.subTest(field=field):
                self.fake = FakeCommands()
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

    def test_absent_multiple_foreign_or_misbound_targets_fail_before_build(self):
        for service in ('backend', 'frontend'):
            for mapping, value in [('ids', ''), ('ids', 'b' * 64 + '\n' + 'c' * 64),
                                   ('labels', 'foreign'), ('ports', '9999')]:
                with self.subTest(service=service, mapping=mapping, value=value):
                    self.fake = FakeCommands()
                    getattr(self.fake, mapping)[service] = value
                    with self.assertRaises(ValueError):
                        self.run_release()
                    self.assertFalse(any('build' in args or 'up' in args for args, _ in self.fake.calls))

    def test_verifies_all_four_exact_public_and_loopback_endpoints(self):
        self.run_release()
        self.assertEqual([a[-1] for a, _ in self.fake.calls if a[0] == 'curl'], [
            'http://127.0.0.1:5000/version', 'http://127.0.0.1:3000/release.json',
            'https://example.invalid/version', 'https://example.invalid/release.json'])


if __name__ == '__main__':
    unittest.main()
