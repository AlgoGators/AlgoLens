"""Explicit private rehearsal connection boundary, shared by all API traffic."""
from dataclasses import dataclass
import os
from pathlib import Path
import re

import psycopg2
from psycopg2.extras import RealDictCursor


def validate_rehearsal_root(value) -> Path:
    try:
        root = Path(value)
    except TypeError:
        raise ValueError('rehearsal_connection_root_invalid') from None
    if (not root.is_absolute() or root.parent != Path('/dev/shm')
            or re.fullmatch(r'algolens-qt-rehearsal\.[A-Za-z0-9_-]{6,64}', root.name) is None
            or root.is_symlink()
            or (root.exists() and (root.resolve() != root.absolute()
                or root.stat().st_uid != os.getuid() or root.stat().st_mode & 0o777 != 0o700))):
        raise ValueError('rehearsal_connection_root_invalid')
    return root


@dataclass(frozen=True)
class RehearsalDatabase:
    root: Path

    def __post_init__(self):
        object.__setattr__(self, 'root', validate_rehearsal_root(self.root))

    def connect(self):
        # Empty libpq keyword values can fall back to the environment. Refuse
        # inherited libpq configuration instead of editing global os.environ.
        if any(name.startswith('PG') and value for name, value in os.environ.items()):
            raise ValueError('rehearsal_connection_environment_invalid')
        root = validate_rehearsal_root(self.root)
        socket = root / 'socket'
        if (not root.is_dir() or not socket.is_dir() or socket.is_symlink()
                or socket.stat().st_uid != os.getuid()
                or socket.stat().st_mode & 0o777 != 0o700):
            raise ValueError('rehearsal_connection_socket_invalid')
        connection = psycopg2.connect(
            host=str(socket), port=5432, dbname='qt_rehearsal_migrated',
            user='qt_algolens_api', password='', passfile='/dev/null',
            sslmode='disable', gssencmode='disable', options='', connect_timeout=5,
            cursor_factory=RealDictCursor,
        )
        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT current_database() AS database_name, current_user AS database_role, '
                               'inet_server_addr() AS server_addr')
                if cursor.fetchone() != {'database_name':'qt_rehearsal_migrated',
                                         'database_role':'qt_algolens_api', 'server_addr':None}:
                    raise ValueError('rehearsal_connection_identity_invalid')
            connection.rollback()
            return connection
        except BaseException:
            connection.close()
            raise
