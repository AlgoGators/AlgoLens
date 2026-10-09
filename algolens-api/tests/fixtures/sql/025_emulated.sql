-- EMULATED for AlgoLens tests: the shapes trade-ngin migration 025 is specified to add
-- (QT hardening spec 2026-10-09, contract C2 and C4), written before the engine's file
-- existed. Replace with the vendored file once trade-ngin merges 025.
--
--   * unique partial indexes: one live decision per request, one open publish and one open
--     override request per (portfolio, day);
--   * an insert trigger: a new row is pending with the engine-owned columns NULL;
--   * an update trigger: pending -> running -> done/refused/failed, running -> pending
--     (the agent's recovery); terminal rows are final;
--   * TRUNCATE blocked by a statement-level trigger.
-- The REVOKE of UPDATE, DELETE and TRUNCATE from the AlgoLens role is done by the fixture
-- (tests/qt_fixture.py), which owns that role.

BEGIN;

CREATE UNIQUE INDEX position_overrides_one_decision
    ON trading.position_overrides (parent_id)
    WHERE kind = 'override_decision' AND status IN ('pending', 'running', 'done');
CREATE UNIQUE INDEX position_overrides_one_open_publish
    ON trading.position_overrides (portfolio_id, date)
    WHERE kind = 'publish' AND status IN ('pending', 'running');
CREATE UNIQUE INDEX position_overrides_one_open_request
    ON trading.position_overrides (portfolio_id, date)
    WHERE kind = 'override_request' AND status IN ('pending', 'running');

CREATE OR REPLACE FUNCTION trading.position_overrides_insert_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.status <> 'pending'
       OR NEW.started_at IS NOT NULL OR NEW.finished_at IS NOT NULL
       OR NEW.result IS NOT NULL OR NEW.message IS NOT NULL
       OR NEW.token_hash IS NOT NULL OR NEW.token_expires_at IS NOT NULL THEN
        RAISE EXCEPTION 'trading.position_overrides: a new row is pending with the engine columns NULL';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER position_overrides_insert_guard
    BEFORE INSERT ON trading.position_overrides
    FOR EACH ROW EXECUTE FUNCTION trading.position_overrides_insert_guard();

CREATE OR REPLACE FUNCTION trading.position_overrides_transition_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.status IS DISTINCT FROM OLD.status AND NOT (
           (OLD.status = 'pending' AND NEW.status = 'running')
        OR (OLD.status = 'running' AND NEW.status IN ('done', 'refused', 'failed', 'pending'))) THEN
        RAISE EXCEPTION 'trading.position_overrides: % -> % is not an allowed transition', OLD.status, NEW.status;
    END IF;
    IF OLD.status IN ('done', 'refused', 'failed') AND NEW.status = OLD.status
       AND (NEW.result, NEW.message, NEW.finished_at) IS DISTINCT FROM (OLD.result, OLD.message, OLD.finished_at) THEN
        RAISE EXCEPTION 'trading.position_overrides: a terminal row is final';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER position_overrides_transition_guard
    BEFORE UPDATE ON trading.position_overrides
    FOR EACH ROW EXECUTE FUNCTION trading.position_overrides_transition_guard();

CREATE OR REPLACE FUNCTION trading.position_overrides_no_truncate() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'trading.position_overrides is never truncated';
END $$;

CREATE TRIGGER position_overrides_no_truncate
    BEFORE TRUNCATE ON trading.position_overrides
    FOR EACH STATEMENT EXECUTE FUNCTION trading.position_overrides_no_truncate();

COMMIT;
