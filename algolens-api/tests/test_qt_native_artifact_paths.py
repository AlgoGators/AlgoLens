"""Portable path contract for optional native QT integration tests."""
from pathlib import Path

import pytest

from tests.qt_native_artifacts import NativeArtifactConfigurationError, NativeArtifactPaths


def configured(tmp_path):
    return {
        "TRADE_NGIN_TEST_SOURCE_DIR": str(tmp_path / "source"),
        "TRADE_NGIN_TEST_BUILD_DIR": str(tmp_path / "build"),
        "TRADE_NGIN_TEST_ARTIFACT_DIR": str(tmp_path / "artifacts"),
    }


def test_native_paths_require_all_explicit_absolute_inputs(tmp_path):
    environment = configured(tmp_path)
    paths = NativeArtifactPaths.from_environment(environment)
    assert paths.source_dir == tmp_path / "source"
    assert paths.build_dir == tmp_path / "build"
    assert paths.artifact_dir == tmp_path / "artifacts"
    assert paths.artifact("qt_evaluator") == tmp_path / "artifacts/qt_evaluator"

    for name in environment:
        incomplete = dict(environment)
        incomplete.pop(name)
        with pytest.raises(NativeArtifactConfigurationError, match=name):
            NativeArtifactPaths.from_environment(incomplete)

    relative = dict(environment, TRADE_NGIN_TEST_ARTIFACT_DIR="relative")
    with pytest.raises(NativeArtifactConfigurationError, match="absolute"):
        NativeArtifactPaths.from_environment(relative)


@pytest.mark.parametrize("name", ["", ".", "..", "../qt_evaluator", "bin/qt_evaluator"])
def test_native_artifact_names_are_single_safe_path_components(tmp_path, name):
    paths = NativeArtifactPaths.from_environment(configured(tmp_path))
    with pytest.raises(NativeArtifactConfigurationError, match="artifact name"):
        paths.artifact(name)


def test_python_tests_have_no_developer_absolute_paths():
    root = Path(__file__).resolve().parent
    forbidden = ("/home/" + "devcontainers/", "/home/" + "john-riley/")
    offenders = []
    for path in root.rglob("*.py"):
        if path == Path(__file__):
            continue
        text = path.read_text(encoding="utf-8")
        if any(value in text for value in forbidden):
            offenders.append(path.relative_to(root).as_posix())
    assert offenders == []
