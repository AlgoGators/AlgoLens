"""Postgres connection utilities."""

import logging
import os
from pathlib import Path
import socket

from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor

ENV_PATH = Path(__file__).resolve().parents[3] / ".env"
load_dotenv(dotenv_path=ENV_PATH)

logger = logging.getLogger(__name__)

logger.info("=== Database module loaded ===")
logger.info("DB_HOST: %s", os.getenv("DB_HOST"))
logger.info("DB_PORT: %s", os.getenv("DB_PORT", "5432"))
logger.info("DB_NAME: %s", os.getenv("DB_NAME"))
logger.info("DB_USER: %s", os.getenv("DB_USER"))
logger.info(
    "DB_PASSWORD set: %s",
    "Yes" if os.getenv("DB_PASSWORD") else "NO - THIS WILL FAIL",
)


def get_db_connection():
    host = os.getenv("DB_HOST")
    port = os.getenv("DB_PORT", "5432")
    user = os.getenv("DB_USER")
    password = os.getenv("DB_PASSWORD")
    dbname = os.getenv("DB_NAME")

    logger.info("=== Attempting DB connection ===")
    logger.info("Target: %s@%s:%s/%s", user, host, port, dbname)

    missing = []
    if not host:
        missing.append("DB_HOST")
    if not user:
        missing.append("DB_USER")
    if not password:
        missing.append("DB_PASSWORD")
    if not dbname:
        missing.append("DB_NAME")

    if missing:
        error_msg = (
            "Missing required database environment variables: " + ", ".join(missing)
        )
        logger.error(error_msg)
        raise ValueError(error_msg)

    try:
        logger.info("Resolving hostname: %s", host)
        resolved_ip = socket.gethostbyname(host)
        logger.info("Hostname resolved to: %s", resolved_ip)
    except socket.gaierror as exc:
        logger.error("DNS resolution failed for %s: %s", host, exc)

    try:
        conn = psycopg2.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            dbname=dbname,
            cursor_factory=RealDictCursor,
            connect_timeout=10,
        )
        logger.info("Database connection established successfully")
        return conn
    except psycopg2.OperationalError as exc:
        error_str = str(exc)
        logger.error("Database connection failed: %s", error_str)

        if "could not connect to server" in error_str or "Connection refused" in error_str:
            logger.error(">>> DIAGNOSIS: Database server unreachable")
            logger.error("    Check: Is PostgreSQL running? Is the host/port correct?")
            logger.error(
                "    Check: Security group allows inbound on port %s?", port
            )
        elif "password authentication failed" in error_str:
            logger.error(">>> DIAGNOSIS: Invalid credentials")
            logger.error("    Check: DB_USER and DB_PASSWORD are correct")
        elif "database" in error_str and "does not exist" in error_str:
            logger.error(">>> DIAGNOSIS: Database does not exist")
            logger.error("    Check: DB_NAME is correct and database is created")
        elif "timeout" in error_str.lower():
            logger.error(">>> DIAGNOSIS: Connection timeout")
            logger.error(
                "    Check: Network connectivity, firewall rules, security groups"
            )

        raise


def execute_query(query, params=None, fetch_one=False):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(query, params)
            if query.strip().upper().startswith("SELECT"):
                return cursor.fetchone() if fetch_one else cursor.fetchall()
            conn.commit()
            return cursor.rowcount
    finally:
        conn.close()
