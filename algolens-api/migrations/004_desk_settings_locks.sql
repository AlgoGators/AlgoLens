-- Desk settings locks (HD D-14, 2026-10-16).
--
-- The desk sees every setting the QT book runs on except backtest ones and the database, email
-- and qt blocks (decision 7). An admin locks or unlocks any single setting from the Admin
-- screen: a locked setting is shown greyed out and cannot be saved. The lock list lives here,
-- not in code. A path is a list of keys; "*" matches any key and "covariance_*" any key that
-- starts with "covariance_"; a section's path covers everything under it. Every lock and unlock
-- is logged, append-only, in trading.desk_settings_lock_log.
--
-- The seed is the starting list (Dom, 2026-10-14): platform and operations switches and the
-- model's structure, which AlgoLens hid before D-14. use_optimization and covariance_* are top
-- level keys of portfolio.json (D-19). AlgoLens applies the same list while this table is
-- absent (algolens/domain/qt/settings.py DEFAULT_LOCKS).
--
-- Safe to run more than once.

BEGIN;

CREATE TABLE IF NOT EXISTS trading.desk_settings_locks (
    path       TEXT[]      PRIMARY KEY CHECK (cardinality(path) BETWEEN 1 AND 12),
    reason     TEXT        NOT NULL CHECK (btrim(reason) <> ''),
    locked_by  TEXT        NOT NULL,
    locked_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS trading.desk_settings_lock_log (
    id          BIGSERIAL   PRIMARY KEY,
    path        TEXT[]      NOT NULL,
    locked      BOOLEAN     NOT NULL,
    reason      TEXT        NOT NULL,
    changed_by  TEXT        NOT NULL,
    changed_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION trading.desk_settings_lock_log_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'trading.desk_settings_lock_log is append-only';
END $$;

DROP TRIGGER IF EXISTS desk_settings_lock_log_append_only ON trading.desk_settings_lock_log;
CREATE TRIGGER desk_settings_lock_log_append_only
    BEFORE UPDATE OR DELETE ON trading.desk_settings_lock_log
    FOR EACH ROW EXECUTE FUNCTION trading.desk_settings_lock_log_append_only();

INSERT INTO trading.desk_settings_locks (path, reason, locked_by) VALUES
    (ARRAY['live'], 'Platform and operations switches (Dom, 2026-10-14)', 'migration 004'),
    (ARRAY['execution'], 'Platform and operations switches (Dom, 2026-10-14)', 'migration 004'),
    (ARRAY['strategy_defaults'], 'Model structure (Dom, 2026-10-14)', 'migration 004'),
    (ARRAY['optimization'], 'Model structure: dynamic optimisation''s internals (Dom, 2026-10-14)', 'migration 004'),
    (ARRAY['use_optimization'], 'Model structure (Dom, 2026-10-14)', 'migration 004'),
    (ARRAY['covariance_*'], 'Model structure (Dom, 2026-10-14)', 'migration 004'),
    (ARRAY['strategies', '*', 'type'], 'Model structure (Dom, 2026-10-14)', 'migration 004'),
    (ARRAY['strategies', '*', 'enabled_live'], 'Model structure (Dom, 2026-10-14)', 'migration 004'),
    (ARRAY['strategies', '*', 'default_allocation'], 'Model structure (Dom, 2026-10-14)', 'migration 004')
ON CONFLICT (path) DO NOTHING;

-- AlgoLens's own role, where it exists (D-51): it reads and changes the locks and appends to
-- the log, never more.
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'svc_algolens') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON trading.desk_settings_locks TO svc_algolens;
        GRANT SELECT, INSERT ON trading.desk_settings_lock_log TO svc_algolens;
        GRANT USAGE ON SEQUENCE trading.desk_settings_lock_log_id_seq TO svc_algolens;
    END IF;
END $$;

COMMIT;
