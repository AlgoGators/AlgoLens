import hashlib
import gc
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import unittest
import warnings

from deployment.qt_rehearsal.cluster import RehearsalCluster
from deployment.qt_rehearsal.harness import SafetyError, load_manifest, load_role_contract
from deployment.qt_rehearsal.postgres_toolchain import PostgresToolchainError, resolve_postgres_bin


try:
    PG_BIN = resolve_postgres_bin()
except PostgresToolchainError:
    PG_BIN = None


@unittest.skipUnless(PG_BIN is not None, "PostgreSQL 16 toolchain unavailable via QT_REHEARSAL_PG_BIN or PATH")
class PostgresIntegrationTests(unittest.TestCase):
    def setUp(self):
        assert PG_BIN is not None
        self.root = Path(tempfile.mkdtemp(prefix="algolens-qt-rehearsal.", dir="/dev/shm"))
        self.root.chmod(0o700)
        self.cluster = RehearsalCluster(self.root, PG_BIN)

    def tearDown(self):
        if self.root.exists():
            try:
                self.cluster.cleanup()
            except Exception:
                subprocess.run(
                    [str(PG_BIN / "pg_ctl"), "-D", str(self.root / "data"), "-m", "immediate", "stop"],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                if self.root.exists():
                    for child in sorted(self.root.rglob("*"), reverse=True):
                        if child.is_file() or child.is_symlink():
                            child.unlink(missing_ok=True)
                        elif child.exists():
                            child.rmdir()
                    self.root.rmdir()

    def test_full_socket_restore_manifest_roles_active_session_refusal_and_cleanup(self):
        self.cluster.initialize()
        self.assertEqual(
            self.cluster.database_names(),
            ["postgres", "qt_rehearsal_baseline", "qt_rehearsal_destructive_tests", "qt_rehearsal_migrated"],
        )
        identity = self.cluster.identity("qt_rehearsal_migrated")
        self.assertEqual(identity[0], "qt_rehearsal_migrated")
        self.assertEqual(identity[1], "socket")
        self.assertEqual(identity[2], str(self.root / "data"))
        self.assertEqual(identity[3], "qt_rehearsal_admin")

        self.cluster.apply_sql(
            "qt_rehearsal_destructive_tests",
            "CREATE SCHEMA synthetic; "
            "CREATE TABLE synthetic.items(id integer PRIMARY KEY, value text NOT NULL); "
            "INSERT INTO synthetic.items VALUES (1, 'local-fixture');",
        )
        archive = self.root / "synthetic.dump"
        subprocess.run(
            [
                str(PG_BIN / "pg_dump"),
                "--format=custom",
                "--no-owner",
                "--no-privileges",
                "--host", str(self.root / "socket"),
                "--username", "qt_rehearsal_admin",
                "--dbname", "qt_rehearsal_destructive_tests",
                "--file", str(archive),
            ],
            check=True,
            env=self.cluster.command_environment(),
            capture_output=True,
            text=True,
        )
        archive_sha256 = hashlib.sha256(archive.read_bytes()).hexdigest()
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always", ResourceWarning)
            self.cluster.restore_archive("qt_rehearsal_baseline", archive, archive_sha256)
            self.cluster.restore_archive("qt_rehearsal_migrated", archive, archive_sha256)
            gc.collect()
        self.assertEqual(
            [warning for warning in captured if issubclass(warning.category, ResourceWarning)],
            [],
        )
        self.assertEqual(self.cluster.query_scalar("qt_rehearsal_baseline", "SELECT count(*) FROM synthetic.items"), "1")

        repo = self.root / "candidate-repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
        (repo / "migrations").mkdir()
        migration = repo / "migrations" / "013_synthetic.sql"
        migration.write_text("ALTER TABLE synthetic.items ADD COLUMN note text;\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "synthetic migration"], check=True)
        sha = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
        self.cluster.apply_sql("qt_rehearsal_destructive_tests", migration.read_text(encoding="utf-8"))
        expected_digest = self.cluster.schema_digest("qt_rehearsal_destructive_tests")
        manifest_value = {
            "schema_version": "qt-rehearsal-migration-manifest/v1",
            "profile": "live-futures",
            "target_database": "qt_rehearsal_migrated",
            "entries": [{
                "id": "trade-013-synthetic",
                "repository": "trade-ngin",
                "git_sha": sha,
                "path": "migrations/013_synthetic.sql",
                "sha256": hashlib.sha256(migration.read_bytes()).hexdigest(),
                "depends_on": [],
                "apply_predicate": {"type": "column_absent", "schema": "synthetic", "table": "items", "column": "note"},
                "rollback_policy": {"type": "forward_only", "reason": "synthetic integration fixture"},
                "expected_schema_digest": expected_digest,
            }],
        }
        manifest_path = self.root / "manifest.json"
        manifest_path.write_text(json.dumps(manifest_value), encoding="utf-8")
        results = self.cluster.apply_manifest(load_manifest(manifest_path), {"trade-ngin": repo})
        self.assertEqual(results, [{"id": "trade-013-synthetic", "outcome": "applied", "schema_digest": expected_digest}])

        destructive_manifest = dict(manifest_value)
        destructive_manifest["profile"] = "destructive-fixture"
        destructive_manifest["target_database"] = "qt_rehearsal_destructive_tests"
        manifest_path.write_text(json.dumps(destructive_manifest), encoding="utf-8")
        destructive_results = self.cluster.apply_manifest(load_manifest(manifest_path), {"trade-ngin": repo})
        self.assertEqual(
            destructive_results,
            [{"id": "trade-013-synthetic", "outcome": "skipped", "schema_digest": expected_digest}],
        )
        self.assertEqual(
            self.cluster.query_scalar(
                "qt_rehearsal_migrated",
                "SELECT count(*) FROM information_schema.columns WHERE table_schema='synthetic' AND table_name='items' AND column_name='note'",
            ),
            "1",
        )

        self.cluster.apply_sql(
            "qt_rehearsal_migrated",
            "CREATE ROLE qt_schema_owner NOLOGIN; CREATE ROLE qt_migrator NOLOGIN; "
            "CREATE ROLE qt_algolens_api NOLOGIN; CREATE ROLE qt_system_publisher NOLOGIN; CREATE ROLE qt_worker NOLOGIN; "
            "GRANT qt_schema_owner TO qt_migrator; "
            "CREATE SCHEMA role_test AUTHORIZATION qt_schema_owner; "
            "CREATE TABLE role_test.api_data(id integer); CREATE TABLE role_test.system_events(id integer); CREATE TABLE role_test.worker_jobs(id integer); "
            "GRANT USAGE ON SCHEMA role_test TO qt_algolens_api, qt_system_publisher, qt_worker; "
            "GRANT SELECT ON role_test.api_data TO qt_algolens_api; "
            "GRANT INSERT ON role_test.system_events TO qt_system_publisher; "
            "GRANT INSERT ON role_test.worker_jobs TO qt_worker;",
        )
        role_value = {
            "schema_version": "qt-rehearsal-role-contract/v1",
            "database": "qt_rehearsal_migrated",
            "roles": [
                {"domain": "schema_owner", "name": "qt_schema_owner"},
                {"domain": "migrator", "name": "qt_migrator"},
                {"domain": "algolens_api", "name": "qt_algolens_api"},
                {"domain": "system_publisher", "name": "qt_system_publisher"},
                {"domain": "qt_worker", "name": "qt_worker"},
            ],
            "probes": [
                {"id": "owner-no-runtime", "role_domain": "schema_owner", "sql": "SELECT * FROM role_test.api_data", "expect": "denied"},
                {"id": "migrator-ddl", "role_domain": "migrator", "sql": "CREATE TABLE role_test.allowed_migration(id integer)", "expect": "allowed"},
                {"id": "migrator-no-data", "role_domain": "migrator", "sql": "SELECT * FROM role_test.api_data", "expect": "denied"},
                {"id": "api-read", "role_domain": "algolens_api", "sql": "SELECT * FROM role_test.api_data", "expect": "allowed"},
                {"id": "api-no-system-write", "role_domain": "algolens_api", "sql": "INSERT INTO role_test.system_events VALUES (1)", "expect": "denied"},
                {"id": "publisher-write", "role_domain": "system_publisher", "sql": "INSERT INTO role_test.system_events VALUES (1)", "expect": "allowed"},
                {"id": "publisher-no-api-read", "role_domain": "system_publisher", "sql": "SELECT * FROM role_test.api_data", "expect": "denied"},
                {"id": "worker-write", "role_domain": "qt_worker", "sql": "INSERT INTO role_test.worker_jobs VALUES (1)", "expect": "allowed"},
                {"id": "worker-no-system-write", "role_domain": "qt_worker", "sql": "INSERT INTO role_test.system_events VALUES (1)", "expect": "denied"},
            ],
        }
        role_path = self.root / "roles.json"
        role_path.write_text(json.dumps(role_value), encoding="utf-8")
        role_results = self.cluster.verify_role_contract(load_role_contract(role_path))
        self.assertEqual(len(role_results), 9)
        self.assertTrue(all(result["passed"] for result in role_results))

        sleeper = subprocess.Popen(
            [
                str(PG_BIN / "psql"), "-X", "--no-psqlrc", "--no-password",
                "--host", str(self.root / "socket"),
                "--username", "qt_rehearsal_admin",
                "--dbname", "qt_rehearsal_migrated",
                "--command", "SELECT pg_sleep(30)",
            ],
            env=self.cluster.command_environment(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            time.sleep(0.5)
            with self.assertRaisesRegex(SafetyError, "active session"):
                self.cluster.cleanup()
            self.assertTrue(self.root.exists())
        finally:
            sleeper.send_signal(signal.SIGINT)
            sleeper.wait(timeout=5)

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            active = self.cluster.query_scalar(
                "qt_rehearsal_baseline",
                "SELECT count(*) FROM pg_stat_activity WHERE datname IN "
                "('qt_rehearsal_baseline','qt_rehearsal_migrated','qt_rehearsal_destructive_tests') "
                "AND pid<>pg_backend_pid();",
            )
            if active == "0":
                break
            time.sleep(0.05)
        self.assertEqual(active, "0")

        root = self.root
        self.cluster.cleanup()
        self.assertFalse(root.exists())


if __name__ == "__main__":
    unittest.main()
