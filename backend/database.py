import psycopg2
import logging
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool
import os
from dotenv import load_dotenv
from pathlib import Path
import socket
import threading

ENV_PATH = Path(__file__).resolve().parent / '.env'
load_dotenv(dotenv_path=ENV_PATH)

logger = logging.getLogger(__name__)
_pool = None
_pool_lock = threading.Lock()

# Log database configuration at module load
logger.info('=== Database module loaded ===')
logger.info(f'DB_HOST: {os.getenv("DB_HOST")}')
logger.info(f'DB_PORT: {os.getenv("DB_PORT", "5432")}')
logger.info(f'DB_NAME: {os.getenv("DB_NAME")}')
logger.info(f'DB_USER: {os.getenv("DB_USER")}')
logger.info(f'DB_PASSWORD set: {"Yes" if os.getenv("DB_PASSWORD") else "NO - THIS WILL FAIL"}')


class _PooledConnection:
    def __init__(self, pool, conn):
        self._pool = pool
        self._conn = conn
        self._returned = False

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def close(self):
        if self._returned:
            return
        self._returned = True
        close_conn = bool(self._conn.closed)
        if not close_conn:
            try:
                self._conn.rollback()
            except psycopg2.Error:
                close_conn = True
        self._pool.putconn(self._conn, close=close_conn)


def _connection_config():
    host = os.getenv('DB_HOST')
    port = os.getenv('DB_PORT', '5432')
    user = os.getenv('DB_USER')
    password = os.getenv('DB_PASSWORD')
    dbname = os.getenv('DB_NAME')

    missing = []
    if not host: missing.append('DB_HOST')
    if not user: missing.append('DB_USER')
    if not password: missing.append('DB_PASSWORD')
    if not dbname: missing.append('DB_NAME')

    if missing:
        error_msg = f'Missing required database environment variables: {", ".join(missing)}'
        logger.error(error_msg)
        raise ValueError(error_msg)

    return {
        'host': host,
        'port': port,
        'user': user,
        'password': password,
        'dbname': dbname,
        'cursor_factory': RealDictCursor,
        'connect_timeout': 10,
    }


def _log_connection_target(config):
    logger.info('=== Attempting DB connection ===')
    logger.info(
        f'Target: {config["user"]}@{config["host"]}:{config["port"]}/{config["dbname"]}'
    )


def _resolve_host_for_diagnostics(host):
    # Try to resolve the hostname first for better error messages
    try:
        logger.info(f'Resolving hostname: {host}')
        resolved_ip = socket.gethostbyname(host)
        logger.info(f'Hostname resolved to: {resolved_ip}')
    except socket.gaierror as e:
        logger.error(f'DNS resolution failed for {host}: {e}')
        # Continue anyway - psycopg2 might handle it differently


def _connect_direct(config):
    try:
        conn = psycopg2.connect(**config)
        logger.info('Database connection established successfully')
        return conn
    except psycopg2.OperationalError as e:
        error_str = str(e)
        logger.error(f'Database connection failed: {error_str}')

        # Provide helpful error diagnosis
        if 'could not connect to server' in error_str or 'Connection refused' in error_str:
            logger.error('>>> DIAGNOSIS: Database server unreachable')
            logger.error('    Check: Is PostgreSQL running? Is the host/port correct?')
            logger.error(
                '    Check: Security group allows inbound on port %s?',
                config['port'],
            )
        elif 'password authentication failed' in error_str:
            logger.error('>>> DIAGNOSIS: Invalid credentials')
            logger.error('    Check: DB_USER and DB_PASSWORD are correct')
        elif 'database' in error_str and 'does not exist' in error_str:
            logger.error('>>> DIAGNOSIS: Database does not exist')
            logger.error('    Check: DB_NAME is correct and database is created')
        elif 'timeout' in error_str.lower():
            logger.error('>>> DIAGNOSIS: Connection timeout')
            logger.error('    Check: Network connectivity, firewall rules, security groups')

        raise


def _pool_enabled():
    return os.getenv('DB_POOL_ENABLED', '1') != '0'


def _get_pool(config):
    global _pool
    if _pool is not None:
        return _pool

    with _pool_lock:
        if _pool is None:
            minconn = int(os.getenv('DB_POOL_MIN', '1'))
            maxconn = int(os.getenv('DB_POOL_MAX', '5'))
            logger.info(
                'Creating PostgreSQL connection pool: min=%s max=%s',
                minconn,
                maxconn,
            )
            _pool = ThreadedConnectionPool(minconn, maxconn, **config)
        return _pool


def get_db_connection():
    config = _connection_config()
    _log_connection_target(config)
    _resolve_host_for_diagnostics(config['host'])

    if not _pool_enabled():
        return _connect_direct(config)

    try:
        pool = _get_pool(config)
        conn = pool.getconn()
        if conn.closed:
            pool.putconn(conn, close=True)
            conn = pool.getconn()
        logger.info('Database pooled connection checked out successfully')
        return _PooledConnection(pool, conn)
    except psycopg2.OperationalError as e:
        error_str = str(e)
        logger.error(f'Database connection failed: {error_str}')
        if 'timeout' in error_str.lower():
            logger.error('>>> DIAGNOSIS: Connection timeout')
            logger.error('    Check: Network connectivity, firewall rules, security groups')
        raise


def execute_query(query, params=None, fetch_one=False):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(query, params)
            if query.strip().upper().startswith('SELECT'):
                return cursor.fetchone() if fetch_one else cursor.fetchall()
            conn.commit()
            return cursor.rowcount
    finally:
        conn.close()
