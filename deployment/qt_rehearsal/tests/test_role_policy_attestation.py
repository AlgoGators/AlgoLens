import subprocess
from pathlib import Path
import tempfile
import unittest

from deployment.qt_rehearsal.cluster import RehearsalCluster
from deployment.qt_rehearsal.postgres_toolchain import PostgresToolchainError, resolve_postgres_bin


try:
    PG_BIN = resolve_postgres_bin()
except PostgresToolchainError:
    PG_BIN = None


@unittest.skipUnless(PG_BIN is not None, "PostgreSQL 16 toolchain unavailable via QT_REHEARSAL_PG_BIN or PATH")
class RolePolicyAttestationTests(unittest.TestCase):
    def setUp(self):
        assert PG_BIN is not None
        self.root = Path(tempfile.mkdtemp(prefix="algolens-qt-rehearsal.", dir="/dev/shm"))
        self.root.chmod(0o700)
        self.cluster = RehearsalCluster(self.root, PG_BIN)
        self.cluster.initialize()

    def tearDown(self):
        if not self.root.exists():
            return
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

    def test_role_policy_digest_changes_for_each_security_boundary(self):
        """Catches an attestation that ignores owners, ACLs, RLS, roles, or function hardening."""
        database = "qt_rehearsal_migrated"
        self.cluster.apply_sql(
            database,
            "CREATE ROLE qt_digest_owner NOLOGIN; "
            "CREATE ROLE qt_digest_runtime LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS; "
            "CREATE SCHEMA digest_test AUTHORIZATION qt_digest_owner; "
            "CREATE TYPE digest_test.stream_kind AS ENUM ('runtime'); "
            "ALTER TYPE digest_test.stream_kind OWNER TO qt_digest_owner; "
            "CREATE TABLE digest_test.rows(id integer PRIMARY KEY, stream digest_test.stream_kind NOT NULL); "
            "ALTER TABLE digest_test.rows OWNER TO qt_digest_owner; "
            "CREATE FUNCTION digest_test.guard() RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER "
            "SET search_path=pg_catalog AS $$ BEGIN RETURN NEW; END $$; "
            "ALTER FUNCTION digest_test.guard() OWNER TO qt_digest_owner;",
        )
        self.assertTrue(
            hasattr(self.cluster, "role_policy_digest"),
            "the canonical rehearsal attestation must expose a role/policy digest",
        )
        baseline = self.cluster.role_policy_digest(database)

        mutations = (
            "ALTER TABLE digest_test.rows OWNER TO qt_rehearsal_admin;",
            "GRANT SELECT ON digest_test.rows TO qt_digest_runtime;",
            "ALTER TABLE digest_test.rows ENABLE ROW LEVEL SECURITY; "
            "CREATE POLICY digest_runtime_read ON digest_test.rows FOR SELECT TO qt_digest_runtime USING (stream='runtime');",
            "CREATE TRIGGER digest_guard BEFORE UPDATE ON digest_test.rows FOR EACH ROW EXECUTE FUNCTION digest_test.guard();",
            "ALTER FUNCTION digest_test.guard() SECURITY DEFINER;",
            "ALTER ROLE qt_digest_runtime BYPASSRLS;",
            "GRANT qt_digest_owner TO qt_digest_runtime;",
        )
        previous = baseline
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.cluster.apply_sql(database, mutation)
                current = self.cluster.role_policy_digest(database)
                self.assertNotEqual(previous, current, mutation)
                previous = current


if __name__ == "__main__":
    unittest.main()
