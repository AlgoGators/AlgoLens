"""A throwaway Postgres schema in the shape of new_algo_data after 021-023.

Opt-in: used only when ALGOLENS_TEST_DATABASE_URL points at a THROWAWAY
Postgres on localhost (it DROPs and recreates the trading, metadata and
futures_data schemas). For example:

    docker run -d --rm --name al-qt-pg -e POSTGRES_PASSWORD=test -p 55440:5432 postgres:16
    ALGOLENS_TEST_DATABASE_URL=postgresql://postgres:test@localhost:55440/postgres \
        python -m pytest tests/test_qt_integration.py -q

Shapes:
  * trading.positions / equity_curve: trade-ngin migrations/test_001_migration.sh
    after 001 (portfolio_type in the key) and 016 (instrument_id).
  * trading.executions / live_results: the pre-021 keys 021 looks for.
  * 021 (books) is emulated as its migration states (branch qt/e1-book-storage
    was not pushed when this was written): portfolio_type CHECK widened to
    ('system','qt_proposal','qt'); portfolio_type on executions and
    live_results, last in their keys; positions.moved_by (qt rows only).
  * 022 and 023 are the engine's own files, vendored under fixtures/sql.
"""

import os
from pathlib import Path
from urllib.parse import urlparse

import pytest

DB_URL = os.environ.get("ALGOLENS_TEST_DATABASE_URL")
SQL_DIR = Path(__file__).parent / "fixtures" / "sql"

requires_db = pytest.mark.skipif(
    not DB_URL, reason="ALGOLENS_TEST_DATABASE_URL not set (needs a throwaway Postgres)"
)

BASE_SCHEMA = """
DROP SCHEMA IF EXISTS trading CASCADE;
DROP SCHEMA IF EXISTS metadata CASCADE;
DROP SCHEMA IF EXISTS futures_data CASCADE;
CREATE SCHEMA trading;
CREATE SCHEMA metadata;
CREATE SCHEMA futures_data;

CREATE TABLE trading.positions (
    symbol               VARCHAR     NOT NULL,
    quantity             NUMERIC     NOT NULL,
    average_price        NUMERIC     NOT NULL,
    daily_unrealized_pnl NUMERIC     NOT NULL,
    daily_realized_pnl   NUMERIC     NOT NULL,
    last_update          TIMESTAMPTZ NOT NULL,
    updated_at           TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    strategy_id          VARCHAR     NOT NULL,
    strategy_name        VARCHAR     NOT NULL,
    date                 DATE        NOT NULL,
    portfolio_id         VARCHAR     NOT NULL,
    portfolio_type       TEXT        NOT NULL DEFAULT 'system',
    instrument_id        TEXT,
    CONSTRAINT positions_portfolio_type_check CHECK (portfolio_type IN ('system', 'qt')),
    CONSTRAINT positions_pkey PRIMARY KEY
        (portfolio_id, strategy_id, strategy_name, date, symbol, portfolio_type)
);

CREATE TABLE trading.equity_curve (
    id             SERIAL PRIMARY KEY,
    strategy_id    VARCHAR          NOT NULL,
    timestamp      TIMESTAMPTZ      NOT NULL,
    equity         DOUBLE PRECISION NOT NULL,
    portfolio_id   VARCHAR,
    portfolio_type TEXT NOT NULL DEFAULT 'system',
    CONSTRAINT equity_curve_portfolio_type_check CHECK (portfolio_type IN ('system', 'qt')),
    CONSTRAINT trading_equity_curve_unique
        UNIQUE (portfolio_id, strategy_id, "timestamp", portfolio_type)
);

CREATE TABLE trading.executions (
    portfolio_id     VARCHAR NOT NULL,
    strategy_id      VARCHAR NOT NULL,
    strategy_name    VARCHAR NOT NULL,
    date             DATE    NOT NULL,
    exec_id          TEXT    NOT NULL,
    symbol           TEXT,
    side             TEXT,
    quantity         NUMERIC,
    price            NUMERIC,
    execution_time   TIMESTAMPTZ,
    commissions_fees NUMERIC,
    CONSTRAINT executions_pkey PRIMARY KEY (portfolio_id, strategy_id, strategy_name, date, exec_id)
);

CREATE TABLE trading.live_results (
    id                      SERIAL PRIMARY KEY,
    strategy_id             VARCHAR(100) NOT NULL,
    portfolio_id            VARCHAR(100) NOT NULL,
    date                    DATE NOT NULL,
    config                  JSONB,
    current_portfolio_value NUMERIC,
    total_annualized_return NUMERIC,
    total_cumulative_return NUMERIC,
    volatility              NUMERIC,
    daily_return            NUMERIC,
    gross_leverage          NUMERIC,
    net_leverage            NUMERIC,
    portfolio_leverage      NUMERIC,
    margin_posted           NUMERIC,
    equity_to_margin_ratio  NUMERIC,
    margin_cushion          NUMERIC,
    gross_notional          NUMERIC,
    total_unrealized_pnl    NUMERIC,
    total_realized_pnl      NUMERIC,
    total_transaction_costs NUMERIC,
    cash_available          NUMERIC,
    risk_scale              NUMERIC,
    risk_detail             JSONB,
    CONSTRAINT live_results_key UNIQUE (portfolio_id, strategy_id, date)
);

CREATE TABLE trading.live_run_metadata (
    id                   SERIAL PRIMARY KEY,
    date                 DATE NOT NULL,
    strategy_id          TEXT NOT NULL,
    portfolio_id         TEXT NOT NULL,
    strategy_allocations JSONB,
    portfolio_config     JSONB,
    strategy_configs     JSONB,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT live_run_metadata_key UNIQUE (date, strategy_id, portfolio_id)
);

-- AlgoLens migrations 001 + 002.
CREATE TABLE trading.strategy_registry (
    id             TEXT PRIMARY KEY,
    strategy_type  TEXT NOT NULL,
    portfolio_id   TEXT NOT NULL,
    name           TEXT NOT NULL,
    description    TEXT NOT NULL DEFAULT '',
    initial_equity NUMERIC NOT NULL DEFAULT 500000,
    managers       JSONB NOT NULL DEFAULT '["AlgoLens System"]'::jsonb,
    is_active      BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order     INTEGER NOT NULL DEFAULT 0,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    lifecycle      TEXT NOT NULL DEFAULT 'live' CHECK (lifecycle IN ('incubating', 'live', 'retired')),
    incubation_started_at TIMESTAMPTZ,
    mock_capital   NUMERIC
);
INSERT INTO trading.strategy_registry (id, strategy_type, portfolio_id, name)
VALUES ('trendfollowing', 'LIVE_TREND_FOLLOWING', 'CONSERVATIVE_PORTFOLIO', 'Trend Following'),
       ('equity_mr', 'LIVE_EQUITY_MEAN_REVERSION', 'EQUITY_MR_PORTFOLIO', 'Equity MR');

CREATE TABLE metadata.contract_metadata (
    "Databento Symbol" TEXT NOT NULL,
    "IB Symbol"        TEXT NOT NULL,
    "Name"             TEXT NOT NULL,
    "Exchange"         TEXT NOT NULL,
    "Asset Type"       TEXT NOT NULL,
    "Sector"           TEXT NOT NULL,
    "Contract Size"    TEXT NOT NULL,
    "Fee Per Contract" TEXT NOT NULL DEFAULT '1.50'
);

-- futures_data.ohlcv_1d has no key; one (symbol, time) may be stored twice.
CREATE TABLE futures_data.ohlcv_1d (
    time   TIMESTAMPTZ NOT NULL,
    symbol TEXT NOT NULL,
    open   DOUBLE PRECISION,
    high   DOUBLE PRECISION,
    low    DOUBLE PRECISION,
    close  DOUBLE PRECISION,
    volume DOUBLE PRECISION
);
"""

EMULATED_021 = """
BEGIN;
ALTER TABLE trading.positions DROP CONSTRAINT positions_portfolio_type_check;
ALTER TABLE trading.positions ADD CONSTRAINT positions_portfolio_type_check
    CHECK (portfolio_type IN ('system', 'qt_proposal', 'qt'));
ALTER TABLE trading.equity_curve DROP CONSTRAINT equity_curve_portfolio_type_check;
ALTER TABLE trading.equity_curve ADD CONSTRAINT equity_curve_portfolio_type_check
    CHECK (portfolio_type IN ('system', 'qt_proposal', 'qt'));
ALTER TABLE trading.executions ADD COLUMN portfolio_type TEXT NOT NULL DEFAULT 'system'
    CHECK (portfolio_type IN ('system', 'qt_proposal', 'qt'));
ALTER TABLE trading.executions DROP CONSTRAINT executions_pkey;
ALTER TABLE trading.executions ADD CONSTRAINT executions_pkey
    PRIMARY KEY (portfolio_id, strategy_id, strategy_name, date, exec_id, portfolio_type);
ALTER TABLE trading.live_results ADD COLUMN portfolio_type TEXT NOT NULL DEFAULT 'system'
    CHECK (portfolio_type IN ('system', 'qt_proposal', 'qt'));
ALTER TABLE trading.live_results DROP CONSTRAINT live_results_key;
ALTER TABLE trading.live_results ADD CONSTRAINT live_results_key
    UNIQUE (portfolio_id, strategy_id, date, portfolio_type);
ALTER TABLE trading.positions ADD COLUMN moved_by TEXT;
ALTER TABLE trading.positions ADD CONSTRAINT positions_moved_by_qt_only
    CHECK (moved_by IS NULL OR portfolio_type = 'qt');
COMMIT;
"""


def assert_local(url):
    host = urlparse(url).hostname
    assert host in {"localhost", "127.0.0.1", "::1"}, (
        f"refusing to drop schemas on non-local host {host!r}"
    )


def build_schema(cursor):
    cursor.execute(BASE_SCHEMA)
    cursor.execute(EMULATED_021)
    cursor.execute((SQL_DIR / "022_strategy_config.sql").read_text(encoding="utf-8"))
    cursor.execute((SQL_DIR / "023_qt_command_log.sql").read_text(encoding="utf-8"))


def drop_schema(cursor):
    cursor.execute(
        "DROP SCHEMA IF EXISTS trading CASCADE;"
        "DROP SCHEMA IF EXISTS metadata CASCADE;"
        "DROP SCHEMA IF EXISTS futures_data CASCADE;"
    )


@pytest.fixture
def qt_db():
    """(connection factory, autocommit setup connection) on a fresh schema."""
    import psycopg2
    from psycopg2.extras import RealDictCursor

    import algolens.infrastructure.portfolio.repositories as repo_module

    assert_local(DB_URL)
    repo_module._has_portfolio_type_cache = None
    repo_module._has_portfolio_type_expires_at = 0

    setup = psycopg2.connect(DB_URL, cursor_factory=RealDictCursor)
    setup.autocommit = True
    with setup.cursor() as cur:
        build_schema(cur)

    def factory():
        return psycopg2.connect(DB_URL, cursor_factory=RealDictCursor)

    factory.setup = setup
    yield factory

    with setup.cursor() as cur:
        drop_schema(cur)
    setup.close()
    repo_module._has_portfolio_type_cache = None
