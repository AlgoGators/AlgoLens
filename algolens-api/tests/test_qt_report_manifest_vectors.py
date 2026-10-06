import json
from pathlib import Path
from algolens.infrastructure.portfolio.qt_publication_proof import report_row_manifest

VECTORS = json.loads((Path(__file__).resolve().parent / 'contracts' / 'qt-report-manifest-vectors-v1.json').read_text())

def test_vectors_schema():
    assert VECTORS['schema_version'] == 'qt-report-manifest-vectors/v1' and len(VECTORS['cases']) == 9

def test_every_vector_matches_expected_digest():
    for case in VECTORS['cases']:
        got = report_row_manifest(case['before'], case['after'], case['selection_rows'])
        assert got == case['expected_manifest_digest'], case['name']
