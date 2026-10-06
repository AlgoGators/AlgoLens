import os
from pathlib import Path
import tempfile
import unittest

from deployment.qt_rehearsal.harness import (
    DATABASES,
    SafetyError,
    build_identity_guard,
    safe_restore_flags,
    validate_database_name,
    validate_rehearsal_root,
    validate_sql_payload,
)


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="algolens-qt-rehearsal.", dir="/dev/shm"))
        self.root.chmod(0o700)

    def tearDown(self):
        if self.root.is_symlink():
            self.root.unlink(missing_ok=True)
        elif self.root.exists():
            for child in sorted(self.root.rglob("*"), reverse=True):
                if child.is_file() or child.is_symlink():
                    child.unlink()
                else:
                    child.rmdir()
            self.root.rmdir()

    def test_accepts_only_exact_private_current_user_root(self):
        self.assertEqual(validate_rehearsal_root(self.root), self.root)
        self.root.chmod(0o750)
        with self.assertRaisesRegex(SafetyError, "mode 0700"):
            validate_rehearsal_root(self.root)

    def test_rejects_symlink_and_non_shm_roots(self):
        target = self.root
        link = target.parent / (target.name + "-link")
        link.symlink_to(target)
        self.addCleanup(link.unlink, missing_ok=True)
        with self.assertRaisesRegex(SafetyError, "symlink"):
            validate_rehearsal_root(link)
        with tempfile.TemporaryDirectory(prefix="algolens-qt-rehearsal.") as outside:
            os.chmod(outside, 0o700)
            with self.assertRaisesRegex(SafetyError, "/dev/shm"):
                validate_rehearsal_root(Path(outside))

    def test_database_names_are_fixed_and_production_is_impossible(self):
        self.assertEqual(
            DATABASES,
            ("qt_rehearsal_baseline", "qt_rehearsal_migrated", "qt_rehearsal_destructive_tests"),
        )
        for database in DATABASES:
            self.assertEqual(validate_database_name(database), database)
        for database in ("new_algo_data", "postgres", "qt_rehearsal_typo", ""):
            with self.subTest(database=database), self.assertRaises(SafetyError):
                validate_database_name(database)

    def test_identity_guard_pins_database_socket_data_directory_and_role(self):
        guard = build_identity_guard(
            database="qt_rehearsal_migrated",
            data_directory=self.root / "data",
            role="qt_rehearsal_admin",
        )
        self.assertIn("current_database()", guard)
        self.assertIn("inet_server_addr() IS NOT NULL", guard)
        self.assertIn(str(self.root / "data"), guard)
        self.assertIn("qt_rehearsal_admin", guard)
        self.assertNotIn("new_algo_data", guard)

    def test_sql_payload_refuses_session_escape_and_external_access(self):
        validate_sql_payload("BEGIN; CREATE TABLE trading.safe(id integer); COMMIT;")
        unsafe = (
            r"\connect new_algo_data",
            "CREATE DATABASE surprise",
            "DROP DATABASE qt_rehearsal_baseline",
            "ALTER SYSTEM SET listen_addresses='*'",
            "COPY x TO PROGRAM 'curl example.invalid'",
            "CREATE EXTENSION postgres_fdw",
            "SELECT dblink_connect('host=example.invalid')",
        )
        for sql in unsafe:
            with self.subTest(sql=sql), self.assertRaises(SafetyError):
                validate_sql_payload(sql)

    def test_restore_flags_cannot_create_or_clean_databases(self):
        flags = safe_restore_flags()
        self.assertEqual(flags, ("--exit-on-error", "--no-owner", "--no-privileges", "--file=-"))
        self.assertFalse({"--create", "--clean", "-C"}.intersection(flags))


if __name__ == "__main__":
    unittest.main()
