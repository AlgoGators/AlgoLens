-- Strategy lifecycle management: support incubation of strategies on mock capital.
--
-- Background: AlgoLens currently tracks only "live" strategies using real capital in
-- the portfolio_id's trading tables (positions, equity_curve, live_results, executions).
--
-- This migration adds a "lifecycle" state machine to strategy_registry, allowing
-- strategies to be moved into an "incubating" state where they run the same cron jobs
-- (same backtests, same rebalance logic) against mock capital, walled off from the
-- real portfolio. A strategy in incubation is completely invisible to the live
-- portfolio dashboard and its metrics.
--
-- The default is 'live' deliberately: every pre-existing strategy_registry row (all
-- of which run real capital) must retain its behavior and continue appearing in the
-- real dashboard. Defaulting to 'incubating' would silently exclude them, breaking
-- the entire live book on any deployment where this migration runs but the code to
-- read the new column has not deployed yet.
--
-- The incubation window is 3-4 months: a strategy's mock performance is tracked from
-- incubation_started_at onward, and mock_capital represents the notional equity the
-- strategy trades against during incubation. Both are NULL for live strategies.
--
-- Safe to run more than once (ADD COLUMN IF NOT EXISTS, transactional).

ALTER TABLE trading.strategy_registry
    ADD COLUMN IF NOT EXISTS lifecycle TEXT NOT NULL DEFAULT 'live'
        CHECK (lifecycle IN ('incubating', 'live', 'retired'));

ALTER TABLE trading.strategy_registry
    ADD COLUMN IF NOT EXISTS incubation_started_at TIMESTAMPTZ;

ALTER TABLE trading.strategy_registry
    ADD COLUMN IF NOT EXISTS mock_capital NUMERIC;

-- Audit table: every lifecycle state transition is recorded with before/after state,
-- reason, and user_id. This is as consequential as a position override and must be
-- auditable.
CREATE TABLE IF NOT EXISTS trading.strategy_lifecycle_log (
    id                  SERIAL PRIMARY KEY,
    strategy_id         TEXT NOT NULL REFERENCES trading.strategy_registry(id) ON DELETE CASCADE,
    before_state        TEXT NOT NULL CHECK (before_state IN ('incubating', 'live', 'retired')),
    after_state         TEXT NOT NULL CHECK (after_state IN ('incubating', 'live', 'retired')),
    reason              TEXT NOT NULL,
    user_id             TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Index for audit queries: look up transitions by strategy and date range
CREATE INDEX IF NOT EXISTS idx_lifecycle_log_strategy_date
    ON trading.strategy_lifecycle_log(strategy_id, created_at DESC);
