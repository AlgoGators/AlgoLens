"""Shared protection for the tests in this directory.

Every test here builds its schema from scratch, which means dropping whatever
``trading`` schema it finds. That is safe against a disposable database and
catastrophic against one that is not: pointing ``ALGOLENS_TEST_DB`` at the demo
database once destroyed it mid-session.

The guard below is what stands between those two outcomes, so it lives here
rather than in one test file, and every fixture that drops a schema calls it.
"""

import os

import pytest

#: Stamped on a schema this suite creates, so it can recognise its own
#: leftovers. A crashed run leaves the marker behind; a seeded demo, a
#: migration test bed or a real database never carries it.
OWNERSHIP_MARK = "owned by tests/integration; safe to drop"


def require_test_dsn():
    dsn = os.getenv("ALGOLENS_TEST_DB")
    if not dsn:
        pytest.skip("ALGOLENS_TEST_DB not set; integration tests skipped")
    return dsn


def refuse_to_clobber_a_real_schema(cur):
    """Fail loudly rather than drop a schema this suite did not create."""
    cur.execute(
        "SELECT obj_description(oid, 'pg_namespace') FROM pg_namespace "
        "WHERE nspname = 'trading'"
    )
    row = cur.fetchone()
    if row is None or row[0] == OWNERSHIP_MARK:
        return
    cur.execute("SELECT count(*) FROM pg_tables WHERE schemaname = 'trading'")
    tables = cur.fetchone()[0]
    if tables == 0:
        return
    pytest.fail(
        f"ALGOLENS_TEST_DB points at a database whose trading schema already "
        f"holds {tables} table(s) this suite did not create. These tests DROP "
        f"that schema. Name a disposable database instead."
    )


def claim_schema(cur):
    """Drop and recreate ``trading``, marking it as this suite's to drop."""
    refuse_to_clobber_a_real_schema(cur)
    cur.execute("DROP SCHEMA IF EXISTS trading CASCADE")
    cur.execute("CREATE SCHEMA trading")
    cur.execute("COMMENT ON SCHEMA trading IS %s", (OWNERSHIP_MARK,))
