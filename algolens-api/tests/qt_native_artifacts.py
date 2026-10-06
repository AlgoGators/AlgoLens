"""Explicit, portable inputs for optional trade-ngin native integration tests."""
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Mapping


class NativeArtifactConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class NativeArtifactPaths:
    source_dir: Path
    build_dir: Path
    artifact_dir: Path

    @classmethod
    def from_environment(cls, environment: Mapping[str, str] = os.environ):
        values = {}
        for name, field in (
            ("TRADE_NGIN_TEST_SOURCE_DIR", "source_dir"),
            ("TRADE_NGIN_TEST_BUILD_DIR", "build_dir"),
            ("TRADE_NGIN_TEST_ARTIFACT_DIR", "artifact_dir"),
        ):
            raw = environment.get(name)
            if not raw:
                raise NativeArtifactConfigurationError(f"{name} is required")
            path = Path(raw)
            if not path.is_absolute():
                raise NativeArtifactConfigurationError(f"{name} must be an absolute path")
            values[field] = path
        return cls(**values)

    def artifact(self, name: str) -> Path:
        if not isinstance(name, str) or not name or Path(name).name != name or name in {".", ".."}:
            raise NativeArtifactConfigurationError("invalid native artifact name")
        return self.artifact_dir / name


def require_native_artifact_paths(*, allow_module_level: bool = False) -> NativeArtifactPaths:
    import pytest

    try:
        return NativeArtifactPaths.from_environment()
    except NativeArtifactConfigurationError as exc:
        pytest.skip(f"native QT artifact configuration unavailable: {exc}",
                    allow_module_level=allow_module_level)
