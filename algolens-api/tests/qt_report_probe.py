"""Private synthetic credentials for the guarded, no-delivery report probe."""
import os
from pathlib import Path
import re
import stat

from psycopg2.extensions import make_dsn, parse_dsn


def report_probe_environment(delivery_guard: Path, environment=os.environ):
    """Keep the clock fixture's password-free DSN unchanged in the parent.

    The report-only native probe additionally requires a fixed synthetic
    password sentinel. Never attach it to an arbitrary connection string.
    """
    try:
        fields = parse_dsn(environment['ALGOLENS_TEST_DB'])
        root = Path(fields['host'])
        if (set(fields) - {'host', 'port', 'dbname', 'user', 'password', 'connect_timeout'}
                or root.parent != Path('/tmp')
                or not re.fullmatch(r'algolens-repair-pg-[A-Za-z0-9_-]+\.[A-Za-z0-9]+', root.name)
                or root.resolve() != root or root.is_symlink()
                or not re.fullmatch(r'algolens_test_[A-Za-z0-9_]+', fields['dbname'])
                or fields['user'] != 'postgres' or fields.get('port', '5432') != '5432'
                or fields.get('password', 'synthetic-test-only') != 'synthetic-test-only'):
            raise ValueError()
        for directory in (root, root / 'data'):
            info = directory.stat()
            if (directory.is_symlink() or not stat.S_ISDIR(info.st_mode)
                    or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700):
                raise ValueError()
    except (KeyError, OSError, ValueError):
        raise ValueError('report probe requires a private synthetic database') from None
    return {**environment, 'LD_PRELOAD': str(delivery_guard),
        'ALGOLENS_TEST_DB': make_dsn(**{**fields, 'port': '5432', 'password': 'synthetic-test-only'})}
