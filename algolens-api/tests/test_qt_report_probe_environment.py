"""Report probe credentials stay inside an explicitly private synthetic DSN."""
from pathlib import Path
import tempfile

from psycopg2.extensions import make_dsn, parse_dsn
import pytest

from tests.qt_report_probe import report_probe_environment


@pytest.fixture
def private_environment():
    with tempfile.TemporaryDirectory(prefix='algolens-repair-pg-', suffix='.abc123') as name:
        root = Path(name)
        (root / 'data').mkdir(mode=0o700)
        yield {'ALGOLENS_TEST_DB': make_dsn(host=name, dbname='algolens_test_report',
                                           user='postgres', port=5432), 'TZ': 'America/New_York'}


def test_report_only_adds_synthetic_guard_credential_without_mutating_clock_dsn(private_environment):
    original = dict(private_environment)
    result = report_probe_environment(Path('/controlled/guard.so'), private_environment)
    assert private_environment == original
    assert parse_dsn(result['ALGOLENS_TEST_DB']) == {
        **parse_dsn(original['ALGOLENS_TEST_DB']), 'password': 'synthetic-test-only'}
    assert result['LD_PRELOAD'] == '/controlled/guard.so'
    assert result['TZ'] == 'America/New_York'


@pytest.mark.parametrize('changed', [
    {'host': 'localhost'}, {'host': '/tmp'}, {'dbname': 'new_algo_data'},
    {'user': 'real_user'}, {'port': 5433}, {'password': 'not-the-synthetic-literal'},
    {'options': '-c search_path=public'},
])
def test_report_probe_refuses_non_fixture_connection_fields(private_environment, changed):
    environment = {**private_environment,
        'ALGOLENS_TEST_DB': make_dsn(private_environment['ALGOLENS_TEST_DB'], **changed)}
    with pytest.raises(ValueError, match='private synthetic'):
        report_probe_environment(Path('/controlled/guard.so'), environment)


def test_report_probe_refuses_non_private_socket_directory(private_environment):
    root = Path(parse_dsn(private_environment['ALGOLENS_TEST_DB'])['host'])
    root.chmod(0o755)
    try:
        with pytest.raises(ValueError, match='private synthetic'):
            report_probe_environment(Path('/controlled/guard.so'), private_environment)
    finally:
        root.chmod(0o700)
