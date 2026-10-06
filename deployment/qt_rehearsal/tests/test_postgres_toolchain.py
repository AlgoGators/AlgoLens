from pathlib import Path

import pytest

from deployment.qt_rehearsal.postgres_toolchain import (
    PostgresToolchainError,
    resolve_postgres_bin,
)


TOOLS = ("postgres", "initdb", "pg_ctl", "createdb", "dropdb", "psql", "pg_dump", "pg_restore")


def make_tools(directory: Path):
    directory.mkdir(parents=True)
    for name in TOOLS:
        path = directory / name
        path.write_text("#!/bin/sh\n", encoding="utf-8")
        path.chmod(0o700)


def test_explicit_absolute_postgres_bin_wins(tmp_path):
    binary_dir = tmp_path / "pg16/bin"
    make_tools(binary_dir)
    resolved = resolve_postgres_bin(
        {"QT_REHEARSAL_PG_BIN": str(binary_dir)},
        which=lambda _name: "/ignored/postgres",
    )
    assert resolved == binary_dir


def test_relative_postgres_bin_is_rejected():
    with pytest.raises(PostgresToolchainError, match="absolute"):
        resolve_postgres_bin({"QT_REHEARSAL_PG_BIN": "relative/bin"})


def test_path_discovery_requires_every_tool_in_one_directory(tmp_path):
    binary_dir = tmp_path / "pg16/bin"
    make_tools(binary_dir)
    assert resolve_postgres_bin({}, which=lambda name: str(binary_dir / name)) == binary_dir

    other = tmp_path / "other"
    other.mkdir()
    with pytest.raises(PostgresToolchainError, match="same directory"):
        resolve_postgres_bin(
            {}, which=lambda name: str(other / name) if name == "psql" else str(binary_dir / name)
        )


def test_missing_path_toolchain_is_reported_not_guessed():
    with pytest.raises(PostgresToolchainError, match="unavailable"):
        resolve_postgres_bin({}, which=lambda _name: None)
