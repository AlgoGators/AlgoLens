"""Owned cached native bundle for offline tests only; never an app default."""
import atexit
from functools import lru_cache
import importlib.util
import json
from pathlib import Path
import sys
import tempfile

from tests.qt_native_artifacts import require_native_artifact_paths


def native_evaluator_requests():
    """Fresh synthetic requests from the same explicit source as the bundle.

    Match trade-ngin's CLI contract fixture binding: only the synthetic build
    placeholder is replaced. A deliberately wrong identity stays wrong.
    """
    paths = require_native_artifact_paths()
    requests = json.loads((paths.source_dir / "tests/contracts/qt-eval-v1.json").read_text())
    build = native_evaluator_configuration()["expected_build"]
    for request in requests.values():
        if request.get("evaluator_build") == "local-qt-controlled":
            request["evaluator_build"] = build
    return requests


@lru_cache(maxsize=1)
def native_evaluator_configuration():
    paths = require_native_artifact_paths()
    helper = paths.source_dir / "tests/contracts/qt_native_bundle_fixture.py"
    artifact_helper = paths.source_dir / "tests/qt_test_artifacts.py"
    artifact_spec = importlib.util.spec_from_file_location("algolens_trade_ngin_test_artifacts", artifact_helper)
    artifact_module = importlib.util.module_from_spec(artifact_spec)
    artifact_spec.loader.exec_module(artifact_module)
    previous = sys.modules.get("tests.qt_test_artifacts")
    sys.modules["tests.qt_test_artifacts"] = artifact_module
    spec = importlib.util.spec_from_file_location("qt_native_fixture_stage", helper)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    finally:
        if previous is None:
            sys.modules.pop("tests.qt_test_artifacts", None)
        else:
            sys.modules["tests.qt_test_artifacts"] = previous
    owned = tempfile.TemporaryDirectory(prefix="qt-owned-native-fixture-")
    atexit.register(owned.cleanup)
    directory = Path(owned.name) / "bundle"
    manifest = module.stage_actual_bundle(directory)
    executable = next(row for row in manifest["artifacts"] if row["role"] == "executable")
    return {"executable":directory / "bin/qt_evaluator", "expected_sha256":executable["sha256"],
        "expected_build":manifest["evaluator_build"], "bundle_directory":directory,
        "expected_bundle_sha256":manifest["bundle_sha256"]}
