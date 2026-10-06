import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from deployment.qt_rehearsal.harness import InputLockError, load_input_lock


class InputLockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.files = {}
        for kind in (
            "migration_manifest",
            "artifact_manifest",
            "config_snapshot",
            "role_contract",
            "data_bundle",
        ):
            path = self.root / f"{kind}.json"
            content = {"kind": kind, "value": "synthetic"}
            if kind == "config_snapshot":
                content = {"live": {"historical_days": 730}, "book": "CONSERVATIVE_PORTFOLIO"}
            path.write_text(json.dumps(content), encoding="utf-8")
            self.files[kind] = path
        self.lock_path = self.root / "input-lock.json"

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def value(self):
        return {
            "schema_version": "qt-rehearsal-input-lock/v1",
            "entries": [
                {
                    "kind": kind,
                    "path": path.name,
                    "sha256": self.digest(path),
                }
                for kind, path in self.files.items()
            ],
        }

    def write(self, value):
        self.lock_path.write_text(json.dumps(value), encoding="utf-8")

    def test_verifies_every_required_later_lane_input_by_exact_hash(self):
        self.write(self.value())
        lock = load_input_lock(self.lock_path)
        self.assertEqual(lock.schema_version, "qt-rehearsal-input-lock/v1")
        self.assertEqual(
            {entry.kind for entry in lock.entries},
            set(self.files),
        )

    def test_rejects_missing_kind_hash_drift_and_path_escape(self):
        cases = []
        missing = self.value()
        missing["entries"].pop()
        cases.append((missing, "exactly one"))
        drift = self.value()
        drift["entries"][0]["sha256"] = "0" * 64
        cases.append((drift, "SHA-256"))
        escape = self.value()
        escape["entries"][0]["path"] = "../outside.json"
        cases.append((escape, "escape"))
        absolute = self.value()
        absolute["entries"][0]["path"] = "/tmp/outside.json"
        cases.append((absolute, "relative"))
        for value, message in cases:
            with self.subTest(message=message):
                self.write(value)
                with self.assertRaisesRegex(InputLockError, message):
                    load_input_lock(self.lock_path)

    def test_rejects_secret_bearing_config_even_when_hash_matches(self):
        config = self.files["config_snapshot"]
        config.write_text(json.dumps({"database": {"password": "do-not-store"}}), encoding="utf-8")
        self.write(self.value())
        with self.assertRaisesRegex(InputLockError, "secret-stripped"):
            load_input_lock(self.lock_path)

    def test_input_lock_schema_names_the_required_contract(self):
        schema = json.loads(
            (Path(__file__).parents[1] / "schemas" / "input-lock.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual(schema["$id"], "qt-rehearsal-input-lock/v1")
        self.assertEqual(set(schema["required"]), {"schema_version", "entries"})


if __name__ == "__main__":
    unittest.main()
