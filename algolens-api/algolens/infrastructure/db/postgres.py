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


def get_db_connection():
    host = os.getenv("DB_HOST")
    port = os.getenv("DB_PORT", "5432")
    user = os.getenv("DB_USER")
    password = os.getenv("DB_PASSWORD")
    dbname = os.getenv("DB_NAME")

    logger.info("=== Attempting DB connection ===")

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
        logger.error("Database configuration incomplete")
        raise ValueError(error_msg)

    try:
        logger.info("Resolving database hostname")
        socket.gethostbyname(host)
        logger.info("Database hostname resolved")
    except socket.gaierror:
        logger.error("Database hostname resolution failed")

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
    except psycopg2.OperationalError:
        logger.error("Database connection failed")
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
