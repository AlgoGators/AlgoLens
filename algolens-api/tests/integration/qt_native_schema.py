"""Retain API schema ownership when reusing the native disposable fixture."""
from contextlib import closing

import psycopg2
import pytest

from tests.integration.conftest import (
    OWNERSHIP_MARK, refuse_to_clobber_a_real_schema, require_test_dsn,
)
from test_runtime_control_schema import connection as native_connection


@pytest.fixture()
def connection():
    dsn = require_test_dsn()
    # Match the native fixture's owned-socket prerequisite before connecting.
    assert 'algolens_test_' in dsn and 'host=/tmp/algolens-repair-pg-' in dsn
    with closing(psycopg2.connect(dsn)) as control:
        control.autocommit = True
        with control.cursor() as cursor:
            refuse_to_clobber_a_real_schema(cursor)
    generator = native_connection.__wrapped__()
    conn = next(generator)
    try:
        # Only the schema this explicitly invoked fixture just recreated is
        # marked. Pre-existing unowned schemas were refused before its DROP.
        with conn.cursor() as cursor:
            cursor.execute('COMMENT ON SCHEMA trading IS %s', (OWNERSHIP_MARK,))
            # Shared native seed fixtures insert Python dates into timestamptz
            # daily-result columns. Seed UTC midnight, independently of the
            # server timezone; native subprocesses retain the server default.
            cursor.execute("SET TIME ZONE 'UTC'")
        yield conn
    finally:
        generator.close()
        conn.close()
