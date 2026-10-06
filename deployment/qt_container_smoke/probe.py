"""Actual production-image transport/isolation check; synthetic data only."""
from hashlib import sha256
import json
import os
from pathlib import Path
from algolens.infrastructure.portfolio.qt_evaluator_process import QtEvaluatorProcess

root = Path('/app/qt-evaluator-bundle')
manifest = json.loads((root / 'qt_evaluator_manifest.json').read_text())
executable = next(row for row in manifest['artifacts'] if row['role'] == 'executable')
try:
    (root / 'must-not-be-writable').write_text('synthetic')
except OSError:
    pass
else:
    raise AssertionError('bundle mount is writable')
request = dict(schema='qt-eval/v1', operation='selected_book',
               evaluator_build=manifest['evaluator_build'], context_fingerprint='1'*64)
runner = QtEvaluatorProcess(root / executable['path'], executable['sha256'], manifest['evaluator_build'],
                            bundle_directory=root, expected_bundle_sha256=manifest['bundle_sha256'])
assert runner.run(request) == request
print(json.dumps({'schema':'qt-container-smoke/v1', 'source_sha':os.environ['APP_RELEASE_SHA'],
                  'bundle_sha256':manifest['bundle_sha256'], 'read_only_mount':True,
                  'sealed_native_transport':True, 'network_namespace':True,
                  'financial_evaluator_semantics':'not_tested', 'production_readiness':'not_tested'}, sort_keys=True))
