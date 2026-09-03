-- Local demo database for AlgoLens development.
--
-- Three strategies across two books, 90 days of three-stream equity, open
-- positions, executions, risk envelopes, and an admin login. Run against a
-- throwaway Postgres:
--
--   psql -h 127.0.0.1 -p 55432 -U algolens -d postgres -f scripts/demo_seed.sql
--
-- The trading schema here mirrors what trade-ngin owns in production closely
-- enough for every AlgoLens read AND write path to run. Four columns and
-- indexes below were missing from the first version of this seed and each hid
-- a real bug until added -- see the comments marked REQUIRED.
--
-- The demo login is admin@admin.com / admin. It exists only in this database.

-- Local demo data for AlgoLens qt-platform-preview.
-- Three strategies spread across two portfolios, so the strategy -> portfolio
-- mapping and the per-portfolio roll-up are both visible.

CREATE DATABASE algolens_demo;
\c algolens_demo

CREATE SCHEMA IF NOT EXISTS trading;
CREATE SCHEMA IF NOT EXISTS auth;

CREATE TABLE auth.users (
    id            SERIAL PRIMARY KEY,
    email         TEXT UNIQUE NOT NULL,
    password_hash TEXT,
    first_name    TEXT,
    last_name     TEXT,
    role          TEXT NOT NULL DEFAULT 'admin',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE trading.strategy_registry (
    id                    TEXT PRIMARY KEY,
    strategy_type         TEXT NOT NULL,
    portfolio_id          TEXT NOT NULL,
    name                  TEXT NOT NULL,
    description           TEXT,
    initial_equity        NUMERIC,
    managers              TEXT[],
    is_active             BOOLEAN NOT NULL DEFAULT TRUE,
    lifecycle             TEXT NOT NULL DEFAULT 'live',
    sort_order            INT  NOT NULL DEFAULT 0,
    mock_capital          NUMERIC,
    incubation_started_at TIMESTAMPTZ
);

CREATE TABLE trading.equity_curve (
    id             SERIAL           PRIMARY KEY,
    strategy_id    VARCHAR          NOT NULL,
    timestamp      TIMESTAMPTZ      NOT NULL,
    equity         DOUBLE PRECISION NOT NULL,
    portfolio_id   VARCHAR,
    portfolio_type TEXT             NOT NULL DEFAULT 'system',
    CONSTRAINT trading_equity_curve_unique
        UNIQUE (portfolio_id, strategy_id, "timestamp", portfolio_type)
);

-- The shape trade-ngin actually ships: the baseline in
-- trade-ngin/migrations/test_001_migration.sh, plus what migrations 001 and 003
-- do to it. This used to be a looser invention -- nullable price, no
-- last_update, no PnL columns -- and the difference silently hid a write path
-- that could not insert a row into the real thing at all.
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
    CONSTRAINT positions_portfolio_type_check
        CHECK (portfolio_type IN ('system','qt','benchmark',
                                  'benchmark_rebench','benchmark_frozen_shadow')),
    CONSTRAINT positions_pkey
        PRIMARY KEY (portfolio_id, strategy_id, strategy_name, date, symbol, portfolio_type)
);

CREATE TABLE trading.executions (
    id               BIGSERIAL PRIMARY KEY,
    strategy_id      TEXT NOT NULL,
    portfolio_id     TEXT NOT NULL,
    symbol           TEXT NOT NULL,
    side             TEXT NOT NULL,
    quantity         NUMERIC NOT NULL,
    price            NUMERIC NOT NULL,
    execution_time   TIMESTAMPTZ NOT NULL,
    commissions_fees NUMERIC DEFAULT 0
);

CREATE TABLE trading.live_results (
    id                      BIGSERIAL PRIMARY KEY,
    config                  JSONB NOT NULL,
    portfolio_id            TEXT NOT NULL,
    date                    DATE NOT NULL,
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
    cash_available          NUMERIC
);

-- ---------------------------------------------------------------------------
-- Market data, owned by data-ngin.
--
-- futures_data.ohlcv_1d is where the price pipeline writes daily bars, and
-- metadata.contract_metadata is where contract sizes live. AlgoLens reads both
-- with the same queries trade-ngin uses. Without them the position view has no
-- market price and no contract size, and says so rather than falling back to
-- the entry price -- which is what it used to do under a column labelled
-- "Market Price".
--
-- Symbols carry the continuous-contract suffix (ES.v.0) exactly as data-ngin
-- writes them and trading.positions stores them.
-- ---------------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS futures_data;
CREATE SCHEMA IF NOT EXISTS metadata;

CREATE TABLE futures_data.ohlcv_1d (
    time   TIMESTAMPTZ      NOT NULL,
    symbol TEXT             NOT NULL,
    open   DOUBLE PRECISION NOT NULL,
    high   DOUBLE PRECISION NOT NULL,
    low    DOUBLE PRECISION NOT NULL,
    close  DOUBLE PRECISION NOT NULL,
    volume BIGINT           NOT NULL,
    PRIMARY KEY (time, symbol)
);

-- Quoted, mixed-case column names, because that is how the table is really
-- spelled: trade-ngin's InstrumentRegistry reads "Contract Size" keyed on
-- "Databento Symbol".
CREATE TABLE metadata.contract_metadata (
    "Databento Symbol" TEXT PRIMARY KEY,
    "IB Symbol"        TEXT,
    "Name"             TEXT,
    "Asset Type"       TEXT,
    "Exchange"         TEXT,
    "Contract Size"    DOUBLE PRECISION,
    "Tick Size"        TEXT
);

-- Contract sizes as published by the exchanges, matching the fallback table in
-- trade-ngin (src/core/email_sender.cpp).
INSERT INTO metadata.contract_metadata
  ("Databento Symbol", "IB Symbol", "Name", "Asset Type", "Exchange", "Contract Size")
VALUES
  ('ES','ES','E-mini S&P 500','FUTURE','CME',50),
  ('NQ','NQ','E-mini Nasdaq 100','FUTURE','CME',20),
  ('RTY','RTY','E-mini Russell 2000','FUTURE','CME',50),
  ('CL','CL','Crude Oil','FUTURE','NYMEX',1000),
  ('GC','GC','Gold','FUTURE','COMEX',100),
  ('SI','SI','Silver','FUTURE','COMEX',5000),
  ('NG','NG','Natural Gas','FUTURE','NYMEX',10000),
  ('ZN','ZN','10-Year T-Note','FUTURE','CBOT',100000),
  ('ZB','ZB','30-Year T-Bond','FUTURE','CBOT',100000),
  ('ZS','ZS','Soybeans','FUTURE','CBOT',5000),
  ('6E','6E','Euro FX','FUTURE','CME',125000);

-- 30 days of daily bars for the symbols the demo holds.
INSERT INTO futures_data.ohlcv_1d (time, symbol, open, high, low, close, volume)
SELECT (CURRENT_DATE - d)::timestamptz,
       m.sym,
       m.px * (1 + 0.002 * sin(d / 3.0)),
       m.px * (1 + 0.006 * sin(d / 3.0)),
       m.px * (1 - 0.006 * sin(d / 3.0)),
       m.px * (1 + 0.004 * sin(d / 4.0)),
       100000 + d * 37
FROM generate_series(0, 29) d
CROSS JOIN (VALUES
    ('ES.v.0', 5310.75), ('NQ.v.0', 18512.25), ('CL.v.0', 79.10),
    ('GC.v.0', 2437.60), ('ZN.v.0', 112.35), ('6E.v.0', 1.0915),
    ('ZS.v.0', 1051.50), ('RTY.v.0', 2298.40), ('NG.v.0', 2.958),
    ('ZB.v.0', 119.20), ('SI.v.0', 31.85)
) AS m(sym, px);

-- From trade-ngin migration 004, constraints included. The first version of
-- this seed left every column nullable and untyped, which meant a write that
-- production would refuse (a NULL before_state, a blank reason, a non-numeric
-- user id) sailed through here. The point of a demo schema is to be refused
-- by the same things.
CREATE TABLE trading.position_overrides (
    id                BIGSERIAL PRIMARY KEY,
    user_id           INTEGER NOT NULL,
    source_app        TEXT NOT NULL
                      CHECK (source_app IN ('algolens', 'manual_db_edit')),
    strategy_id       TEXT NOT NULL,
    symbol            TEXT NOT NULL,
    before_state      JSONB NOT NULL,
    after_state       JSONB NOT NULL,
    reason            TEXT NOT NULL
                      CHECK (length(btrim(reason)) > 0),
    risk_check_result JSONB NOT NULL,
    overrode_risk     BOOLEAN NOT NULL DEFAULT FALSE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- From trade-ngin migration 005
CREATE TABLE trading.risk_limits (
    id           BIGSERIAL PRIMARY KEY,
    strategy_id  TEXT NOT NULL,
    portfolio_id TEXT NOT NULL,
    limits       JSONB NOT NULL,
    published_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Three strategies, two portfolios. CONSERVATIVE holds two; AGGRESSIVE holds one.
-- ---------------------------------------------------------------------------
INSERT INTO trading.strategy_registry
  (id, strategy_type, portfolio_id, name, description, initial_equity, managers, is_active, lifecycle, sort_order)
VALUES
  ('trendfollowing', 'LIVE_TREND_FOLLOWING', 'CONSERVATIVE_PORTFOLIO',
   'Trend Following', 'Systematic trend following across global futures', 500000,
   ARRAY['Dominick Dupuy'], TRUE, 'live', 0),
  ('carry', 'LIVE_CARRY', 'CONSERVATIVE_PORTFOLIO',
   'Carry', 'Cross-asset carry harvesting', 250000,
   ARRAY['Xander Robbins'], TRUE, 'live', 1),
  ('breakout', 'LIVE_BREAKOUT', 'AGGRESSIVE_PORTFOLIO',
   'Breakout', 'Short-horizon volatility breakout', 300000,
   ARRAY['John Riley'], TRUE, 'live', 2);

-- Equity curves: 90 days, three streams each. qt and system are identical
-- (nothing has edited qt yet); benchmark diverges slightly so the attribution
-- chart has something real to draw.
INSERT INTO trading.equity_curve (strategy_id, portfolio_id, portfolio_type, timestamp, equity)
SELECT r.strategy_type, r.portfolio_id, s.stream,
       (CURRENT_DATE - (89 - d))::timestamptz,
       r.initial_equity
         * (1 + (d * r.drift) + 0.012 * sin(d / 6.0) + CASE WHEN s.stream = 'benchmark' THEN -0.0004 * d ELSE 0 END)
FROM (VALUES
        ('LIVE_TREND_FOLLOWING', 'CONSERVATIVE_PORTFOLIO', 500000.0, 0.00090),
        ('LIVE_CARRY',           'CONSERVATIVE_PORTFOLIO', 250000.0, 0.00055),
        ('LIVE_BREAKOUT',        'AGGRESSIVE_PORTFOLIO',   300000.0, 0.00125)
     ) AS r(strategy_type, portfolio_id, initial_equity, drift)
CROSS JOIN (VALUES ('qt'), ('system'), ('benchmark')) AS s(stream)
CROSS JOIN generate_series(0, 89) AS d;

-- Open positions (qt stream = the real book)
INSERT INTO trading.positions
  (strategy_id, strategy_name, portfolio_id, portfolio_type, symbol, quantity, average_price,
   daily_unrealized_pnl, daily_realized_pnl, date, last_update, updated_at)
VALUES
  ('LIVE_TREND_FOLLOWING','Trend Following','CONSERVATIVE_PORTFOLIO','qt','ES.v.0',  12, 5280.25,  4210.00,  980.00, CURRENT_DATE, now(), now()),
  ('LIVE_TREND_FOLLOWING','Trend Following','CONSERVATIVE_PORTFOLIO','qt','NQ.v.0',   5,18420.50,  2380.00, -410.00, CURRENT_DATE, now(), now()),
  ('LIVE_TREND_FOLLOWING','Trend Following','CONSERVATIVE_PORTFOLIO','qt','CL.v.0', -18,   78.40, -1150.00,  260.00, CURRENT_DATE, now(), now()),
  ('LIVE_TREND_FOLLOWING','Trend Following','CONSERVATIVE_PORTFOLIO','qt','GC.v.0',   7, 2418.90,   890.00,  120.00, CURRENT_DATE, now(), now()),
  ('LIVE_CARRY','Carry','CONSERVATIVE_PORTFOLIO','qt','ZN.v.0',  40,  111.85,  1420.00,  310.00, CURRENT_DATE, now(), now()),
  ('LIVE_CARRY','Carry','CONSERVATIVE_PORTFOLIO','qt','6E.v.0', -22,    1.087, -640.00,   85.00, CURRENT_DATE, now(), now()),
  ('LIVE_CARRY','Carry','CONSERVATIVE_PORTFOLIO','qt','ZS.v.0',  15, 1042.25,   510.00,  -70.00, CURRENT_DATE, now(), now()),
  ('LIVE_BREAKOUT','Breakout','AGGRESSIVE_PORTFOLIO','qt','RTY.v.0', 9, 2285.60, 1980.00, 440.00, CURRENT_DATE, now(), now()),
  ('LIVE_BREAKOUT','Breakout','AGGRESSIVE_PORTFOLIO','qt','NG.v.0', -30,    2.914, -820.00, 150.00, CURRENT_DATE, now(), now());

-- Yesterday's snapshot, so the "finalized positions" panel has something
INSERT INTO trading.positions
  (strategy_id, strategy_name, portfolio_id, portfolio_type, symbol, quantity, average_price,
   daily_unrealized_pnl, daily_realized_pnl, date, last_update, updated_at)
SELECT strategy_id, strategy_name, portfolio_id, portfolio_type, symbol,
       quantity, average_price, daily_unrealized_pnl, daily_realized_pnl,
       CURRENT_DATE - 1, now() - INTERVAL '1 day', now() - INTERVAL '1 day'
FROM trading.positions
WHERE date = CURRENT_DATE;

INSERT INTO trading.executions
  (strategy_id, portfolio_id, symbol, side, quantity, price, execution_time, commissions_fees)
VALUES
  ('LIVE_TREND_FOLLOWING','CONSERVATIVE_PORTFOLIO','ES','BUY',  4, 5276.00, now() - INTERVAL '3 hours',  9.20),
  ('LIVE_TREND_FOLLOWING','CONSERVATIVE_PORTFOLIO','CL','SELL', 6,   78.62, now() - INTERVAL '6 hours', 11.40),
  ('LIVE_CARRY','CONSERVATIVE_PORTFOLIO','ZN','BUY', 10, 111.79, now() - INTERVAL '5 hours',  7.80),
  ('LIVE_BREAKOUT','AGGRESSIVE_PORTFOLIO','RTY','BUY', 3, 2281.10, now() - INTERVAL '2 hours', 6.10);

INSERT INTO trading.live_results
  (config, portfolio_id, date, current_portfolio_value, total_annualized_return, total_cumulative_return,
   volatility, daily_return, gross_leverage, net_leverage, portfolio_leverage, margin_posted,
   equity_to_margin_ratio, margin_cushion, gross_notional, total_unrealized_pnl, total_realized_pnl,
   total_transaction_costs, cash_available)
VALUES
  ('{"strategy_type":"LIVE_TREND_FOLLOWING"}','CONSERVATIVE_PORTFOLIO',CURRENT_DATE,
   541200, 18.40, 8.24, 12.60, 0.34, 1.82, 1.15, 1.82, 148000, 3.66, 72.7, 985000, 6330, 950, 412, 393200),
  ('{"strategy_type":"LIVE_CARRY"}','CONSERVATIVE_PORTFOLIO',CURRENT_DATE,
   262750, 11.20, 5.10, 7.90, 0.12, 1.24, 0.86, 1.24, 61000, 4.31, 76.8, 326000, 1290, 325, 178, 201750),
  ('{"strategy_type":"LIVE_BREAKOUT"}','AGGRESSIVE_PORTFOLIO',CURRENT_DATE,
   334800, 26.90, 11.60, 21.30, -0.28, 2.41, 1.63, 2.41, 96000, 3.49, 71.3, 807000, 1160, 590, 233, 238800);

-- Risk envelopes, so the gate actually gates. ES is capped low on purpose:
-- the demo book already sits near it, so a small increase trips a breach.
-- Leverage here is NOTIONAL leverage on futures, where gross exposure is many
-- times equity by design, so the limits are set well above 1x. The per-symbol
-- contract cap is the one tuned to trip in the demo.
-- The shape the engine actually publishes, per trade-ngin's store_risk_limits:
-- per-symbol caps in CONTRACTS, and leverage ratios. It deliberately does NOT
-- publish max_gross_notional or max_position_count, because it does not enforce
-- them. This seed used to invent exactly those two keys plus a
-- max_symbol_notional, which made a gate that checks keys the engine never
-- writes look like it was working.
INSERT INTO trading.risk_limits (strategy_id, portfolio_id, limits) VALUES
  ('LIVE_TREND_FOLLOWING','CONSERVATIVE_PORTFOLIO',
   '{"max_symbol_position_contracts": {"ES": 10, "NQ": 8},
     "max_gross_leverage": 20.0, "max_net_leverage": 20.0}'::jsonb),
  ('LIVE_CARRY','CONSERVATIVE_PORTFOLIO',
   '{"max_symbol_position_contracts": {"ZN": 50},
     "max_gross_leverage": 20.0, "max_net_leverage": 20.0}'::jsonb),
  ('LIVE_BREAKOUT','AGGRESSIVE_PORTFOLIO',
   '{"max_symbol_position_contracts": {"RTY": 12, "NG": 40},
     "max_gross_leverage": 25.0, "max_net_leverage": 25.0}'::jsonb);

-- admin login (werkzeug scrypt hash of 'admin')
INSERT INTO auth.users (email, password_hash, first_name, last_name, role)
VALUES ('admin@admin.com', 'scrypt:32768:8:1$iZQP0LmCyyfY1MEI$975dc2232135c7f701b49a07425efb426d141f09256d3fd1a650e2bfa043e0989256e2319a30f8489cb96792098966a1bc913e423411a000d6df389e1f599339', 'Local', 'Admin', 'admin');

-- ---------------------------------------------------------------------------
-- REQUIRED: schema the write paths depend on. Each of these was absent from
-- the first seed and surfaced as a 500 only when the feature was driven.
-- ---------------------------------------------------------------------------

-- write_qt_position upserts on this exact key. Without the index Postgres
-- rejects the ON CONFLICT clause outright.
-- The primary key above already is the uniqueness the ON CONFLICT clause
-- targets, so no extra index is needed here any more.

-- Incubation start/promote/retire touch updated_at and the lifecycle log.
ALTER TABLE trading.strategy_registry ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();
CREATE TABLE IF NOT EXISTS trading.strategy_lifecycle_log (
    id           BIGSERIAL PRIMARY KEY,
    strategy_id  TEXT NOT NULL,
    before_state TEXT,
    after_state  TEXT,
    reason       TEXT,
    user_id      TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Books, membership and the assignment audit are NOT created here. They belong
-- to trade-ngin migration 009_books_and_membership.sql, and the application no
-- longer creates them lazily. After running this file:
--
--   psql ... -f ../trade-ngin/migrations/009_books_and_membership.sql
--
-- 009 also seeds membership from strategy_registry, so every strategy starts in
-- the book it already names.
