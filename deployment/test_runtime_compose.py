"""Parse Compose only, in a clean no-network namespace; never starts containers."""
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest


class RuntimeComposeTests(unittest.TestCase):
    def test_default_manifest_is_read_only_empty_and_not_execution_opt_in(self):
        self.assertEqual(sorted(name for _, name in socket.if_nameindex()), ['lo'])
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix='qt-compose-') as scratch:
            empty_env = Path(scratch) / 'synthetic.env'
            empty_env.write_text('QT_RUNTIME_CONTROL_ENABLED=false\n')
            env = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'ALGOLENS_RELEASE_SHA': 'a'*40,
                   'ALGOLENS_RUNTIME_ENV_FILE': str(empty_env)}
            # Use the installed native plugin directly. The Docker CLI's
            # Desktop symlink is unavailable inside a user/network namespace.
            parser = '/usr/libexec/docker/cli-plugins/docker-compose'
            env['DOCKER_CONFIG'] = scratch
            result = subprocess.run([parser,'--project-name','synthetic-parse-only',
                '--env-file',str(empty_env),'-f',str(root/'docker-compose.prod.yml'),
                'config','--format','json'],env=env,cwd=scratch,capture_output=True,text=True,check=False,timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            backend = json.loads(result.stdout)['services']['backend']
            self.assertEqual(backend['environment']['QT_RUNTIME_CONFIG_MANIFEST'], '/app/runtime-control/manifest.json')
            self.assertEqual(backend['environment']['QT_RUNTIME_CONTROL_ENABLED'], 'false')
            mounted = [volume for volume in backend['volumes'] if volume['target']=='/app/runtime-control/manifest.json']
            self.assertEqual(len(mounted),1)
            self.assertTrue(mounted[0]['read_only'])
            # Compose omits a false/default boolean in normalized JSON.
            self.assertFalse(mounted[0].get('bind', {}).get('create_host_path', False))
            self.assertEqual(json.loads(Path(mounted[0]['source']).read_text()), {'version':1,'scopes':[]})
            # Prove that omission is not hiding an enabled option. Parse an
            # isolated counterexample only; no service/container is started.
            original = (root/'docker-compose.prod.yml').read_text()
            self.assertEqual(original.count('create_host_path: false'), 1)
            counterexample = Path(scratch) / 'counterexample.yml'
            counterexample.write_text(original.replace('create_host_path: false', 'create_host_path: true'))
            command = [parser, '--project-name', 'synthetic-parse-only',
                       '--env-file', str(empty_env), '-f', str(counterexample),
                       'config', '--format', 'json']
            positive = subprocess.run(command, env=env, cwd=scratch,
                capture_output=True, text=True, check=False, timeout=30)
            self.assertEqual(positive.returncode, 0, positive.stderr)
            positive_mounts = json.loads(positive.stdout)['services']['backend']['volumes']
            self.assertTrue(next(volume for volume in positive_mounts
                if volume['target']=='/app/runtime-control/manifest.json')['bind']['create_host_path'])


if __name__ == '__main__':
    unittest.main()
