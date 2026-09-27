"""Real native v1 reference compatibility under four explicit SQL states.

The original API a3_db supplies a nonempty v1 publication and no v2 table.
These tests prove reference loading only, not financial readiness or MODEL.
"""
import ctypes
import json
import os
from pathlib import Path
import subprocess

import psycopg2
import pytest
from tests.integration.test_qt_a3_read_set_postgres import a3_db, PUBLICATION

BIN = Path('/home/devcontainers/qt-validation-20260921/bin/Debug')
PROBE = Path(os.environ.get('QT_LEGACY_CAPABILITY_PROBE', str(BIN/'qt_empty_owner_loader_probe')))
GUARD = BIN/'libqt_no_delivery_guard.so'


def state(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT c.oid,n.nspname,c.relname,c.relkind,c.relpersistence,c.relhasrules "
                    "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='trading' ORDER BY c.oid")
        catalog = cur.fetchall()
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='trading' ORDER BY tablename")
        tables = [r[0] for r in cur.fetchall()]
        rows = {}
        for name in tables:
            assert name.replace('_', '').isalnum()
            cur.execute('SELECT to_jsonb(t)::text FROM trading.' + name + ' t ORDER BY to_jsonb(t)::text')
            rows[name] = cur.fetchall()
        cur.execute('SHOW search_path')
        path = cur.fetchone()
    return catalog, rows, path


@pytest.mark.parametrize('mode,accepted', [
    ('neither', True), ('empty_capability_table', True),
    ('archive_without_capability', False), ('claimed_marker_without_archive', False),
])
def test_legacy_reference_capability_boundary(a3_db, mode, accepted):
    root = next(p for p in Path(__file__).resolve().parents if (p/'.review/trade-ngin-qt').is_dir())
    isolated = root/'docs/repairs/2026-09-26-hemdutt-issue-completion/empty-owner-protocol-staging/legacy-capability-1/isolated-1/qt_empty_owner_loader_probe'
    assert PROBE in (BIN/'qt_empty_owner_loader_probe', isolated)
    assert PROBE.is_file() and not PROBE.is_symlink()
    assert GUARD.is_file() and not GUARD.is_symlink()
    assert os.environ['LD_PRELOAD'] == str(GUARD)
    assert ctypes.CDLL(None).qt_no_delivery_guard_loaded() == 1
    with psycopg2.connect(a3_db) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('trading.qt_storage_capabilities'), "
                        "to_regclass('trading.qt_empty_model_owner_publications')")
            assert cur.fetchone() == (None, None)
            if mode in ('empty_capability_table', 'claimed_marker_without_archive'):
                cur.execute('CREATE TABLE trading.qt_storage_capabilities '
                            '(capability_name text PRIMARY KEY, capability_version integer NOT NULL)')
            if mode == 'claimed_marker_without_archive':
                cur.execute("INSERT INTO trading.qt_storage_capabilities VALUES "
                            "('qt_empty_model_owner_publication_v2',1)")
            if mode == 'archive_without_capability':
                cur.execute('CREATE TABLE trading.qt_empty_model_owner_publications (publication_id uuid PRIMARY KEY)')
            cur.execute('SELECT publication_id::text,strategy_id,publication_version,seed_digest,'
                        'proposal_manifest_digest,producer_version FROM trading.qt_model_seed_publications '
                        'WHERE publication_id=%s', (PUBLICATION,))
            reference = dict(zip(('publication_id', 'strategy_id', 'publication_version', 'seed_digest',
                                  'proposal_manifest_digest', 'producer_version'), cur.fetchone()))
        conn.commit()
        before = state(conn)
        result = subprocess.run([str(PROBE), 'record', PUBLICATION], env=os.environ.copy(),
                                capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, (result.returncode, result.stdout[-1000:], result.stderr[-500:])
        assert state(conn) == before
        if accepted:
            assert result.stdout.startswith('EMPTY_ARCHIVE='), result.stdout
            assert json.loads(result.stdout.removeprefix('EMPTY_ARCHIVE=')) == {
                'kind': 'legacy_v1', 'reference': reference}
            assert len(reference) == 6
        else:
            assert result.stdout == 'EMPTY_ARCHIVE_REFUSED=1\n'
