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
                    email text NOT NULL UNIQUE,
                    password_hash text,
                    role text NOT NULL,
                    first_name text,
                    last_name text,
                    created_at timestamptz NOT NULL DEFAULT now()
                )
            """)
            cursor.execute("""
                INSERT INTO auth.users VALUES
                    (101, 'john.riley@ufl.edu', 'john-hash', 'general_member', 'John', 'Riley', now()),
                    (202, 'raohemdutt@ufl.edu', 'hemdutt-hash', 'exec_board', 'Hemdutt', 'Rao', now()),
                    (303, 'robbins.a@ufl.edu', 'xander-hash', 'general_member', 'Alexander', 'Robbins', now()),
                    (404, 'dominickdupuy@ufl.edu', 'ufl-hash', 'general_member', 'Dominick', 'Dupuy', now()),
                    (405, 'domdd305@gmail.com', 'gmail-hash', 'general_member', 'Dominick', 'Dupuy', now())
            """)
            cursor.execute("""
                CREATE TABLE auth.identity_audit_fixture (
                    event_id bigint PRIMARY KEY,
                    actor_id bigint NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
                    detail text NOT NULL
                )
            """)
            cursor.execute("""
                INSERT INTO auth.identity_audit_fixture VALUES
                    (1, 405, 'historical personal-account action')
            """)
            cursor.execute((MIGRATIONS / "003_qt_decision_workflow.sql").read_text(encoding="utf-8"))
            cursor.execute("ALTER TABLE trading.qt_approver_allowlist DROP CONSTRAINT qt_approver_identity")
            cursor.execute("""
                INSERT INTO trading.qt_action_grants VALUES
                    (101, 'qt_approve', true, 1, now()),
                    (303, 'qt_submit', true, 1, now()),
                    (405, 'qt_approve', true, 1, now())
            """)
            cursor.execute("""
                INSERT INTO trading.qt_approver_allowlist VALUES
                    ('eric_shwartz', 'eric shwartz', 101, true, 1, now()),
                    ('dominick_dupuoy', 'dominick dupuoy', 405, true, 1, now())
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
        ('dominick_dupuoy', 405, False, 2),
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
        (405, 'qt_approve', False, 2),
    ]
    assert rows(approver_db, """
        SELECT u.email, u.role
        FROM auth.users u
        WHERE lower(btrim(u.email)) IN (
            'john.riley@ufl.edu', 'raohemdutt@ufl.edu', 'robbins.a@ufl.edu',
            'dominickdupuy@ufl.edu', 'domdd305@gmail.com'
        )
        ORDER BY u.id
    """) == [
        ('john.riley@ufl.edu', 'general_member'),
        ('raohemdutt@ufl.edu', 'exec_board'),
        ('robbins.a@ufl.edu', 'general_member'),
        ('dominickdupuy@ufl.edu', 'exec_board'),
        ('domdd305@gmail.com', 'general_member'),
    ]
    assert rows(approver_db, """
        SELECT retired.email, replacement.email, r.reason
        FROM auth.account_retirements r
        JOIN auth.users retired ON retired.id = r.user_id
        JOIN auth.users replacement ON replacement.id = r.replacement_user_id
    """) == [(
        'domdd305@gmail.com',
        'dominickdupuy@ufl.edu',
        'duplicate personal identity retired in favor of verified UFL account',
    )]
    assert rows(approver_db, """
        SELECT actor_id, detail FROM auth.identity_audit_fixture
    """) == [(405, 'historical personal-account action')]
    retirement_before_replay = rows(approver_db, """
        SELECT user_id, replacement_user_id, reason, retired_by_migration, retired_at
        FROM auth.account_retirements
    """)
    with pytest.raises(psycopg2.errors.RaiseException, match='retired account'):
        rows(approver_db, """
            UPDATE trading.qt_action_grants
            SET active = true WHERE user_id = 405 AND capability = 'qt_approve'
        """)
    with pytest.raises(psycopg2.errors.RaiseException, match='retired account'):
        rows(approver_db, """
            UPDATE trading.qt_approver_allowlist
            SET active = true WHERE person_id = 'dominick_dupuoy'
        """)
    with pytest.raises(psycopg2.errors.RaiseException, match='immutable'):
        rows(approver_db, "DELETE FROM auth.account_retirements WHERE user_id = 405")
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
    assert rows(approver_db, """
        SELECT user_id, replacement_user_id, reason, retired_by_migration, retired_at
        FROM auth.account_retirements
    """) == retirement_before_replay


def test_migration_refuses_an_ambiguous_named_identity(approver_db):
    rows(approver_db, """
        INSERT INTO auth.users VALUES
            (505, 'RAOHEMDUTT@UFL.EDU ', NULL, 'exec_board', 'Hemdutt', 'Rao', now())
    """)
    migration = (MIGRATIONS / "009_hemdutt_qt_approver.sql").read_text(encoding="utf-8")
    with pytest.raises(psycopg2.errors.RaiseException, match='exactly one raohemdutt@ufl.edu account'):
        rows(approver_db, migration)


def test_migration_refuses_a_missing_named_identity(approver_db):
    rows(approver_db, "DELETE FROM trading.qt_action_grants WHERE user_id = 303; DELETE FROM auth.users WHERE id = 303")
    migration = (MIGRATIONS / "009_hemdutt_qt_approver.sql").read_text(encoding="utf-8")
    with pytest.raises(psycopg2.errors.RaiseException, match='exactly one robbins.a@ufl.edu account'):
        rows(approver_db, migration)


def test_migration_refuses_wrong_exact_role_or_missing_personal_identity(approver_db):
    migration = (MIGRATIONS / "009_hemdutt_qt_approver.sql").read_text(encoding="utf-8")
    rows(approver_db, "UPDATE auth.users SET role = 'admin' WHERE id = 404")
    with pytest.raises(psycopg2.errors.RaiseException, match='must start as general_member or exec_board'):
        rows(approver_db, migration)

    rows(approver_db, "UPDATE auth.users SET role = 'general_member' WHERE id = 404")
    rows(approver_db, "DELETE FROM trading.qt_action_grants WHERE user_id = 405")
    rows(approver_db, "DELETE FROM trading.qt_approver_allowlist WHERE user_id = 405")
    rows(approver_db, "DELETE FROM auth.identity_audit_fixture WHERE actor_id = 405")
    rows(approver_db, "DELETE FROM auth.users WHERE id = 405")
    with pytest.raises(psycopg2.errors.RaiseException, match='exactly one domdd305@gmail.com account'):
        rows(approver_db, migration)
