"""Actual disposable SQL checks for the API/native fixture ownership boundary."""
from contextlib import closing

import psycopg2
import pytest

from tests.integration.conftest import OWNERSHIP_MARK, claim_schema, require_test_dsn


def selected_connection():
    # Register the real engine fixture imports, then choose the staged bridge.
    import tests.integration.test_qt_upstream_accounting
    from tests.integration.qt_native_schema import connection
    return connection.__wrapped__()


def schema_oid(cursor):
    cursor.execute("SELECT oid FROM pg_namespace WHERE nspname='trading'")
    return cursor.fetchone()[0]


def test_native_fixture_then_api_fixture():
    with closing(psycopg2.connect(require_test_dsn())) as control:
        control.autocommit = True
        with control.cursor() as cursor:
            claim_schema(cursor)
        generator = selected_connection()
        native = next(generator)
        with native.cursor() as cursor:
            created_oid = schema_oid(cursor)
        try:
            # This is the operation that failed in 82 later full-suite setups.
            with native.cursor() as cursor:
                claim_schema(cursor)
                cursor.execute("CREATE TABLE trading.following_api_test(id integer)")
        finally:
            # In the RED case only: this exact schema was just created above by
            # the explicitly invoked disposable native fixture. Never claim an
            # unrelated replacement, and do not change the production guard.
            with control.cursor() as cursor:
                if schema_oid(cursor) == created_oid:
                    cursor.execute('COMMENT ON SCHEMA trading IS %s', (OWNERSHIP_MARK,))
            generator.close()
            native.close()
        assert native.closed


def test_api_native_bridge_refuses_existing_unowned_schema():
    with closing(psycopg2.connect(require_test_dsn())) as control:
        control.autocommit = True
        with control.cursor() as cursor:
            claim_schema(cursor)
            cursor.execute('CREATE TABLE trading.owned_regression_sentinel(value text)')
            cursor.execute("INSERT INTO trading.owned_regression_sentinel VALUES('preserve me')")
            created_oid = schema_oid(cursor)
            cursor.execute('COMMENT ON SCHEMA trading IS NULL')
        generator = selected_connection()
        try:
            with pytest.raises(pytest.fail.Exception, match='this suite did not create'):
                next(generator)
            with control.cursor() as cursor:
                assert schema_oid(cursor) == created_oid
                cursor.execute('SELECT value FROM trading.owned_regression_sentinel')
                assert cursor.fetchall() == [('preserve me',)]
        finally:
            generator.close()
            with control.cursor() as cursor:
                assert schema_oid(cursor) == created_oid
                cursor.execute('COMMENT ON SCHEMA trading IS %s', (OWNERSHIP_MARK,))


def test_api_native_bridge_closes_connection_on_test_failure():
    with closing(psycopg2.connect(require_test_dsn())) as control:
        control.autocommit = True
        with control.cursor() as cursor:
            claim_schema(cursor)
    generator = selected_connection()
    native = next(generator)
    with pytest.raises(RuntimeError, match='simulated test assertion'):
        generator.throw(RuntimeError('simulated test assertion'))
    assert native.closed
