"""Synthetic PostgreSQL regressions for readiness identity and request isolation."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import shutil
from types import SimpleNamespace
from unittest.mock import patch

import psycopg2
from psycopg2.extras import RealDictCursor
from werkzeug.security import generate_password_hash

from deployment.qt_rehearsal.cluster import RehearsalCluster
from deployment.qt_rehearsal.harness import validate_rehearsal_root
from deployment.qt_rehearsal.postgres_toolchain import resolve_postgres_bin, PostgresToolchainError

BACKEND = Path(__file__).resolve().parents[3] / 'algolens-api'
sys.path.insert(0, str(BACKEND))
from algolens.infrastructure.config.production_readiness import _CAPABILITY_READINESS_SQL
from algolens.infrastructure.config.app_factory import create_app
from algolens.infrastructure.db.postgres import get_db_connection

try:
    PG_BIN = resolve_postgres_bin()
except PostgresToolchainError:
    PG_BIN = None


@unittest.skipUnless(PG_BIN, 'private PostgreSQL 16 toolchain required')
class ReadinessRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix='algolens-qt-rehearsal.', dir='/dev/shm'))
        cls.cluster = RehearsalCluster(cls.root, PG_BIN)
        cls.initialized = False
        cls.addClassCleanup(cls.cleanup_cluster)
        cls.cluster.initialize()
        cls.initialized = True
        cls.cluster.apply_sql('qt_rehearsal_migrated',
                              'CREATE ROLE qt_algolens_api LOGIN NOINHERIT NOSUPERUSER;')

    @classmethod
    def cleanup_cluster(cls):
        if cls.initialized:
            cls.cluster.cleanup()
        else:
            status = subprocess.run([str(PG_BIN/'pg_ctl'), '-D', str(cls.root/'data'), 'status'],
                                    capture_output=True, timeout=10)
            if status.returncode != 3:
                raise AssertionError('failed fixture may still own a server; refusing deletion')
            validate_rehearsal_root(cls.root)
            if list((cls.root/'socket').glob('.s.PGSQL.*')):
                raise AssertionError('failed fixture retains socket; refusing deletion')
            shutil.rmtree(cls.root)
        assert not cls.root.exists()

    def setUp(self):
        log_directory = tempfile.TemporaryDirectory(prefix='qt-readiness-test-logs-')
        self.addCleanup(log_directory.cleanup)
        self.addCleanup(os.chdir, Path.cwd())
        os.chdir(log_directory.name)
        clean = {key: value for key, value in os.environ.items() if not key.startswith('PG')}
        clean.update(FLASK_ENV='rehearsal', FLASK_DEBUG='false', DEV_MODE='0',
                     PYTHON_DOTENV_DISABLED='1', CORS_ORIGINS='https://example.invalid',
                     JWT_SECRET_KEY='synthetic-private-rehearsal-key-longer-than-32',
                     APP_RELEASE_SHA='a'*40, QT_EMAIL_DELIVERY_ENABLED='false',
                     DB_HOST=str(self.root/'socket'), DB_NAME='qt_rehearsal_migrated',
                     DB_USER='qt_algolens_api', QT_EVALUATOR_BUNDLE_DIR='/app/qt-evaluator-bundle',
                     QT_RUNTIME_CONFIG_MANIFEST='/app/runtime-control/manifest.json',
                     QT_RUNTIME_CONFIG_SHA256='0'*64,
                     QT_RELEASE_ARTIFACT_MANIFEST=str(BACKEND/'tests/fixtures/production_readiness/release-artifacts.v1.placeholder.json'),
                     QT_DATABASE_IDENTITY_MANIFEST=str(BACKEND/'tests/fixtures/production_readiness/database-identity.v1.placeholder.json'))
        clean.pop('DB_PASSWORD', None)
        self.environment = patch.dict(os.environ, clean, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.admin = psycopg2.connect(host=str(self.root/'socket'), dbname='qt_rehearsal_migrated',
                                     user='qt_rehearsal_admin', cursor_factory=RealDictCursor)
        self.admin.autocommit = True
        self.addCleanup(self.admin.close)
        self.sql('''
            DROP SCHEMA IF EXISTS auth CASCADE; DROP SCHEMA IF EXISTS trading CASCADE;
            CREATE SCHEMA auth; CREATE SCHEMA trading;
            CREATE TABLE auth.users(id bigint PRIMARY KEY, email text NOT NULL,
                                    role text NOT NULL, password_hash text);
            CREATE TABLE auth.account_retirements(user_id bigint PRIMARY KEY, replacement_user_id bigint NOT NULL);
            CREATE TABLE trading.qt_action_grants(user_id bigint, capability text, active boolean);
            CREATE TABLE trading.qt_approver_allowlist(user_id bigint, person_id text, active boolean);
            CREATE TABLE trading.qt_override_approvals(id bigint);
            CREATE TABLE trading.qt_previews(preview_id uuid, book_id text, source_day date);
            INSERT INTO trading.qt_previews VALUES
              ('11111111-1111-4111-8111-111111111111','CONSERVATIVE_PORTFOLIO','2026-10-05');
            CREATE FUNCTION trading.qt_reject_submitter_approval() RETURNS trigger LANGUAGE plpgsql AS
              $$ BEGIN RETURN NEW; END $$;
            CREATE TRIGGER qt_approvals_no_submitter BEFORE INSERT ON trading.qt_override_approvals
              FOR EACH ROW EXECUTE FUNCTION trading.qt_reject_submitter_approval();
            INSERT INTO auth.users VALUES
              (101,'john.riley@ufl.edu','general_member',NULL),
              (202,'raohemdutt@ufl.edu','exec_board',NULL),
              (303,'robbins.a@ufl.edu','general_member',NULL),
              (404,'dominickdupuy@ufl.edu','exec_board',NULL),
              (405,'domdd305@gmail.com','general_member',NULL);
            INSERT INTO auth.account_retirements VALUES(405,404);
            INSERT INTO trading.qt_action_grants VALUES
              (101,'qt_submit',true),(202,'qt_approve',true),(303,'qt_approve',true),(404,'qt_approve',true);
            INSERT INTO trading.qt_approver_allowlist VALUES
              (202,'hemdutt_rao',true),(303,'xander_robbins',true),(404,'dominick_dupuy',true);
            GRANT USAGE ON SCHEMA auth,trading TO qt_algolens_api;
            GRANT SELECT ON ALL TABLES IN SCHEMA auth,trading TO qt_algolens_api;
        ''')
        self.sql('UPDATE auth.users SET password_hash=%s WHERE id=101',
                 (generate_password_hash('SyntheticPass123!'),))

    def sql(self, query, parameters=None):
        with self.admin.cursor() as cursor:
            cursor.execute(query, parameters)
            return cursor.fetchall() if cursor.description else []

    def authority_ready(self):
        return self.sql(_CAPABILITY_READINESS_SQL)[0]['launch_authority_ready']

    def add_configuration_grants(self):
        # Match the grant key and capability vocabulary after migration 011.
        # Duplicate grant rows must be rejected by PostgreSQL, not invented by
        # the readiness fixture to exercise an impossible production state.
        self.sql("""
            ALTER TABLE trading.qt_action_grants ADD PRIMARY KEY (user_id, capability);
            ALTER TABLE trading.qt_action_grants ADD CHECK
              (capability IN ('qt_submit','qt_approve','config_submit','config_approve'));
            INSERT INTO trading.qt_action_grants VALUES
              (303,'config_submit',true),(202,'config_approve',true);
        """)

    def test_configuration_grants_coexist_with_exact_qt_authority(self):
        self.assertTrue(self.authority_ready())
        self.add_configuration_grants()
        self.assertTrue(self.authority_ready())

    def test_configuration_grants_do_not_hide_invalid_qt_authority(self):
        self.add_configuration_grants()
        self.assertTrue(self.authority_ready())
        mutations = [
            "DELETE FROM trading.qt_action_grants WHERE user_id=202 AND capability='qt_approve'",
            "INSERT INTO trading.qt_action_grants VALUES(202,'qt_submit',true)",
            # An alias can have its own unique grant key, but must not replace
            # the canonical user's grant or evade exact identity resolution.
            "INSERT INTO auth.users VALUES(606,' RAOHEMDUTT@UFL.EDU ','exec_board',NULL); "
            "UPDATE trading.qt_action_grants SET user_id=606 "
            "WHERE user_id=202 AND capability='qt_approve'",
            "UPDATE auth.users SET role='admin' WHERE id=202",
            "DELETE FROM trading.qt_approver_allowlist WHERE user_id=202",
            "INSERT INTO auth.account_retirements VALUES(202,303)",
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.sql('BEGIN')
                try:
                    self.sql(mutation)
                    self.assertFalse(self.authority_ready())
                finally:
                    self.sql('ROLLBACK')
                self.assertTrue(self.authority_ready())

    def test_duplicate_qt_grant_with_configuration_grants_is_rejected_by_schema(self):
        self.add_configuration_grants()
        self.sql('BEGIN')
        try:
            with self.assertRaises(psycopg2.errors.UniqueViolation):
                self.sql("INSERT INTO trading.qt_action_grants VALUES(202,'qt_approve',true)")
        finally:
            self.sql('ROLLBACK')
        self.assertTrue(self.authority_ready())

    def test_duplicate_unretired_email_with_different_role_is_not_ready(self):
        self.assertTrue(self.authority_ready())
        self.sql("INSERT INTO auth.users VALUES(606,' JOHN.RILEY@UFL.EDU ','exec_board',NULL)")
        self.assertFalse(self.authority_ready())

    def test_retired_lookalike_cannot_receive_expected_identity_grant(self):
        self.sql("INSERT INTO auth.users VALUES(606,' JOHN.RILEY@UFL.EDU ','general_member',NULL)")
        self.sql('INSERT INTO auth.account_retirements VALUES(606,101)')
        self.sql('UPDATE trading.qt_action_grants SET user_id=606 WHERE user_id=101')
        self.assertFalse(self.authority_ready())

    def test_duplicate_grant_cannot_replace_a_missing_expected_grant(self):
        self.sql('DELETE FROM trading.qt_action_grants WHERE user_id=202')
        self.sql("INSERT INTO trading.qt_action_grants VALUES(101,'qt_submit',true)")
        self.assertFalse(self.authority_ready())

    def test_authority_rejects_missing_extra_wrong_role_and_duplicate_mappings(self):
        mutations = [
            "DELETE FROM trading.qt_action_grants WHERE user_id=202",
            "INSERT INTO trading.qt_action_grants VALUES(202,'qt_submit',true)",
            "UPDATE auth.users SET role='admin' WHERE id=202",
            "DELETE FROM trading.qt_approver_allowlist WHERE user_id=202; "
            "INSERT INTO trading.qt_approver_allowlist VALUES(303,'xander_robbins',true)",
            "UPDATE trading.qt_approver_allowlist SET user_id=101 WHERE user_id=202",
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.sql('BEGIN')
                try:
                    self.sql(mutation)
                    self.assertFalse(self.authority_ready())
                finally:
                    self.sql('ROLLBACK')

    def test_retired_same_email_history_without_authority_remains_allowed(self):
        self.sql("INSERT INTO auth.users VALUES(606,' JOHN.RILEY@UFL.EDU ','exec_board',NULL)")
        self.sql('INSERT INTO auth.account_retirements VALUES(606,101)')
        self.assertTrue(self.authority_ready())

    def test_authenticated_route_uses_bound_socket_without_database_password(self):
        app = create_app(rehearsal_root=self.root)
        with app.test_client() as client:
            response = client.post('/auth/login', base_url='https://example.invalid',
                                   json={'email':'john.riley@ufl.edu', 'password':'SyntheticPass123!'})
            self.assertEqual(response.status_code, 200, response.get_json())
            response = client.get('/auth/verify', base_url='https://example.invalid')
            self.assertEqual(response.status_code, 200, response.get_json())
            self.assertIn('edit_qt_book', response.get_json()['user']['capabilities'])
        with app.app_context():
            connection = get_db_connection()
            try:
                with connection.cursor() as cursor:
                    cursor.execute('SELECT current_database() AS db, current_user AS role, inet_server_addr() AS address')
                    self.assertEqual(cursor.fetchone(), {'db':'qt_rehearsal_migrated', 'role':'qt_algolens_api', 'address':None})
            finally:
                connection.close()
            from algolens.infrastructure.portfolio.qt_workflow_repository import QtWorkflowRepository
            with patch.dict(os.environ, {'DB_HOST':'/tmp/untrusted', 'DB_NAME':'untrusted', 'DB_USER':'untrusted'}):
                row = QtWorkflowRepository().preview_routing('11111111-1111-4111-8111-111111111111')
                self.assertEqual(row['book_id'], 'CONSERVATIVE_PORTFOLIO')

    def test_hostile_libpq_environment_is_refused_before_connecting(self):
        app = create_app(rehearsal_root=self.root)
        for name, value in [('PGHOSTADDR','192.0.2.1'), ('PGSERVICE','production'),
                            ('PGOPTIONS','-c search_path=public')]:
            with self.subTest(name=name), app.app_context(), patch.dict(os.environ, {name:value}):
                with patch('psycopg2.connect', side_effect=AssertionError('unexpected connection attempt')), \
                     self.assertRaisesRegex(ValueError, 'rehearsal_connection_environment_invalid'):
                    get_db_connection()

    def test_unbound_rehearsal_connection_cannot_fall_back_to_environment(self):
        with self.assertRaisesRegex(ValueError, 'rehearsal_connection_context_required'):
            get_db_connection()

    def test_readiness_connector_refuses_the_same_hostile_libpq_environment(self):
        from algolens.infrastructure.config.production_readiness import _rehearsal_connection
        with patch.dict(os.environ, {'PGSERVICE':'untrusted-service'}):
            with self.assertRaisesRegex(ValueError, 'rehearsal_connection_environment_invalid'):
                _rehearsal_connection(SimpleNamespace(rehearsal_root=self.root))


if __name__ == '__main__':
    unittest.main()
