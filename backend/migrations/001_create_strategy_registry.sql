-- Strategy registry: makes the set of strategies AlgoLens can display data-driven
-- instead of hardcoded in portfolio.py.
--
-- Each row maps a public API id (used in the URL /portfolio/strategy/<id> and in
-- the front-end) to the internal strategy_type discriminator stored in the trading
-- tables, plus display metadata and the starting equity used for return math.
--
-- Safe to run more than once (IF NOT EXISTS + idempotent seed upsert). Applying it
-- is OPTIONAL for correctness: the backend falls back to a built-in default
-- registry (the single trend-following strategy) when this table is absent or
-- empty, so old and new code both work. Applying it is what unlocks adding further
-- strategies without a code change.

CREATE TABLE IF NOT EXISTS trading.strategy_registry (
    id             TEXT PRIMARY KEY,            -- public API id, e.g. 'trendfollowing'
    strategy_type  TEXT NOT NULL,               -- internal discriminator, e.g. 'LIVE_TREND_FOLLOWING'
    name           TEXT NOT NULL,               -- display name
    description    TEXT NOT NULL DEFAULT '',
    initial_equity NUMERIC NOT NULL DEFAULT 500000,
    managers       JSONB NOT NULL DEFAULT '["AlgoLens System"]'::jsonb,
    is_active      BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order     INTEGER NOT NULL DEFAULT 0,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Seed / refresh the one strategy that currently exists. This mirrors exactly the
-- values that were hardcoded in portfolio.py so behaviour is unchanged after the
-- code switches to reading this table.
INSERT INTO trading.strategy_registry
    (id, strategy_type, name, description, initial_equity, managers, is_active, sort_order)
VALUES
    ('trendfollowing',
     'LIVE_TREND_FOLLOWING',
     'Trend Following',
     'Systematic trend following across multiple futures contracts',
     500000,
     '["AlgoLens System"]'::jsonb,
     TRUE,
     0)
ON CONFLICT (id) DO UPDATE SET
    strategy_type  = EXCLUDED.strategy_type,
    name           = EXCLUDED.name,
    description    = EXCLUDED.description,
    initial_equity = EXCLUDED.initial_equity,
    managers       = EXCLUDED.managers,
    is_active      = EXCLUDED.is_active,
    sort_order     = EXCLUDED.sort_order,
    updated_at     = now();
