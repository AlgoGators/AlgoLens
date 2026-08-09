"""Compatibility shim for legacy database imports."""

from algolens.infrastructure.db.postgres import execute_query, get_db_connection

__all__ = ["execute_query", "get_db_connection"]
