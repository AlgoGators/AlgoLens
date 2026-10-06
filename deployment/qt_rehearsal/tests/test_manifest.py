import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from deployment.qt_rehearsal.harness import ManifestError, load_manifest, verify_manifest_sources


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name) / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.email", "test@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.name", "Test"], check=True)
        (self.repo / "migrations").mkdir()
        self.first = self.repo / "migrations" / "001_safe.sql"
        self.first.write_text("CREATE SCHEMA IF NOT EXISTS synthetic;\n", encoding="utf-8")
        self.second = self.repo / "migrations" / "013_runtime.sql"
        self.second.write_text("CREATE TABLE synthetic.ready(id integer);\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-qm", "fixture"], check=True)
        self.sha = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"],
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
        self.manifest_path = Path(self.temp.name) / "manifest.json"

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def manifest(self):
        return {
            "schema_version": "qt-rehearsal-migration-manifest/v1",
            "profile": "live-futures",
            "target_database": "qt_rehearsal_migrated",
            "entries": [
                {
                    "id": "algolens-001",
                    "repository": "algolens",
                    "git_sha": self.sha,
                    "path": "migrations/001_safe.sql",
                    "sha256": self.digest(self.first),
                    "depends_on": [],
                    "apply_predicate": {"type": "always"},
                    "rollback_policy": {"type": "forward_only", "reason": "synthetic fixture"},
                    "expected_schema_digest": "a" * 64,
                },
                {
                    "id": "trade-013",
                    "repository": "trade-ngin",
                    "git_sha": self.sha,
                    "path": "migrations/013_runtime.sql",
                    "sha256": self.digest(self.second),
                    "depends_on": ["algolens-001"],
                    "apply_predicate": {
                        "type": "table_absent",
                        "schema": "synthetic",
                        "table": "ready",
                    },
                    "rollback_policy": {"type": "forward_only", "reason": "synthetic fixture"},
                    "expected_schema_digest": "b" * 64,
                },
            ],
        }

    def write(self, value):
        self.manifest_path.write_text(json.dumps(value), encoding="utf-8")

    def test_validates_explicit_order_dependencies_and_source_bytes(self):
        self.write(self.manifest())
        manifest = load_manifest(self.manifest_path)
        verified = verify_manifest_sources(
            manifest,
            {"algolens": self.repo, "trade-ngin": self.repo},
        )
        self.assertEqual([entry.id for entry in verified], ["algolens-001", "trade-013"])

    def test_rejects_a_worktree_symlink_before_following_it(self):
        original = self.first.read_text(encoding="utf-8")
        target = Path(self.temp.name) / "outside.sql"
        target.write_text(original, encoding="utf-8")
        self.first.unlink()
        self.first.symlink_to(target)
        value = self.manifest()
        value["entries"] = value["entries"][:1]
        self.write(value)
        with self.assertRaisesRegex(ManifestError, "regular repository file"):
            verify_manifest_sources(load_manifest(self.manifest_path), {"algolens": self.repo})

    def test_rejects_dependency_that_has_not_already_appeared(self):
        value = self.manifest()
        value["entries"].reverse()
        self.write(value)
        with self.assertRaisesRegex(ManifestError, "earlier"):
            load_manifest(self.manifest_path)

    def test_rejects_wrong_hash_wrong_commit_and_absolute_or_escaping_path(self):
        cases = [
            ("sha256", "0" * 64, "SHA-256"),
            ("git_sha", "f" * 40, "Git SHA"),
            ("path", "/tmp/migration.sql", "relative"),
            ("path", "../migration.sql", "escape"),
        ]
        for field, bad, message in cases:
            with self.subTest(field=field):
                value = self.manifest()
                value["entries"][0][field] = bad
                self.write(value)
                try:
                    manifest = load_manifest(self.manifest_path)
                    verify_manifest_sources(
                        manifest,
                        {"algolens": self.repo, "trade-ngin": self.repo},
                    )
                except ManifestError as error:
                    self.assertIn(message, str(error))
                else:
                    self.fail("unsafe manifest entry was accepted")

    def test_live_futures_profile_rejects_backfill_investor_equity_and_incubating(self):
        forbidden = (
            "migrations/002_backfill_qt_from_system.sql",
            "migrations/019_qt_equity_desk_accounting.sql",
            "migrations/025_runtime_scope_model_incubating.sql",
            "migrations/026_investor_books_and_publications.sql",
        )
        for path in forbidden:
            with self.subTest(path=path):
                value = self.manifest()
                value["entries"][0]["path"] = path
                self.write(value)
                with self.assertRaisesRegex(ManifestError, "live-futures"):
                    load_manifest(self.manifest_path)

    def test_manifest_schema_is_valid_json_and_matches_required_interface(self):
        schema_path = Path(__file__).parents[1] / "schemas" / "migration-manifest.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.assertEqual(schema["$id"], "qt-rehearsal-migration-manifest/v1")
        self.assertEqual(
            set(schema["required"]),
            {"schema_version", "profile", "target_database", "entries"},
        )


if __name__ == "__main__":
    unittest.main()
