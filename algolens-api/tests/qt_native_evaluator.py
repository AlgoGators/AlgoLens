"""Owned cached native bundle for offline tests only; never an app default."""
import atexit
from functools import lru_cache
import importlib.util
from pathlib import Path
import tempfile


@lru_cache(maxsize=1)
def native_evaluator_configuration():
    engine = Path(__file__).resolve().parents[3] / "trade-ngin-qt"
    helper = engine / "tests/contracts/qt_native_bundle_fixture.py"
    spec = importlib.util.spec_from_file_location("qt_native_fixture_stage", helper)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    owned = tempfile.TemporaryDirectory(prefix="qt-owned-native-fixture-")
    atexit.register(owned.cleanup)
    directory = Path(owned.name) / "bundle"
    manifest = module.stage_actual_bundle(directory)
    executable = next(row for row in manifest["artifacts"] if row["role"] == "executable")
    return {"executable":directory / "bin/qt_evaluator", "expected_sha256":executable["sha256"],
        "expected_build":manifest["evaluator_build"], "bundle_directory":directory,
        "expected_bundle_sha256":manifest["bundle_sha256"]}
