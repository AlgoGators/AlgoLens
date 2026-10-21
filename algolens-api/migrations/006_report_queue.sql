-- Outbound report queue (trade-ngin enqueues, AlgoLens renders and sends).
--
-- trade-ngin used to build and send the daily trading email itself. It now writes one row here
-- when a run finishes and AlgoLens (scripts/send_reports.py) renders the HTML and charts and
-- sends the mail. payload is the report data (schema_version 1, see
-- algolens/domain/reports/daily.py); nothing about layout lives in trade-ngin any more.
--
-- status: queued -> sending -> sent | failed. A worker claims a row with FOR UPDATE SKIP LOCKED,
-- so two workers never send the same report. failed rows are retried until max_attempts.
--
-- Safe to run more than once.

BEGIN;

CREATE SCHEMA IF NOT EXISTS reports;

CREATE TABLE IF NOT EXISTS reports.report_queue (
    id           BIGSERIAL   PRIMARY KEY,
    report_type  TEXT        NOT NULL CHECK (report_type IN ('daily_trading')),
    portfolio_id TEXT        NOT NULL CHECK (btrim(portfolio_id) <> ''),
    report_date  DATE        NOT NULL,
    recipients   TEXT[]      NOT NULL CHECK (cardinality(recipients) > 0),
    payload      JSONB       NOT NULL,
    status       TEXT        NOT NULL DEFAULT 'queued'
                             CHECK (status IN ('queued', 'sending', 'sent', 'failed')),
    attempts     INTEGER     NOT NULL DEFAULT 0,
    max_attempts INTEGER     NOT NULL DEFAULT 3,
    last_error   TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    claimed_at   TIMESTAMPTZ,
    sent_at      TIMESTAMPTZ,
    -- one report per portfolio per day per type: re-enqueueing the same run is a no-op
    UNIQUE (report_type, portfolio_id, report_date)
);

CREATE INDEX IF NOT EXISTS report_queue_pending_idx
    ON reports.report_queue (created_at)
    WHERE status IN ('queued', 'failed');

COMMIT;
