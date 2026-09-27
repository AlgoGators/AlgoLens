"""Storage authority and guards on the owned PostgreSQL fixture only."""
from pathlib import Path

import psycopg2
import pytest

from tests.integration.test_qt_workflow_postgres import qt_db, _execute
from tests.qt_native_evaluator import native_evaluator_configuration


MIGRATION = Path(__file__).resolve().parents[2] / "migrations/004_qt_governed_sources.sql"
BUNDLE_MIGRATION = Path(__file__).resolve().parents[2] / "migrations/005_qt_evaluator_bundle.sql"


@pytest.fixture
def governed_db(qt_db):
    _execute(qt_db, MIGRATION.read_text(encoding="utf-8"))
    _execute(qt_db, BUNDLE_MIGRATION.read_text(encoding="utf-8"))
    return qt_db


def _policy(dsn):
    configuration = native_evaluator_configuration()
    _execute(dsn, """INSERT INTO trading.qt_source_policies
        (book_id,purpose,enabled,version,producer_id,policy_version,
         evaluator_build,evaluator_sha256,evaluator_bundle_sha256,allowed_override_codes)
        VALUES ('BOOK','evaluation',true,1,'synthetic-publisher','policy-v1',
                %s,%s,%s,'["gross_leverage"]')""", (configuration["expected_build"], configuration["expected_sha256"], configuration["expected_bundle_sha256"]))


def _snapshot(dsn):
    return _execute(dsn, """INSERT INTO trading.qt_evaluation_snapshots
        (book_id,source_day,model_publication_id,producer_id,policy_version,
         source_version,as_of,valid_until,content_digest,payload)
        VALUES ('BOOK',CURRENT_DATE,'10000000-0000-4000-8000-000000000001',
                'synthetic-publisher','policy-v1','source-v1',now(),
                now()+interval '1 minute',repeat('b',64),'{}')
        RETURNING snapshot_id""")[0][0]


def test_governed_tables_start_empty_without_enabled_authority(governed_db):
    for table in ("qt_source_policies", "qt_evaluation_snapshots",
                  "qt_execution_observations", "qt_desk_results"):
        assert _execute(governed_db, f"SELECT count(*) FROM trading.{table}") == [(0,)]


@pytest.mark.parametrize("operation", ["UPDATE", "DELETE", "TRUNCATE"])
def test_source_snapshot_evidence_cannot_be_rewritten(governed_db, operation):
    row_id = _snapshot(governed_db)
    query = {"UPDATE": "UPDATE trading.qt_evaluation_snapshots SET payload='{\"changed\":true}'",
             "DELETE": "DELETE FROM trading.qt_evaluation_snapshots",
             "TRUNCATE": "TRUNCATE trading.qt_evaluation_snapshots"}[operation]
    with pytest.raises(psycopg2.Error):
        _execute(governed_db, query)
    assert _execute(governed_db, "SELECT snapshot_id,payload FROM trading.qt_evaluation_snapshots") == [(row_id, {})]


def test_policy_changes_require_new_version_and_keep_scope_identity(governed_db):
    _policy(governed_db)
    for query in (
        "UPDATE trading.qt_source_policies SET enabled=false",
        "UPDATE trading.qt_source_policies SET version=2,book_id='OTHER'",
        "DELETE FROM trading.qt_source_policies",
        "TRUNCATE trading.qt_source_policies",
    ):
        with pytest.raises(psycopg2.Error):
            _execute(governed_db, query)
    _execute(governed_db, "UPDATE trading.qt_source_policies SET enabled=false,version=2")
    assert _execute(governed_db, "SELECT enabled,version FROM trading.qt_source_policies") == [(False, 2)]


def test_snapshot_scope_fence_uses_same_canonical_book_lock(governed_db):
    blocker = psycopg2.connect(governed_db)
    contender = psycopg2.connect(governed_db)
    try:
        with blocker.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended('algolens:qt-book:BOOK',0))")
        with contender.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout='100ms'")
            with pytest.raises(psycopg2.errors.LockNotAvailable):
                cursor.execute("""INSERT INTO trading.qt_evaluation_snapshots
                    (book_id,source_day,model_publication_id,producer_id,policy_version,
                     source_version,as_of,valid_until,content_digest,payload)
                    VALUES ('BOOK',CURRENT_DATE,'10000000-0000-4000-8000-000000000001',
                      'synthetic-publisher','policy-v1','source-v1',now(),now(),repeat('b',64),'{}')""")
    finally:
        contender.rollback()
        blocker.rollback()
        contender.close()
        blocker.close()
    assert _execute(governed_db, "SELECT count(*) FROM trading.qt_evaluation_snapshots") == [(0,)]


@pytest.mark.parametrize("table", ["qt_execution_observations", "qt_desk_results"])
def test_empty_observation_and_result_tables_still_refuse_truncate(governed_db, table):
    with pytest.raises(psycopg2.Error):
        _execute(governed_db, f"TRUNCATE trading.{table}")
    assert _execute(governed_db, f"SELECT count(*) FROM trading.{table}") == [(0,)]

# Loader coverage uses real SQL in the same owned database and actual ordered
# transaction object. This minimal MODEL table proves reference scoping only;
# A3/E1 separately prove the authoritative publication and provenance chain.
from datetime import datetime, timezone, timedelta
from psycopg2.extras import Json
from algolens.domain.portfolio.qt_workflow_errors import QtWorkflowError
from algolens.infrastructure.portfolio.qt_workflow_repository import QtWorkflowRepository
from algolens.infrastructure.portfolio.qt_evaluation_inputs import load_qt_evaluation_inputs
from tests.test_qt_evaluation_inputs import sample, rehash, MODEL
from tests.integration.test_qt_workflow_postgres import _draft_preview, _decision, DECISION


def _input_records(dsn, *, mutation=None, seed_policy=True):
    policy, snapshot = sample()
    current = datetime.now(timezone.utc)
    snapshot.update(source_day=current.date(), as_of=current-timedelta(seconds=1),
                    valid_until=current+timedelta(minutes=2))
    snapshot['payload']['source_day'] = current.date().isoformat()
    snapshot['payload']['instrument_catalog'][0]['key']['date'] = current.date().isoformat()
    if mutation == 'expired': snapshot.update(as_of=current-timedelta(seconds=30), valid_until=current-timedelta(seconds=2))
    if mutation == 'future': snapshot['as_of'] = current+timedelta(seconds=20)
    if mutation == 'producer': snapshot['producer_id'] = 'untrusted'
    if mutation == 'choice': snapshot['payload']['engine_inputs']['risk_inputs']['quantity_exact'] = '7'
    rehash(snapshot)
    if mutation == 'hash': snapshot['content_digest'] = 'd'*64
    _execute(dsn, 'CREATE TABLE trading.qt_model_seed_publications '
        '(publication_id uuid PRIMARY KEY,portfolio_id text NOT NULL,source_day date NOT NULL)')
    _execute(dsn, 'INSERT INTO trading.qt_model_seed_publications VALUES (%s,%s,%s)',
             (MODEL, 'OTHER' if mutation == 'model_scope' else 'BOOK', current.date()))
    if seed_policy:
        configuration = native_evaluator_configuration()
        _execute(dsn, """INSERT INTO trading.qt_source_policies
            (book_id,purpose,enabled,version,producer_id,policy_version,evaluator_build,
             evaluator_sha256,evaluator_bundle_sha256,allowed_override_codes)
            VALUES ('BOOK','evaluation',true,1,'synthetic','policy-v1',%s,%s,%s,%s)""",
            (configuration["expected_build"], configuration["expected_sha256"], configuration["expected_bundle_sha256"], Json(['gross_leverage'])))
    _insert_input_snapshot(dsn, snapshot)
    return snapshot


def _insert_input_snapshot(dsn, snapshot):
    _execute(dsn, """INSERT INTO trading.qt_evaluation_snapshots
        (book_id,source_day,model_publication_id,producer_id,policy_version,source_version,
         as_of,valid_until,content_digest,payload)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        tuple(snapshot[k] for k in ('book_id','source_day','model_publication_id','producer_id',
            'policy_version','source_version','as_of','valid_until','content_digest'))+(Json(snapshot['payload']),))


def _load_inputs(dsn):
    repository = QtWorkflowRepository(lambda: psycopg2.connect(dsn))
    with repository.transaction('BOOK',101) as tx:
        tx.lock_authorities([101])
        tx.lock_registries([])
        tx.lock_books(['BOOK'])
        day=tx.utc_source_day()
        tx.lock_mutable(source_day=day)
        tx.cursor.execute('SELECT clock_timestamp() AS checked_at')
        checked=tx.cursor.fetchone()['checked_at']
        return load_qt_evaluation_inputs(tx,source_day=day,model_publication_id=MODEL,checked_at=checked)


def test_real_loader_selects_latest_snapshot_and_binds_policy_revision(governed_db):
    snapshot=_input_records(governed_db)
    first=_load_inputs(governed_db)
    snapshot['source_version']='source-v2'
    _insert_input_snapshot(governed_db,snapshot)
    second=_load_inputs(governed_db)
    assert first.snapshot_id < second.snapshot_id
    assert first.content_digest == second.content_digest
    assert first.source_identity_digest != second.source_identity_digest
    _execute(governed_db,'UPDATE trading.qt_source_policies SET version=2')
    third=_load_inputs(governed_db)
    assert second.source_identity_digest != third.source_identity_digest
    _execute(governed_db,'UPDATE trading.qt_source_policies SET version=3,enabled=false')
    with pytest.raises(QtWorkflowError) as caught: _load_inputs(governed_db)
    assert caught.value.code == 'preview_unavailable'


@pytest.mark.parametrize('mutation',['expired','future','producer','choice','hash','model_scope'])
def test_real_loader_refuses_untrusted_or_incomplete_source(governed_db,mutation):
    _input_records(governed_db,mutation=mutation)
    with pytest.raises(QtWorkflowError) as caught: _load_inputs(governed_db)
    assert caught.value.code == 'preview_unavailable'
    assert _execute(governed_db,'SELECT count(*) FROM trading.qt_previews') == [(0,)]


def test_real_loader_requires_enabled_policy_record(governed_db):
    _input_records(governed_db,seed_policy=False)
    with pytest.raises(QtWorkflowError) as caught: _load_inputs(governed_db)
    assert caught.value.code == 'preview_unavailable'


@pytest.mark.parametrize('table',['qt_execution_observations','qt_desk_results'])
@pytest.mark.parametrize('operation',['UPDATE','DELETE'])
def test_actual_observation_and_result_rows_are_immutable(governed_db,table,operation):
    _draft_preview(governed_db)
    with psycopg2.connect(governed_db) as conn:
        with conn.cursor() as cur: _decision(cur,DECISION)
    observation='00000000-0000-4000-8000-000000000044'
    _execute(governed_db,"""INSERT INTO trading.qt_execution_observations
        (observation_id,decision_id,producer_id,policy_version,source_version,as_of,
         valid_until,content_digest,payload)
        VALUES (%s,%s,'synthetic','execution-v1','v1',now(),now(),repeat('a',64),'{}')""",
        (observation,DECISION))
    _execute(governed_db,"""INSERT INTO trading.qt_desk_results
        (decision_id,attempt_id,observation_id,content_digest,payload)
        VALUES (%s,'00000000-0000-4000-8000-000000000055',%s,repeat('b',64),'{}')""",
        (DECISION,observation))
    query=f'UPDATE trading.{table} SET payload=\'{{"changed":true}}\'' if operation=='UPDATE' else f'DELETE FROM trading.{table}'
    with pytest.raises(psycopg2.Error): _execute(governed_db,query)
    assert _execute(governed_db,f'SELECT payload FROM trading.{table}') == [({},)]
