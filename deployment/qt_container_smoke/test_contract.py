"""The CI smoke must remain local, synthetic, non-deploying and fail closed."""
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[2]


class SmokeContractTests(unittest.TestCase):
    def test_container_has_no_network_or_writable_bundle_or_security_bypass(self):
        service = yaml.safe_load((ROOT/'deployment/qt_container_smoke/compose.yml').read_text())['services']['smoke']
        self.assertEqual(service['network_mode'], 'none')
        self.assertTrue(service['read_only'])
        self.assertEqual(service['cap_drop'], ['ALL'])
        self.assertFalse({'ports', 'env_file', 'privileged', 'security_opt'} & service.keys())
        for volume in service['volumes']:
            self.assertTrue(volume['read_only'])
            self.assertFalse(volume['bind']['create_host_path'])

    def test_ci_uses_exact_checkout_and_read_only_repository_permission(self):
        job = yaml.safe_load((ROOT/'.github/workflows/ci.yml').read_text())['jobs']['qt-container-smoke']
        self.assertEqual(job['permissions'], {'contents':'read'})
        self.assertEqual(job['steps'][0]['with']['ref'], '${{ github.sha }}')
        self.assertFalse(job['steps'][0]['with']['persist-credentials'])
        command = job['steps'][1]
        self.assertEqual(command['env']['QT_SMOKE_SOURCE_SHA'], '${{ github.sha }}')
        self.assertEqual(command['run'], 'python3 deployment/qt_container_smoke/run.py --sha "$QT_SMOKE_SOURCE_SHA"')


if __name__ == '__main__':
    unittest.main()
