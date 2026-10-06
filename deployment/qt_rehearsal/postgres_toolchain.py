"""Resolve an optional PostgreSQL toolchain without workstation-specific defaults."""
import os
from pathlib import Path
import shutil
from typing import Callable, Mapping


TOOLS = ("postgres", "initdb", "pg_ctl", "createdb", "dropdb", "psql", "pg_dump", "pg_restore")


class PostgresToolchainError(ValueError):
    pass


def _validate(directory: Path) -> Path:
    missing = [name for name in TOOLS if not (directory / name).is_file() or not os.access(directory / name, os.X_OK)]
    if missing:
        raise PostgresToolchainError("PostgreSQL toolchain unavailable: " + ", ".join(missing))
    return directory


def resolve_postgres_bin(
    environment: Mapping[str, str] = os.environ,
    *,
    which: Callable[[str], str | None] = shutil.which,
) -> Path:
    configured = environment.get("QT_REHEARSAL_PG_BIN")
    if configured:
        directory = Path(configured)
        if not directory.is_absolute():
            raise PostgresToolchainError("QT_REHEARSAL_PG_BIN must be an absolute path")
        return _validate(directory)

    located = [which(name) for name in TOOLS]
    if any(path is None for path in located):
        raise PostgresToolchainError("PostgreSQL toolchain unavailable on PATH")
    directories = {Path(path).resolve().parent for path in located if path is not None}
    if len(directories) != 1:
        raise PostgresToolchainError("PostgreSQL tools must resolve from the same directory")
    return _validate(directories.pop())
