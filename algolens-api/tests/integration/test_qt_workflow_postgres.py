"""A2 physical invariants on the owned, disposable PostgreSQL fixture only."""

from datetime import date
from pathlib import Path

import psycopg2
from psycopg2.errors import UniqueViolation
import pytest

from tests.integration.conftest import claim_schema, require_test_dsn
from algolens.domain.portfolio.qt_workflow_errors import QtWorkflowError
from algolens.infrastructure.db.schema_contract import qt_publication_storage_ready
from algolens.infrastructure.portfolio.qt_workflow_repository import QtWorkflowRepository


MIGRATION = Path(__file__).resolve().parents[2] / "migrations" / "003_qt_decision_workflow.sql"
DRAFT = "00000000-0000-4000-8000-000000000011"
PREVIEW = "00000000-0000-4000-8000-000000000022"
DECISION = "00000000-0000-4000-8000-000000000033"


@pytest.fixture
def qt_db():
    dsn = require_test_dsn()
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            claim_schema(cur)
            cur.execute("CREATE SCHEMA IF NOT EXISTS auth")
            cur.execute("CREATE TABLE IF NOT EXISTS auth.users (id bigint PRIMARY KEY)")
            cur.execute("ALTER TABLE auth.users ADD COLUMN IF NOT EXISTS role text NOT NULL DEFAULT 'general_member'")
            cur.execute("INSERT INTO auth.users(id,role) VALUES (101,'general_member'),(202,'general_member') "
                        "ON CONFLICT (id) DO UPDATE SET role=EXCLUDED.role")
            cur.execute(MIGRATION.read_text(encoding="utf-8"))
        conn.commit()
        yield dsn
    finally:
        conn.close()


def _execute(dsn, query, params=()):
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            if cur.description:
                return cur.fetchall()


def _draft_preview(dsn, draft_id=DRAFT, preview_id=PREVIEW, source_day=date(2026, 9, 25)):
    _execute(
        dsn,
        """INSERT INTO trading.qt_drafts
           (draft_id, book_id, source_day, revision, source_digest,
            provenance_digest, draft_digest, selection_payload, created_by, updated_by)
           VALUES (%s, 'BOOK', %s, 1, 'source', 'provenance', 'draft', '{}', 101, 101)""",
        (draft_id, source_day),
    )
    _execute(
        dsn,
        """INSERT INTO trading.qt_previews
           (preview_id, book_id, source_day, draft_id, draft_revision,
            draft_digest, source_digest, provenance_digest, read_set_digest,
            optimizer_book_digest, selected_book_digest, payload_digest,
            payload, read_set_payload, evaluator_build, policy_version,
            availability, created_by, state)
           VALUES (%s, 'BOOK', %s, %s, 1, 'draft', 'source', 'provenance',
                   'readset', 'optimizer', 'selected', 'payload', '{}', '{}',
                   'build', 'policy', 'ready', 101, 'pending')""",
        (preview_id, source_day, draft_id),
    )


def _decision(cur, decision_id):
    cur.execute(
        """INSERT INTO trading.qt_decisions
           (decision_id, preview_id, book_id, source_day, status,
            provenance_digest, draft_id, draft_revision, selected_book_digest,
            read_set_digest, workflow_capability_version, submitter_grant_version,
            policy_version, payload, created_by)
           VALUES (%s, %s, 'BOOK', %s, 'pending_override', 'provenance', %s, 1,
                   'selected', 'readset', 1, 1, 'policy', '{}', 101)""",
        (decision_id, PREVIEW, date(2026, 9, 25), DRAFT),
    )


def test_migration_starts_without_human_grants_or_mappings(qt_db):
    assert _execute(qt_db, "SELECT count(*) FROM trading.qt_action_grants") == [(0,)]
    assert _execute(qt_db, "SELECT count(*) FROM trading.qt_approver_allowlist") == [(0,)]
    assert _execute(qt_db, "SELECT count(*) FROM trading.qt_workflow_capabilities") == [(0,)]


def test_two_people_cannot_map_to_one_account(qt_db):
    _execute(qt_db, """INSERT INTO trading.qt_approver_allowlist
        (person_id, display_label, user_id, active, mapping_version)
        VALUES ('hemdutt_rao', 'hemdutt rao', 101, true, 1)""")
    with pytest.raises(UniqueViolation):
        _execute(qt_db, """INSERT INTO trading.qt_approver_allowlist
            (person_id, display_label, user_id, active, mapping_version)
            VALUES ('john_riley', 'john riley', 101, true, 1)""")


def test_one_decision_per_preview_rolls_back_entire_transaction(qt_db):
    _draft_preview(qt_db)
    _execute(qt_db, "CREATE TABLE trading.positions (id integer PRIMARY KEY, quantity numeric(20,8))")
    _execute(qt_db, "CREATE TABLE trading.position_overrides (id integer PRIMARY KEY, note text)")
    _execute(qt_db, "INSERT INTO trading.positions VALUES (1, 1.25)")
    _execute(qt_db, "INSERT INTO trading.position_overrides VALUES (1, 'original')")
    positions_before = _execute(qt_db, "SELECT id, quantity FROM trading.positions ORDER BY id")
    audit_before = _execute(qt_db, "SELECT id, note FROM trading.position_overrides ORDER BY id")
    with pytest.raises(UniqueViolation):
        with psycopg2.connect(qt_db) as conn:
            with conn.cursor() as cur:
                _decision(cur, DECISION)
                _decision(cur, "00000000-0000-4000-8000-000000000034")
    assert _execute(qt_db, "SELECT count(*) FROM trading.qt_decisions") == [(0,)]
    assert _execute(qt_db, "SELECT id, quantity FROM trading.positions ORDER BY id") == positions_before
    assert _execute(qt_db, "SELECT id, note FROM trading.position_overrides ORDER BY id") == audit_before


def test_request_insert_rejects_decision_from_another_book(qt_db):
    _draft_preview(qt_db)
    _execute(qt_db, "INSERT INTO trading.qt_workflow_capabilities (book_id, enabled, version) VALUES ('BOOK', true, 1)")
    with psycopg2.connect(qt_db) as conn:
        with conn.cursor() as cur:
            _decision(cur, DECISION)
    repository = QtWorkflowRepository(lambda: psycopg2.connect(qt_db))
    with pytest.raises(QtWorkflowError):
        with repository.transaction("OTHER", 101) as tx:
            tx.lock_authorities([101])
            tx.lock_registries([])
            tx.lock_books(["OTHER"])
            tx.lock_mutable()
            tx.insert_override_request({
                "request_id": "00000000-0000-4000-8000-000000000044",
                "decision_id": DECISION,
                "eligibility_version": 1,
                "required_approvals": 2,
            })
    assert _execute(qt_db, "SELECT count(*) FROM trading.qt_override_requests") == [(0,)]


def test_approval_insert_rejects_request_from_another_book(qt_db):
    _draft_preview(qt_db)
    with psycopg2.connect(qt_db) as conn:
        with conn.cursor() as cur:
            _decision(cur, DECISION)
            cur.execute("""INSERT INTO trading.qt_override_requests
                (request_id, decision_id, eligibility_version, required_approvals)
                VALUES ('00000000-0000-4000-8000-000000000044', %s, 1, 2)""", (DECISION,))
            cur.execute("""INSERT INTO trading.qt_approver_allowlist
                (person_id, display_label, user_id, active, mapping_version)
                VALUES ('john_riley', 'john riley', 202, true, 1)""")
    repository = QtWorkflowRepository(lambda: psycopg2.connect(qt_db))
    with pytest.raises(QtWorkflowError):
        with repository.transaction("OTHER", 202) as tx:
            tx.lock_authorities([202])
            tx.lock_registries([])
            tx.lock_books(["OTHER"])
            tx.lock_mutable()
            tx.insert_approval({
                "approval_id": "00000000-0000-4000-8000-000000000066",
                "request_id": "00000000-0000-4000-8000-000000000044",
                "person_id": "john_riley",
                "user_id": 202,
                "mapping_version": 1,
                "grant_version": 1,
            })
    assert _execute(qt_db, "SELECT count(*) FROM trading.qt_override_approvals") == [(0,)]


def test_mutable_lock_targets_head_and_preview_without_locking_history(qt_db):
    _draft_preview(qt_db)
    historical_preview = "00000000-0000-4000-8000-000000000077"
    historical_draft = "00000000-0000-4000-8000-000000000078"
    _draft_preview(qt_db, historical_draft, historical_preview, date(2026, 9, 24))
    _execute(qt_db, """INSERT INTO trading.qt_draft_heads
        (book_id, source_day, draft_id, revision) VALUES ('BOOK', %s, %s, 1)""",
        (date(2026, 9, 25), DRAFT),
    )
    repository = QtWorkflowRepository(lambda: psycopg2.connect(qt_db))
    with repository.transaction("BOOK", 101) as tx:
        tx.lock_authorities([101])
        tx.lock_registries([])
        tx.lock_books(["BOOK"])
        tx.lock_mutable(source_day=date(2026, 9, 25), preview_ids=(PREVIEW,))
        assert _execute(qt_db, """SELECT preview_id FROM trading.qt_previews
            WHERE preview_id = %s FOR UPDATE NOWAIT""", (historical_preview,)) == [(historical_preview,)]
        with pytest.raises(psycopg2.errors.LockNotAvailable):
            _execute(qt_db, """SELECT preview_id FROM trading.qt_previews
                WHERE preview_id = %s FOR UPDATE NOWAIT""", (PREVIEW,))
        with pytest.raises(psycopg2.errors.LockNotAvailable):
            _execute(qt_db, """SELECT draft_id FROM trading.qt_draft_heads
                WHERE book_id = 'BOOK' AND source_day = %s FOR UPDATE NOWAIT""",
                (date(2026, 9, 25),))


def test_immutable_draft_and_preview_payload_cannot_change(qt_db):
    _draft_preview(qt_db)
    with pytest.raises(psycopg2.Error):
        _execute(qt_db, "UPDATE trading.qt_drafts SET selection_payload = '{\"changed\":true}'")
    with pytest.raises(psycopg2.Error):
        _execute(qt_db, "UPDATE trading.qt_previews SET payload_digest = 'changed'")
    assert _execute(qt_db, "SELECT draft_digest FROM trading.qt_drafts") == [("draft",)]


def test_repository_transaction_rolls_back_on_failure(qt_db):
    repository = QtWorkflowRepository(lambda: psycopg2.connect(qt_db))
    with pytest.raises(RuntimeError):
        with repository.transaction("BOOK", 101) as tx:
            tx.lock_authorities([101])
            tx.lock_registries([])
            tx.lock_books(["BOOK"])
            tx.lock_mutable()
            tx.cursor.execute("""INSERT INTO trading.qt_workflow_capabilities
                (book_id, enabled, version) VALUES ('BOOK', true, 1)""")
            raise RuntimeError("abort")
    assert _execute(qt_db, "SELECT count(*) FROM trading.qt_workflow_capabilities") == [(0,)]


def test_repository_transaction_commits_once_at_boundary(qt_db):
    repository = QtWorkflowRepository(lambda: psycopg2.connect(qt_db))
    with repository.transaction("BOOK", 101) as tx:
        tx.lock_authorities([101])
        tx.lock_registries([])
        tx.lock_books(["BOOK"])
        tx.lock_mutable()
        tx.cursor.execute("""INSERT INTO trading.qt_workflow_capabilities
            (book_id, enabled, version) VALUES ('BOOK', false, 1)""")
    assert _execute(qt_db, "SELECT enabled FROM trading.qt_workflow_capabilities") == [(False,)]


def test_decision_must_reference_the_previews_exact_draft_revision(qt_db):
    _draft_preview(qt_db)
    alternate_draft = "00000000-0000-4000-8000-000000000012"
    _execute(
        qt_db,
        """INSERT INTO trading.qt_drafts
           (draft_id, book_id, source_day, revision, source_digest,
            provenance_digest, draft_digest, selection_payload, created_by, updated_by)
           VALUES (%s, 'BOOK', %s, 2, 'source', 'provenance', 'alternate', '{}', 101, 101)""",
        (alternate_draft, date(2026, 9, 25)),
    )
    with pytest.raises(psycopg2.IntegrityError):
        _execute(
            qt_db,
            """INSERT INTO trading.qt_decisions
               (decision_id, preview_id, book_id, source_day, status,
                provenance_digest, draft_id, draft_revision, selected_book_digest,
                read_set_digest, workflow_capability_version, submitter_grant_version,
                policy_version, payload, created_by)
               VALUES (%s, %s, 'BOOK', %s, 'confirmed_decision', 'provenance', %s, 2,
                       'selected', 'readset', 1, 1, 'policy', '{}', 101)""",
            (DECISION, PREVIEW, date(2026, 9, 25), alternate_draft),
        )


def test_idempotency_response_cannot_be_rewritten(qt_db):
    _execute(qt_db, """INSERT INTO trading.qt_idempotency
        (actor_id, book_id, operation, scope_id, idempotency_key, request_digest, response_payload)
        VALUES (101, 'BOOK', 'create_preview', 'scope',
                '00000000-0000-4000-8000-000000000055', 'digest', '{\"preview_id\":\"first\"}')""")
    with pytest.raises(psycopg2.Error):
        _execute(qt_db, """UPDATE trading.qt_idempotency
            SET response_payload = '{\"preview_id\":\"second\"}'""")


def test_real_catalog_precision_probe_rejects_old_and_accepts_exact_storage(qt_db):
    with psycopg2.connect(qt_db) as conn:
        with conn.cursor() as cur:
            cur.execute("""CREATE TABLE trading.positions (
                quantity numeric(20,6), average_price numeric(20,6))""")
            assert qt_publication_storage_ready(cur) is False
            cur.execute("""ALTER TABLE trading.positions
                ALTER COLUMN quantity TYPE numeric(20,8),
                ALTER COLUMN average_price TYPE numeric(20,8)""")
            assert qt_publication_storage_ready(cur) is True


_IMMUTABLE_EVIDENCE = (
    "qt_drafts",
    "qt_previews",
    "qt_decisions",
    "qt_override_requests",
    "qt_override_approvals",
    "qt_idempotency",
)


def _populate_immutable_evidence(dsn):
    _draft_preview(dsn)
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            _decision(cur, DECISION)
            cur.execute("""INSERT INTO trading.qt_override_requests
                (request_id, decision_id, eligibility_version, required_approvals)
                VALUES ('00000000-0000-4000-8000-000000000044', %s, 1, 2)""", (DECISION,))
            cur.execute("""INSERT INTO trading.qt_approver_allowlist
                (person_id, display_label, user_id, active, mapping_version)
                VALUES ('john_riley', 'john riley', 202, true, 1)""")
            cur.execute("""INSERT INTO trading.qt_override_approvals
                (approval_id, request_id, person_id, user_id, mapping_version, grant_version)
                VALUES ('00000000-0000-4000-8000-000000000066',
                        '00000000-0000-4000-8000-000000000044', 'john_riley', 202, 1, 1)""")
            cur.execute("""INSERT INTO trading.qt_idempotency
                (actor_id, book_id, operation, scope_id, idempotency_key, request_digest, response_payload)
                VALUES (101, 'BOOK', 'confirm_preview', 'scope',
                        '00000000-0000-4000-8000-000000000055', 'digest', '{}')""")


@pytest.mark.parametrize("table", _IMMUTABLE_EVIDENCE)
def test_truncate_cascade_cannot_erase_immutable_evidence(qt_db, table):
    _populate_immutable_evidence(qt_db)
    before = {name: _execute(qt_db, f"SELECT count(*) FROM trading.{name}")[0][0]
              for name in _IMMUTABLE_EVIDENCE}
    assert all(count == 1 for count in before.values())
    with pytest.raises(psycopg2.Error):
        _execute(qt_db, f"TRUNCATE trading.{table} CASCADE")
    assert {name: _execute(qt_db, f"SELECT count(*) FROM trading.{name}")[0][0]
            for name in _IMMUTABLE_EVIDENCE} == before


def test_truncate_cascade_from_auth_parent_cannot_erase_immutable_evidence(qt_db):
    before_accounts = _execute(qt_db, "SELECT id,role FROM auth.users ORDER BY id")
    _populate_immutable_evidence(qt_db)
    before = _execute(qt_db, "SELECT count(*) FROM trading.qt_drafts")
    with pytest.raises(psycopg2.Error):
        _execute(qt_db, "TRUNCATE auth.users CASCADE")
    assert _execute(qt_db, "SELECT count(*) FROM trading.qt_drafts") == before
    assert _execute(qt_db, "SELECT id,role FROM auth.users ORDER BY id") == before_accounts
