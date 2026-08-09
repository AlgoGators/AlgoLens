"""Runtime dependency composition for HTTP adapters."""

import os

from werkzeug.security import check_password_hash, generate_password_hash

from algolens.infrastructure.db.postgres import execute_query, get_db_connection
from algolens.infrastructure.identity.dev_config import EnvironmentDevAuthConfig
from algolens.infrastructure.identity.repositories import PostgresUserRepository
from algolens.infrastructure.identity.security import WerkzeugPasswordHasher
from algolens.infrastructure.identity.sessions import FlaskJwtSessionIssuer
from algolens.infrastructure.portfolio.cache import CachedPortfolioReader
from algolens.infrastructure.portfolio.repositories import PostgresPortfolioRepository
from algolens.infrastructure.portfolio.strategy_registry import PostgresStrategyRegistry

_portfolio_reader = None
_portfolio_reader_ttl_seconds = None


def create_identity_dependencies():
    users = PostgresUserRepository(
        execute_query_func=execute_query,
        connection_factory=get_db_connection,
    )
    hasher = WerkzeugPasswordHasher(
        verify_func=check_password_hash,
        hash_func=generate_password_hash,
    )
    sessions = FlaskJwtSessionIssuer()
    return users, hasher, sessions


def create_portfolio_dependencies():
    global _portfolio_reader, _portfolio_reader_ttl_seconds

    reader = PostgresPortfolioRepository()
    ttl_seconds = float(os.getenv("PORTFOLIO_CACHE_TTL_SECONDS", "30"))
    if ttl_seconds > 0:
        if _portfolio_reader is None or _portfolio_reader_ttl_seconds != ttl_seconds:
            _portfolio_reader = CachedPortfolioReader(reader, ttl_seconds=ttl_seconds)
            _portfolio_reader_ttl_seconds = ttl_seconds
        reader = _portfolio_reader
    return PostgresStrategyRegistry(), reader


def create_dev_auth_config():
    return EnvironmentDevAuthConfig()
