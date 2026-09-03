"""The demo seed must satisfy the same contract a real database has to.

``scripts/demo_seed.sql`` is what every developer runs locally, so it is the
schema most of this application's behaviour is observed against. When it drifted
from the shape trade-ngin ships, the manual position write path was built
against the drift and could not have worked in production. Nothing noticed,
because the seed was only ever checked by using it.

This closes that loop: the seed is loaded into a real Postgres and compared with
the contract in ``algolens.infrastructure.db.schema_contract``. It runs in CI
alongside the other integration tests.

It does not prove the contract matches production -- only a dump from a real
database can do that. It proves the seed matches what this application says it
needs, which is the part that is ours to get right.
"""

import pathlib
import re

import pytest

from tests.integration.conftest import (
    OWNERSHIP_MARK,
    refuse_to_clobber_a_real_schema,
    require_test_dsn,
)

psycopg2 = pytest.importorskip("psycopg2")

from algolens.infrastructure.db.schema_contract import (  # noqa: E402
    check_schema,
    format_findings,
)

pytestmark = pytest.mark.integration

SEED = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "demo_seed.sql"

# Migration 009 owns these and lives in the other repository, so the seed does
# not create them and neither can CI check them out. Created here exactly as
# that migration declares them, so the contract can be checked in full.
BOOKS_TABLES = """
CREATE TABLE trading.portfolios (
    portfolio_id TEXT PRIMARY KEY, name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '', created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE trading.strategy_book_memberships (
    strategy_id TEXT NOT NULL, portfolio_id TEXT NOT NULL, added_by TEXT,
    added_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (strategy_id, portfolio_id)
);
CREATE TABLE trading.portfolio_assignments (
    id BIGSERIAL PRIMARY KEY, strategy_id TEXT NOT NULL, user_id TEXT,
    from_portfolio_id TEXT, to_portfolio_id TEXT, lifecycle_at_move TEXT,
    reason TEXT, consequences JSONB NOT NULL DEFAULT '[]'::jsonb,
    acknowledged BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT portfolio_assignments_has_a_side
        CHECK (from_portfolio_id IS NOT NULL OR to_portfolio_id IS NOT NULL)
);
"""


def _seed_body():
    """The seed, minus the two lines that make it create its own database."""
    text = SEED.read_text(encoding="utf-8")
    text = re.sub(r"(?im)^\s*CREATE DATABASE .*?;\s*$", "", text)
    text = re.sub(r"(?im)^\s*\\c .*$", "", text)
    return text


@pytest.fixture()
def seeded(monkeypatch):
    conn = psycopg2.connect(require_test_dsn())
    conn.autocommit = True
    with conn.cursor() as cur:
        # The seed builds the schema itself, so this only has to make sure the
        # schema it is about to replace is one this suite may destroy.
        refuse_to_clobber_a_real_schema(cur)
        for schema in ("trading", "auth", "futures_data", "metadata"):
            cur.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        cur.execute(_seed_body())
        cur.execute(BOOKS_TABLES)
        cur.execute("COMMENT ON SCHEMA trading IS %s", (OWNERSHIP_MARK,))
    yield conn
    with conn.cursor() as cur:
        for schema in ("trading", "auth", "futures_data", "metadata"):
            cur.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
    conn.close()


def test_the_demo_seed_satisfies_the_schema_contract(seeded):
    with seeded.cursor() as cur:
        findings = check_schema(cur)
    assert findings == [], "\n" + format_findings(findings)


def test_the_seed_declares_the_columns_the_write_path_depends_on(seeded):
    # Named individually because these three are the ones whose absence from
    # the seed hid a write path that could not insert into the real table.
    with seeded.cursor() as cur:
        cur.execute(
            "SELECT column_name, is_nullable FROM information_schema.columns"
            " WHERE table_schema='trading' AND table_name='positions'"
        )
        columns = dict(cur.fetchall())

    for required in ("daily_unrealized_pnl", "daily_realized_pnl", "last_update"):
        assert required in columns, f"{required} missing from the seeded positions table"
        assert columns[required] == "NO", (
            f"{required} is nullable in the seed but NOT NULL in the shipped schema; "
            "that difference is what hid the write bug"
        )
    assert columns["average_price"] == "NO"
