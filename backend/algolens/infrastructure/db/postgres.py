"""Compatibility wrappers around the existing database module."""

from database import execute_query, get_db_connection

__all__ = ["execute_query", "get_db_connection"]
