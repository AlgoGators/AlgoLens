"""Migration 009 resolves named production identities and is rerunnable."""

from pathlib import Path

import psycopg2
import pytest

from tests.integration.conftest import claim_schema, require_test_dsn


MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"


@pytest.fixture
def approver_db():
    dsn = require_test_dsn()
    with psycopg2.connect(dsn) as connection:
        with connection.cursor() as cursor:
            claim_schema(cursor)
            cursor.execute("CREATE SCHEMA IF NOT EXISTS auth")
            cursor.execute("DROP TABLE IF EXISTS auth.users CASCADE")
            cursor.execute("""
                CREATE TABLE auth.users (
                    id bigint PRIMARY KEY,
                    role text NOT NULL,
                    first_name text,
                    last_name text
                )
            """)
            cursor.execute("""
                INSERT INTO auth.users VALUES
                    (101, 'general_member', 'John', 'Riley'),
                    (202, 'exec_board', 'Hemdutt', 'Rao'),
                    (303, 'general_member', 'Xander', 'Robbins'),
                    (404, 'general_member', 'Dominick', 'Dupuy')
            """)
            cursor.execute((MIGRATIONS / "003_qt_decision_workflow.sql").read_text(encoding="utf-8"))
            cursor.execute("ALTER TABLE trading.qt_approver_allowlist DROP CONSTRAINT qt_approver_identity")
            cursor.execute("""
                INSERT INTO trading.qt_action_grants VALUES
                    (101, 'qt_approve', true, 1, now()),
                    (303, 'qt_submit', true, 1, now()),
                    (404, 'qt_approve', true, 1, now())
            """)
            cursor.execute("""
                INSERT INTO trading.qt_approver_allowlist VALUES
                    ('eric_shwartz', 'eric shwartz', 101, true, 1, now()),
                    ('dominick_dupuoy', 'dominick dupuoy', 404, true, 1, now())
            """)
    yield dsn


def rows(dsn, sql):
    with psycopg2.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql)
            return cursor.fetchall() if cursor.description else []


def test_migration_establishes_exclusive_submitter_and_three_approvers_without_deleting_history(approver_db):
    migration = (MIGRATIONS / "009_hemdutt_qt_approver.sql").read_text(encoding="utf-8")
    rows(approver_db, migration)
    expected_mappings = [
        ('dominick_dupuoy', 404, False, 2),
        ('dominick_dupuy', 404, True, 1),
        ('eric_shwartz', 101, False, 2),
        ('hemdutt_rao', 202, True, 1),
        ('xander_robbins', 303, True, 1),
    ]
    assert rows(approver_db, """
        SELECT person_id, user_id, active, mapping_version
        FROM trading.qt_approver_allowlist ORDER BY person_id
    """) == expected_mappings
    assert rows(approver_db, """
        SELECT user_id, capability, active, version FROM trading.qt_action_grants
        ORDER BY user_id, capability
    """) == [
        (101, 'qt_approve', False, 2), (101, 'qt_submit', True, 1),
        (202, 'qt_approve', True, 1),
        (303, 'qt_approve', True, 1), (303, 'qt_submit', False, 2),
        (404, 'qt_approve', True, 1),
    ]
    with pytest.raises(psycopg2.errors.CheckViolation):
        rows(approver_db, """
            UPDATE trading.qt_approver_allowlist
            SET active = true WHERE person_id = 'eric_shwartz'
        """)

    # Rerunning is a no-op for versions and retains every history row.
    rows(approver_db, migration)
    assert rows(approver_db, """
        SELECT person_id, user_id, active, mapping_version
        FROM trading.qt_approver_allowlist ORDER BY person_id
    """) == expected_mappings


def test_migration_refuses_an_ambiguous_named_identity(approver_db):
    rows(approver_db, """
        INSERT INTO auth.users VALUES (505, 'exec_board', 'Hemdutt', 'Rao')
    """)
    migration = (MIGRATIONS / "009_hemdutt_qt_approver.sql").read_text(encoding="utf-8")
    with pytest.raises(psycopg2.errors.RaiseException, match='exactly one Hemdutt Rao account'):
        rows(approver_db, migration)


def test_migration_refuses_a_missing_named_identity(approver_db):
    rows(approver_db, "DELETE FROM trading.qt_action_grants WHERE user_id = 303; DELETE FROM auth.users WHERE id = 303")
    migration = (MIGRATIONS / "009_hemdutt_qt_approver.sql").read_text(encoding="utf-8")
    with pytest.raises(psycopg2.errors.RaiseException, match='exactly one Xander Robbins account'):
        rows(approver_db, migration)
