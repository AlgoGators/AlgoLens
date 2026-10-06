import json
from pathlib import Path
import tempfile
import unittest

from deployment.qt_rehearsal.harness import (
    EvidenceError,
    RoleContractError,
    load_role_contract,
    sanitize_evidence,
    write_evidence,
)


class EvidenceAndRoleTests(unittest.TestCase):
    def test_evidence_accepts_only_sanitized_summary_fields(self):
        value = {
            "schema_version": "qt-rehearsal-evidence/v1",
            "run_id": "synthetic-20261006",
            "postgres_version": "16.15",
            "root_fingerprint": "a" * 64,
            "database_summaries": [
                {"database": "qt_rehearsal_migrated", "schema_digest": "b" * 64, "row_count": 7}
            ],
            "role_results": [{"probe": "api-read", "role_domain": "algolens_api", "outcome": "allowed"}],
            "test_reports": [{"name": "unit", "passed": 12, "failed": 0}],
        }
        self.assertEqual(sanitize_evidence(value), value)

    def test_evidence_rejects_credentials_dsns_raw_paths_and_unknown_fields(self):
        bad_values = (
            {"schema_version": "qt-rehearsal-evidence/v1", "password": "secret"},
            {"schema_version": "qt-rehearsal-evidence/v1", "note": "postgresql://user:pw@host/db"},
            {"schema_version": "qt-rehearsal-evidence/v1", "note": "/dev/shm/algolens-qt-rehearsal.ABC/data"},
            {"schema_version": "qt-rehearsal-evidence/v1", "raw_rows": [{"email": "person@example.com"}]},
        )
        for value in bad_values:
            with self.subTest(value=value), self.assertRaises(EvidenceError):
                sanitize_evidence(value)

    def test_evidence_write_is_private_canonical_json(self):
        value = {
            "schema_version": "qt-rehearsal-evidence/v1",
            "run_id": "synthetic",
            "postgres_version": "16.15",
            "root_fingerprint": "c" * 64,
            "database_summaries": [],
            "role_results": [],
            "test_reports": [],
        }
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "evidence.json"
            write_evidence(output, value)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), value)

    def test_role_contract_requires_all_access_domains_and_both_outcomes(self):
        contract = {
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
                {"id": "api-read", "role_domain": "algolens_api", "sql": "SELECT 1", "expect": "allowed"},
                {"id": "api-no-ddl", "role_domain": "algolens_api", "sql": "CREATE TABLE forbidden(id int)", "expect": "denied"},
                {"id": "publisher-write", "role_domain": "system_publisher", "sql": "SELECT 1", "expect": "allowed"},
                {"id": "publisher-no-worker", "role_domain": "system_publisher", "sql": "SELECT 1/0", "expect": "denied"},
                {"id": "worker-write", "role_domain": "qt_worker", "sql": "SELECT 1", "expect": "allowed"},
                {"id": "worker-no-system", "role_domain": "qt_worker", "sql": "SELECT 1/0", "expect": "denied"},
                {"id": "migrator-ddl", "role_domain": "migrator", "sql": "SELECT 1", "expect": "allowed"},
                {"id": "migrator-no-owner-login", "role_domain": "migrator", "sql": "SELECT 1/0", "expect": "denied"},
                {"id": "owner-not-runtime", "role_domain": "schema_owner", "sql": "SELECT 1/0", "expect": "denied"},
            ],
        }
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "roles.json"
            path.write_text(json.dumps(contract), encoding="utf-8")
            loaded = load_role_contract(path)
            self.assertEqual(len(loaded.roles), 5)
            self.assertEqual(len(loaded.probes), 9)

            for mutation in ("roles", "probes"):
                broken = dict(contract)
                broken[mutation] = contract[mutation][:-1]
                path.write_text(json.dumps(broken), encoding="utf-8")
                with self.subTest(mutation=mutation), self.assertRaises(RoleContractError):
                    load_role_contract(path)


if __name__ == "__main__":
    unittest.main()
