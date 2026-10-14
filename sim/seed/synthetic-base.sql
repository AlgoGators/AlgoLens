-- The synthetic fixture's base: the tables trade-ngin's QT migrations (021 on) build on, in the
-- shape new_algo_data had after trade-ngin 001 and 016, plus AlgoLens' auth.users.
--
-- Copied from algolens-api/tests/qt_fixture.py (BASE_SCHEMA) and
-- algolens-api/tests/test_screen_access_integration.py (AUTH_SCHEMA), without their test rows
-- and roles. build-synthetic.sh puts trade-ngin's migrations and AlgoLens' 003 after it.

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
    -- Not in the AlgoLens fixture; the scheduler reads it (book_written_at), prod has it.
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
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

DROP SCHEMA IF EXISTS investor CASCADE;
DROP SCHEMA IF EXISTS auth CASCADE;
CREATE SCHEMA auth;
CREATE TYPE auth.user_role AS ENUM ('general_member', 'team_lead', 'exec_board');
CREATE TABLE auth.users (
    id            SERIAL PRIMARY KEY,
    email         VARCHAR(120) NOT NULL UNIQUE,
    password_hash VARCHAR(256) NOT NULL DEFAULT '',
    created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    role          auth.user_role NOT NULL,
    first_name    VARCHAR(120) NOT NULL DEFAULT '',
    last_name     VARCHAR(120) NOT NULL DEFAULT ''
);
