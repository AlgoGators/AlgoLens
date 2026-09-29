"""Migration 007 (trading.strategy_registry.asset_class) applies cleanly to
the real migration chain, existing rows land NULL (never guessed from a
name), and the CHECK constraint only ever admits 'EQUITY', 'FUTURE' or NULL.
"""

from pathlib import Path

import psycopg2
import psycopg2.errors
import pytest

from tests.integration.conftest import claim_schema, require_test_dsn

MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"


def _query(dsn, sql, params=()):
    with psycopg2.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall() if cursor.description else None


@pytest.fixture
def registry_db():
    dsn = require_test_dsn()
    with psycopg2.connect(dsn) as connection:
        with connection.cursor() as cursor:
            claim_schema(cursor)
            cursor.execute((MIGRATIONS / "001_create_strategy_registry.sql").read_text(encoding="utf-8"))
            cursor.execute((MIGRATIONS / "002_strategy_lifecycle.sql").read_text(encoding="utf-8"))
    return dsn


def test_migration_applies_cleanly_and_existing_rows_are_null(registry_db):
    before = _query(registry_db, "SELECT id FROM trading.strategy_registry")
    assert before  # migration 001 seeds 'trendfollowing'
    _query(registry_db, (MIGRATIONS / "007_strategy_registry_asset_class.sql").read_text(encoding="utf-8"))
    rows = _query(registry_db, "SELECT id, asset_class FROM trading.strategy_registry")
    assert rows and all(asset_class is None for _id, asset_class in rows)
    # Safe to run more than once (ADD COLUMN IF NOT EXISTS).
    _query(registry_db, (MIGRATIONS / "007_strategy_registry_asset_class.sql").read_text(encoding="utf-8"))


def test_check_constraint_admits_only_equity_future_or_null(registry_db):
    _query(registry_db, (MIGRATIONS / "007_strategy_registry_asset_class.sql").read_text(encoding="utf-8"))
    _query(registry_db, "UPDATE trading.strategy_registry SET asset_class = 'EQUITY'")
    _query(registry_db, "UPDATE trading.strategy_registry SET asset_class = 'FUTURE'")
    _query(registry_db, "UPDATE trading.strategy_registry SET asset_class = NULL")
    with pytest.raises(psycopg2.errors.CheckViolation):
        _query(registry_db, "UPDATE trading.strategy_registry SET asset_class = 'CRYPTO'")
