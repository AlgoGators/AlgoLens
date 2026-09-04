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

-- This table used to be a reconstruction: the columns AlgoLens reads, and
-- nothing else, guessed at from the reads. It is no longer a guess. The
-- engine's two writers name every column explicitly, and this DDL is their
-- union:
--
--   trade-ngin/src/data/postgres_database.cpp
--       store_live_results() -- the fixed INSERT, and the ON CONFLICT target
--       (portfolio_id, strategy_id, date) that gives the table its real key
--   trade-ngin/src/data/postgres_database_extensions.cpp
--       store_live_results_complete() -- builds its column list from the
--       metric maps the runner passes it
--   trade-ngin/apps/strategies/live_portfolio_runner.cpp:2930
--       the metric maps themselves, which is where the column NAMES come from
--   trade-ngin/src/live/live_data_loader.cpp:167
--       the engine's own SELECT, which reads them back
--
-- Two things this exposes that the reconstruction hid:
--
--   strategy_id is a real column and part of the table's uniqueness. AlgoLens
--   reads config->>'strategy_type' instead and never touches it, so the
--   reconstruction dropped it entirely -- and with it the constraint that
--   stops two rows existing for one strategy-book-day.
--
--   The engine publishes sharpe_ratio, sortino_ratio, max_drawdown, win_rate,
--   avg_win, avg_loss, profit_factor, best_day and worst_day. AlgoLens
--   recomputes all nine from the equity curve. They are seeded here so the two
--   can be compared instead of only one of them existing.
CREATE TABLE trading.live_results (
    id                      BIGSERIAL PRIMARY KEY,
    strategy_id             TEXT,
    config                  JSONB NOT NULL,
    portfolio_id            TEXT NOT NULL,
    date                    DATE NOT NULL,
    -- Value and return
    current_portfolio_value NUMERIC,
    total_return            NUMERIC,
    total_annualized_return NUMERIC,
    total_cumulative_return NUMERIC,
    daily_return            NUMERIC,
    -- Risk
    volatility              NUMERIC,
    downside_deviation      NUMERIC,
    sharpe_ratio            NUMERIC,
    sortino_ratio           NUMERIC,
    max_drawdown            NUMERIC,
    portfolio_var           NUMERIC,
    max_correlation         NUMERIC,
    jump_risk               NUMERIC,
    risk_scale              NUMERIC,
    -- Day statistics
    win_rate                NUMERIC,
    avg_win                 NUMERIC,
    avg_loss                NUMERIC,
    profit_factor           NUMERIC,
    gross_profit            NUMERIC,
    gross_loss              NUMERIC,
    best_day                NUMERIC,
    worst_day               NUMERIC,
    winning_days            INTEGER,
    losing_days             INTEGER,
    total_days              INTEGER,
    -- Exposure and leverage
    gross_notional          NUMERIC,
    net_notional            NUMERIC,
    net_leverage            NUMERIC,
    portfolio_leverage      NUMERIC,
    margin_leverage         NUMERIC,
    active_positions        INTEGER,
    -- The column the engine abandoned. Kept because it is still there in the
    -- real database, holding whatever it held the day it stopped being
    -- written. AlgoLens must not read it in preference to portfolio_leverage.
    gross_leverage          NUMERIC,
    -- P&L
    total_pnl               NUMERIC,
    total_unrealized_pnl    NUMERIC,
    total_realized_pnl      NUMERIC,
    daily_pnl               NUMERIC,
    daily_realized_pnl      NUMERIC,
    daily_unrealized_pnl    NUMERIC,
    -- Costs and margin
    total_transaction_costs NUMERIC,
    daily_transaction_costs NUMERIC,
    margin_posted           NUMERIC,
    equity_to_margin_ratio  NUMERIC,
    margin_cushion          NUMERIC,
    cash_available          NUMERIC,
    UNIQUE (portfolio_id, strategy_id, date)
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

-- Contract sizes, as PRICE MULTIPLIERS: the currency value of one full point
-- of the quoted price. Notional is quantity x price x this, which is the
-- formula trade-ngin uses (chart_generator.cpp).
--
-- That distinction matters, and getting it wrong is not subtle. For most of
-- these the multiplier equals the contract size in underlying units, because
-- the price is quoted per unit: crude is dollars per barrel on 1,000 barrels,
-- gold dollars per ounce on 100 ounces. For three of them it does not:
--
--   ZN, ZB  quoted as a PERCENTAGE OF PAR on $100,000 of face value, so one
--           point is $1,000, not $100,000.
--   ZS      quoted in CENTS per bushel on 5,000 bushels, so one point (one
--           cent) is $50, not $5,000.
--
-- Seeded from trade-ngin's fallback list, those three produced exposures 100x
-- too large: forty ZN read as $449,400,000 against a $264,000 book. Note that
-- the fallback table in trade-ngin (src/core/email_sender.cpp) holds the
-- underlying-unit figures, so anything using it as a price multiplier for
-- treasuries or grains inherits the same 100x error. Worth raising with the
-- engine team; the values below are the point values.
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
  ('ZN','ZN','10-Year T-Note','FUTURE','CBOT',1000),
  ('ZB','ZB','30-Year T-Bond','FUTURE','CBOT',1000),
  ('ZS','ZS','Soybeans','FUTURE','CBOT',50),
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
   ARRAY['John Riley'], TRUE, 'live', 2),
  -- On mock capital, 45 days into its window. Its value must stay out of the
  -- fund headline: nobody has put real money behind it.
  ('meanreversion', 'LIVE_MEAN_REVERSION', 'CONSERVATIVE_PORTFOLIO',
   'Mean Reversion', 'Short-horizon reversal on index futures', 100000,
   ARRAY['Quant Team'], TRUE, 'incubating', 3);

UPDATE trading.strategy_registry
   SET mock_capital = 100000,
       incubation_started_at = now() - INTERVAL '45 days'
 WHERE id = 'meanreversion';

-- The curve is generated from these same figures, so the starting equity the
-- registry records and the curve's first point are the same number by
-- construction. The app prefers the curve's first point when one exists; this
-- keeps the two from ever telling different stories.

-- Equity curves: 90 daily points, three streams each. qt and system are
-- identical (nothing has edited qt yet); benchmark carries the same shocks with
-- a lower drift, so the attribution chart has a real spread to draw.
--
-- The previous version was a smooth drift plus one sine wave. It looked like an
-- equity curve but had almost no day-to-day variation, so the volatility
-- derived from it came out near 2% annualised and the Sharpe ratio built on
-- that came out above 12 -- a number no real book produces. A demo curve that
-- implies impossible statistics is not a neutral placeholder; anyone reading
-- the tiles has to know to disbelieve them.
--
-- This builds each curve from daily returns instead: a drift plus a shock, at a
-- target annualised volatility per strategy. The shocks are deterministic --
-- derived from md5 of the day index, not random() -- so the seed produces the
-- same book every time and the same figures can be checked twice.
-- ---------------------------------------------------------------------------
-- The equity curve.
--
-- Two things this got wrong, both of which showed up as Sharpe ratios nobody
-- should believe: 4.67 for Trend Following, 0.05 for Carry, sitting next to
-- each other on the same screen.
--
-- FIRST, the curve ran on CALENDAR days. Ninety consecutive dates, twenty-six
-- of them Saturdays and Sundays, each carrying a return. Futures markets are
-- shut then and the engine writes no equity point at all, so a third of the
-- history was days that never happened. It also made the annualisation wrong
-- twice over: the drift was scaled per trading day and then applied ninety
-- times across a span holding only about sixty-four of them, and both
-- sqrt(252) and the 252/n exponent assume the points ARE trading days.
--
-- SECOND, and worse, the shocks were never centred. Ninety draws with a
-- standard deviation of one leave a sample mean that misses zero by about a
-- tenth of a standard deviation, and compounded over the window that swamped
-- the drift it was added to:
--
--     Trend Following   seeded +4.9%   realised +18.5%   luck +13.5%
--     Carry             seeded +3.2%   realised  +0.1%   luck  -3.0%
--     Breakout          seeded +6.7%   realised +15.8%   luck  +9.1%
--     Mean Reversion    seeded +3.9%   realised  -6.0%   luck  -9.9%
--
-- Every strategy's return was two to three times more dice than drift. Then
-- annualising a lucky quarter -- raising it to the power 252/n -- turned Trend
-- Following's +18.5% into +60.8% a year against 13% volatility, and the ratio
-- of those two is 4.67. Nothing was miscalculated; the number faithfully
-- reported a coin that had come up heads.
--
-- The shocks are now demeaned across the window, so the realised return over
-- the window IS the seeded drift and the realised Sharpe is the ratio of the
-- two targets below -- a number chosen on purpose and defensible on sight.
-- The daily path keeps its noise; only the endpoint is pinned.
-- ---------------------------------------------------------------------------
INSERT INTO trading.equity_curve (strategy_id, portfolio_id, portfolio_type, timestamp, equity)
WITH trading_days AS (
    -- The last 90 weekdays, oldest first. The engine writes one point per
    -- trading day, so the demo must too.
    SELECT day, row_number() OVER (ORDER BY day) - 1 AS i
    FROM (
        SELECT d::date AS day
        FROM generate_series(CURRENT_DATE - 200, CURRENT_DATE, INTERVAL '1 day') AS d
        WHERE extract(isodow FROM d) <= 5
        ORDER BY d DESC
        LIMIT 90
    ) recent
),
params AS (
    SELECT * FROM (VALUES
        -- strategy, book, starting equity, target annual return %, target annual vol %
        --
        -- The ratio of the last two columns IS the Sharpe ratio the dashboard
        -- will show, so these are picked to be plausible for systematic
        -- futures rather than picked independently and left to collide:
        --   Trend Following 1.12   Carry 0.67   Breakout 0.90
        --   Mean Reversion -0.67 -- a trial that is not working, which is a
        --   thing an incubating strategy is allowed to be
        ('LIVE_TREND_FOLLOWING', 'CONSERVATIVE_PORTFOLIO', 500000.0, 14.0, 12.5),
        ('LIVE_CARRY',           'CONSERVATIVE_PORTFOLIO', 250000.0,  5.0,  7.5),
        ('LIVE_BREAKOUT',        'AGGRESSIVE_PORTFOLIO',   300000.0, 19.0, 21.0),
        ('LIVE_MEAN_REVERSION',  'CONSERVATIVE_PORTFOLIO', 100000.0, -6.0,  9.0)
    ) AS r(strategy_type, portfolio_id, initial_equity, annual_return, annual_vol)
),
raw AS (
    -- One row per return, so day 0 is excluded: it is the starting equity and
    -- carries no return. Ninety points give eighty-nine returns.
    SELECT p.strategy_type, p.portfolio_id, s.stream, t.i, t.day, p.initial_equity,
           p.annual_vol,
           -- Drift as a daily LOG return, so compounding it 252 times gives
           -- back the target exactly. Dividing the simple rate by 252 instead
           -- compounds to e^r - 1: a 14% target realised as 15.03%.
           --
           -- Lower for the benchmark: the spread between them is the
           -- discretionary alpha the attribution chart reports.
           ln(1 + (CASE WHEN s.stream = 'benchmark' THEN p.annual_return - 4.0
                        ELSE p.annual_return END) / 100.0) / 252.0 AS drift,
           -- Shock: three deterministic uniforms summed to approximate a
           -- normal, scaled to the target annualised volatility. The benchmark
           -- draws its own, not the same ones: identical shocks would leave
           -- the two streams differing by a constant, tracking error would be
           -- zero, and the information ratio built on it would divide by dust.
           (p.annual_vol / 100.0 / sqrt(252.0)) * 2.0 * (
                 ((('x' || substr(md5((t.i * 3 + 1)::text || p.strategy_type || CASE WHEN s.stream = 'benchmark' THEN 'b' ELSE 'q' END), 1, 8))::bit(32)::bigint & 65535) / 65535.0)
               + ((('x' || substr(md5((t.i * 3 + 2)::text || p.strategy_type || CASE WHEN s.stream = 'benchmark' THEN 'b' ELSE 'q' END), 1, 8))::bit(32)::bigint & 65535) / 65535.0)
               + ((('x' || substr(md5((t.i * 3 + 3)::text || p.strategy_type || CASE WHEN s.stream = 'benchmark' THEN 'b' ELSE 'q' END), 1, 8))::bit(32)::bigint & 65535) / 65535.0)
               - 1.5
           ) AS shock
    FROM params p
    CROSS JOIN (VALUES ('qt'), ('system'), ('benchmark')) AS s(stream)
    CROSS JOIN trading_days t
    WHERE t.i > 0
),
centred AS (
    -- Demeaned, so the shocks cancel exactly across the window and what is
    -- left is the drift. In log space, so the compounded total is exact.
    SELECT strategy_type, portfolio_id, stream, i, day, initial_equity,
           drift
           -- Standardised, then rescaled to the target. Demeaning alone left
           -- the realised volatility wherever the draws happened to land --
           -- Breakout's 21% target came out at 19.79% -- and volatility is
           -- the denominator of the Sharpe ratio on screen. Both moments are
           -- now pinned, so the ratio is the one chosen above rather than the
           -- one the dice produced. The daily path keeps its shape; only its
           -- mean and spread are calibrated.
           + ((shock - avg(shock) OVER w)
              / nullif(stddev_pop(shock) OVER w, 0))
             * (annual_vol / 100.0 / sqrt(252.0))
           AS log_return
    FROM raw
    WINDOW w AS (PARTITION BY strategy_type, portfolio_id, stream)
)
SELECT strategy_type, portfolio_id, stream, day::timestamptz,
       initial_equity * exp(sum(log_return) OVER (PARTITION BY strategy_type, portfolio_id, stream
                                                  ORDER BY i ROWS UNBOUNDED PRECEDING))
FROM centred
UNION ALL
-- Day zero: the starting equity itself, so the curve's first point and the
-- registry's initial_equity are the same number by construction.
SELECT p.strategy_type, p.portfolio_id, s.stream, t.day::timestamptz, p.initial_equity
FROM params p
CROSS JOIN (VALUES ('qt'), ('system'), ('benchmark')) AS s(stream)
CROSS JOIN trading_days t
WHERE t.i = 0;

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
  ('LIVE_BREAKOUT','Breakout','AGGRESSIVE_PORTFOLIO','qt','NG.v.0', -30,    2.914, -820.00, 150.00, CURRENT_DATE, now(), now()),
  ('LIVE_MEAN_REVERSION','Mean Reversion','CONSERVATIVE_PORTFOLIO','qt','ES.v.0', -3, 5295.00, -410.00, 95.00, CURRENT_DATE, now(), now());

-- Yesterday's snapshot.
--
-- This copied today's rows verbatim, which meant every lot matched and the
-- "Yesterday's Finalized Position Results" panel was permanently empty --
-- a "Total P&L $0.00" over no rows at all. It also meant the demo never
-- exercised the closed-lot path, where a lot that is gone today has no exit
-- price on record.
--
-- Yesterday now genuinely differs from today in the two ways the engine's
-- data can differ:
--
--   ZB.v.0  held yesterday, gone today. Nothing in this data says what it
--           exited at, so the app reports the exit price as unknown.
--   RTY.v.0 six yesterday, nine today. The lot changed size.
INSERT INTO trading.positions
  (strategy_id, strategy_name, portfolio_id, portfolio_type, symbol, quantity, average_price,
   daily_unrealized_pnl, daily_realized_pnl, date, last_update, updated_at)
SELECT strategy_id, strategy_name, portfolio_id, portfolio_type, symbol,
       CASE WHEN symbol = 'RTY.v.0' THEN 6 ELSE quantity END,
       CASE WHEN symbol = 'RTY.v.0' THEN 2279.40 ELSE average_price END,
       daily_unrealized_pnl, daily_realized_pnl,
       CURRENT_DATE - 1, now() - INTERVAL '1 day', now() - INTERVAL '1 day'
FROM trading.positions
WHERE date = CURRENT_DATE;

INSERT INTO trading.positions
  (strategy_id, strategy_name, portfolio_id, portfolio_type, symbol, quantity, average_price,
   daily_unrealized_pnl, daily_realized_pnl, date, last_update, updated_at)
VALUES
  ('LIVE_TREND_FOLLOWING','Trend Following','CONSERVATIVE_PORTFOLIO','qt','ZB.v.0', 8, 119.50,
   0.00, 640.00, CURRENT_DATE - 1, now() - INTERVAL '1 day', now() - INTERVAL '1 day');

INSERT INTO trading.executions
  (strategy_id, portfolio_id, symbol, side, quantity, price, execution_time, commissions_fees)
VALUES
  ('LIVE_TREND_FOLLOWING','CONSERVATIVE_PORTFOLIO','ES.v.0','BUY',  4, 5276.00, now() - INTERVAL '3 hours',  9.20),
  ('LIVE_TREND_FOLLOWING','CONSERVATIVE_PORTFOLIO','CL.v.0','SELL', 6,   78.62, now() - INTERVAL '6 hours', 11.40),
  ('LIVE_CARRY','CONSERVATIVE_PORTFOLIO','ZN.v.0','BUY', 10, 111.79, now() - INTERVAL '5 hours',  7.80),
  ('LIVE_BREAKOUT','AGGRESSIVE_PORTFOLIO','RTY.v.0','BUY', 3, 2281.10, now() - INTERVAL '2 hours', 6.10);

-- ---------------------------------------------------------------------------
-- Engine results, DERIVED from the data above rather than typed.
--
-- These were hand-written literals, and they disagreed with the very series
-- they were meant to summarise: current_portfolio_value was $3,453 away from
-- the last point of the equity curve, and volatility claimed 12.6% where the
-- curve's actual annualised volatility is 2.1%. The chart and the tiles beside
-- it were describing different books.
--
-- Everything below is computed from the equity curve, the open positions, the
-- market prices and the executions already seeded, so every figure on screen
-- reconciles with the series behind it.
--
-- Fields the demo has no basis for -- margin posted, and the equity-to-margin
-- and cushion ratios derived from it, and cash available -- are left NULL. The
-- app renders NULL as "unknown", which is the truth here: no margin model
-- exists in this data. Inventing a plausible margin figure is what produced
-- the numbers this block replaces.
-- ---------------------------------------------------------------------------
WITH curve AS (
    SELECT strategy_id, portfolio_id, timestamp, equity,
           lag(equity) OVER (PARTITION BY strategy_id, portfolio_id ORDER BY timestamp) AS prev,
           max(equity) OVER (PARTITION BY strategy_id, portfolio_id ORDER BY timestamp
                             ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS peak
    FROM trading.equity_curve
    WHERE portfolio_type = 'qt'
),
-- Daily returns in PERCENT and daily P&L in DOLLARS, which is the pair the
-- engine's LiveHistoricalMetricsCalculator works from: percentage returns for
-- volatility, win rate, best/worst day and the average win and loss; dollar
-- P&L for gross profit, gross loss and the profit factor.
returns AS (
    SELECT strategy_id, portfolio_id,
           (equity / prev - 1) * 100 AS r_pct,
           equity - prev             AS pnl,
           row_number() OVER (PARTITION BY strategy_id, portfolio_id ORDER BY timestamp DESC) AS recency
    FROM curve
    WHERE prev IS NOT NULL AND prev > 0
),
drawdown AS (
    SELECT strategy_id, portfolio_id,
           max((peak - equity) / peak) * 100 AS max_drawdown
    FROM curve WHERE peak > 0 GROUP BY 1, 2
),
series AS (
    SELECT strategy_id, portfolio_id,
           min(equity) FILTER (WHERE rn_first = 1) AS first_equity,
           min(equity) FILTER (WHERE rn_last = 1)  AS last_equity,
           count(*)                                AS points
    FROM (
        SELECT strategy_id, portfolio_id, equity,
               row_number() OVER (PARTITION BY strategy_id, portfolio_id ORDER BY timestamp ASC)  AS rn_first,
               row_number() OVER (PARTITION BY strategy_id, portfolio_id ORDER BY timestamp DESC) AS rn_last
        FROM trading.equity_curve WHERE portfolio_type = 'qt'
    ) q GROUP BY 1, 2
),
stats AS (
    SELECT strategy_id, portfolio_id,
           -- POPULATION standard deviation, divided by n. The engine's
           -- calculate_annualized_volatility divides by n, not n-1; this was
           -- stddev_samp, which is a different number on a 90-point curve.
           stddev_pop(r_pct) * sqrt(252)                        AS volatility,
           -- Downside deviation over the NEGATIVE returns only, which is the
           -- engine's convention (calculate_annualized_downside_deviation
           -- divides by the count of negatives, not by the count of all days).
           CASE WHEN count(*) FILTER (WHERE r_pct < 0) >= 2
                THEN sqrt(sum(r_pct * r_pct) FILTER (WHERE r_pct < 0)
                          / count(*) FILTER (WHERE r_pct < 0)) * sqrt(252)
           END                                                  AS downside_deviation,
           max(r_pct) FILTER (WHERE recency = 1)                AS daily_return,
           max(pnl)   FILTER (WHERE recency = 1)                AS daily_pnl,
           max(r_pct)                                           AS best_day,
           min(r_pct)                                           AS worst_day,
           count(*) FILTER (WHERE r_pct > 0)                    AS winning_days,
           count(*) FILTER (WHERE r_pct < 0)                    AS losing_days,
           count(*)                                             AS total_days,
           avg(r_pct)      FILTER (WHERE r_pct > 0)             AS avg_win,
           abs(avg(r_pct)  FILTER (WHERE r_pct < 0))            AS avg_loss,
           coalesce(sum(pnl) FILTER (WHERE pnl > 0), 0)         AS gross_profit,
           abs(coalesce(sum(pnl) FILTER (WHERE pnl < 0), 0))    AS gross_loss
    FROM returns GROUP BY 1, 2
),
-- Exposure priced exactly the way the application prices it: quantity times
-- the latest close times the contract size.
exposure AS (
    SELECT p.strategy_id, p.portfolio_id,
           sum(abs(p.quantity * px.close * m."Contract Size")) AS gross_notional,
           abs(sum(p.quantity * px.close * m."Contract Size")) AS net_notional,
           sum(p.daily_unrealized_pnl) AS unrealized,
           sum(p.daily_realized_pnl)   AS realized,
           count(*)                    AS active_positions
    FROM trading.positions p
    JOIN LATERAL (
        SELECT close FROM futures_data.ohlcv_1d o
        WHERE o.symbol = p.symbol ORDER BY o.time DESC LIMIT 1
    ) px ON TRUE
    JOIN metadata.contract_metadata m
      ON m."Databento Symbol" = split_part(p.symbol, '.', 1)
    WHERE p.portfolio_type = 'qt' AND p.date = CURRENT_DATE
    GROUP BY 1, 2
),
costs AS (
    SELECT strategy_id, portfolio_id, sum(commissions_fees) AS commissions
    FROM trading.executions GROUP BY 1, 2
),
annualised AS (
    SELECT se.*,
           -- points - 1, because n points are n-1 returns. Annualising over
           -- the point count stretched the exponent by a ninetieth and left
           -- the realised return a shade under its target.
           (power(se.last_equity / se.first_equity, 252.0 / (se.points - 1)) - 1) * 100 AS ann_return
    FROM series se
    WHERE se.points > 1
)
INSERT INTO trading.live_results
  (strategy_id, config, portfolio_id, date,
   current_portfolio_value, total_return, total_annualized_return,
   total_cumulative_return, daily_return,
   volatility, downside_deviation, sharpe_ratio, sortino_ratio, max_drawdown,
   portfolio_var, max_correlation, jump_risk, risk_scale,
   win_rate, avg_win, avg_loss, profit_factor, gross_profit, gross_loss,
   best_day, worst_day, winning_days, losing_days, total_days,
   gross_notional, net_notional, net_leverage, portfolio_leverage,
   margin_leverage, active_positions, gross_leverage,
   total_pnl, total_unrealized_pnl, total_realized_pnl,
   daily_pnl, daily_realized_pnl, daily_unrealized_pnl,
   total_transaction_costs, daily_transaction_costs,
   margin_posted, equity_to_margin_ratio, margin_cushion, cash_available)
SELECT
    se.strategy_id,
    jsonb_build_object('strategy_type', se.strategy_id),
    se.portfolio_id,
    CURRENT_DATE,
    se.last_equity,
    -- total_return is only written by the engine's legacy fixed INSERT, and
    -- its units are not determinable from the call site. Left unset rather
    -- than guessed at.
    NULL,
    se.ann_return,
    (se.last_equity / se.first_equity - 1) * 100,
    st.daily_return,
    st.volatility,
    st.downside_deviation,
    -- The engine's own formulas: annualised return over volatility, and over
    -- downside deviation. Both with a ZERO risk-free rate, which is what
    -- live_historical_metrics.cpp does.
    CASE WHEN st.volatility > 0 THEN se.ann_return / st.volatility END,
    CASE WHEN st.downside_deviation > 0 THEN se.ann_return / st.downside_deviation END,
    dd.max_drawdown,
    NULL, NULL, NULL, NULL,     -- VaR, max correlation, jump risk, risk scale: no source
    CASE WHEN st.total_days > 0
         THEN st.winning_days::numeric / st.total_days * 100 END,
    st.avg_win,
    st.avg_loss,
    -- Engine convention is 999.99 for a book with gains and no losses. Left
    -- NULL here instead: an undefined ratio is not a very large one, and the
    -- app renders NULL as unknown. Flagged for the engine team.
    CASE WHEN st.gross_loss > 0 THEN st.gross_profit / st.gross_loss END,
    st.gross_profit,
    st.gross_loss,
    st.best_day,
    st.worst_day,
    st.winning_days,
    st.losing_days,
    st.total_days,
    ex.gross_notional,
    ex.net_notional,
    ex.net_notional / se.last_equity,
    ex.gross_notional / se.last_equity,
    NULL,                        -- margin leverage: depends on margin, no source
    ex.active_positions,
    -- The abandoned column stays empty, so anything reading it in preference
    -- to portfolio_leverage shows unknown rather than a stale number.
    NULL,
    ex.unrealized + ex.realized,
    ex.unrealized,
    ex.realized,
    st.daily_pnl,
    ex.realized,                 -- positions carry DAILY realised P&L
    ex.unrealized,               -- and DAILY unrealised P&L
    co.commissions,
    co.commissions,              -- every seeded fill is today's
    NULL, NULL, NULL, NULL       -- margin posted, equity/margin, cushion, cash: no source
FROM annualised se
JOIN stats st         ON st.strategy_id = se.strategy_id AND st.portfolio_id = se.portfolio_id
LEFT JOIN drawdown dd ON dd.strategy_id = se.strategy_id AND dd.portfolio_id = se.portfolio_id
LEFT JOIN exposure ex ON ex.strategy_id = se.strategy_id AND ex.portfolio_id = se.portfolio_id
LEFT JOIN costs co    ON co.strategy_id = se.strategy_id AND co.portfolio_id = se.portfolio_id;

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
