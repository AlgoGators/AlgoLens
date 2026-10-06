"""Local native fixture proof; Docker image/mount proof remains a separate gate."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPOSITORY = Path(__file__).resolve().parents[2]
BACKEND = REPOSITORY / 'algolens-api'
sys.path.insert(0, str(BACKEND))
from algolens.infrastructure.portfolio.qt_evaluator_process import QtEvaluatorProcess, QtEvaluatorUnavailable


class FixtureTests(unittest.TestCase):
    def test_real_native_closed_bundle_executes_from_sealed_memory(self):
        fixture_source = Path(__file__).parent
        with tempfile.TemporaryDirectory(prefix='qt-smoke-native-') as temporary:
            root = Path(temporary)
            subprocess.run(['gcc', '-shared', '-fPIC', str(fixture_source/'engine.c'),
                            '-Wl,-soname,libtrade_ngin.so', '-l:libcrypto.so.3', '-o', str(root/'libtrade_ngin.so')], check=True)
            subprocess.run(['gcc', str(fixture_source/'evaluator.c'), '-L'+str(root),
                            '-ltrade_ngin', '-Wl,-rpath,'+str(root), '-o', str(root/'qt_evaluator')], check=True)
            subprocess.run([sys.executable, str(fixture_source/'stage.py'), '--fixture-dir', str(root),
                            '--output', str(root/'bundle')], check=True,
                           env={**os.environ, 'PYTHONPATH':str(BACKEND/'algolens/infrastructure/portfolio')})
            manifest = json.loads((root/'bundle/qt_evaluator_manifest.json').read_text())
            executable = next(row for row in manifest['artifacts'] if row['role']=='executable')
            request = dict(schema='qt-eval/v1', operation='selected_book',
                           evaluator_build=manifest['evaluator_build'], context_fingerprint='1'*64)
            process = QtEvaluatorProcess(root/'bundle/bin/qt_evaluator', executable['sha256'],
                        manifest['evaluator_build'], bundle_directory=root/'bundle',
                        expected_bundle_sha256=manifest['bundle_sha256'])
            self.assertEqual(process.run(request), request)
            (root/'bundle/lib/libtrade_ngin.so').chmod(0o755)
            with (root/'bundle/lib/libtrade_ngin.so').open('ab') as stream:
                stream.write(b'tampered')
            with self.assertRaisesRegex(QtEvaluatorUnavailable, 'evaluator_bundle_unavailable'):
                process.run(request)


if __name__ == '__main__':
    unittest.main()
