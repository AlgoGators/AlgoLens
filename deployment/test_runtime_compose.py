"""Offline semantic YAML checks; never starts containers or opens network connections."""
import json
from pathlib import Path
import subprocess
import unittest


class RuntimeComposeTests(unittest.TestCase):
    def test_production_contracts_are_forced_and_every_input_mount_is_read_only(self):
        root = Path(__file__).resolve().parents[1]
        command = ["ruby", "-ryaml", "-rjson", "-e",
                   "puts JSON.generate(YAML.safe_load(File.read(ARGV[0]), aliases: false))",
                   str(root / "docker-compose.prod.yml")]
        result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        backend = json.loads(result.stdout)['services']['backend']
        self.assertEqual(backend['environment'], {
                'APP_RELEASE_SHA': '${ALGOLENS_RELEASE_SHA:?Exact tested release SHA required}',
                'DEV_MODE': '0',
                'FLASK_DEBUG': 'false',
                'FLASK_ENV': 'production',
                'QT_DATABASE_IDENTITY_MANIFEST': '/app/production-contracts/database-identity.json',
                'QT_EMAIL_DELIVERY_ENABLED': 'false',
                'QT_EVALUATOR_BUNDLE_DIR': '/app/qt-evaluator-bundle',
                'QT_RELEASE_ARTIFACT_MANIFEST': '/app/production-contracts/release-artifacts.json',
                'QT_RUNTIME_CONFIG_MANIFEST': '/app/runtime-control/manifest.json',
                'QT_RUNTIME_CONFIG_SHA256': '${ALGOLENS_RUNTIME_CONFIG_SHA256:?Runtime config digest required}',
                'QT_RUNTIME_CONTROL_ENABLED': 'false',
        })
        by_target = {volume['target']: volume for volume in backend['volumes'] if isinstance(volume, dict)}
        self.assertEqual(set(by_target), {
                '/app/runtime-control/manifest.json',
                '/app/qt-evaluator-bundle',
                '/app/production-contracts/release-artifacts.json',
                '/app/production-contracts/database-identity.json',
        })
        for mounted in by_target.values():
            self.assertTrue(mounted['read_only'])
            self.assertIs(mounted['bind']['create_host_path'], False)
        self.assertEqual(
            by_target['/app/runtime-control/manifest.json']['source'],
            '${ALGOLENS_RUNTIME_MANIFEST_FILE:?Runtime control manifest required}',
        )
        self.assertEqual(backend['healthcheck']['test'], ['CMD', 'curl', '-f', 'http://localhost:5000/ready'])


if __name__ == '__main__':
    unittest.main()
