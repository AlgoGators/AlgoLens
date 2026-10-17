-- Rollback of 004_desk_settings_locks.sql: drops the lock list and its log. AlgoLens then
-- applies its starting locks (DEFAULT_LOCKS) again. Back up the log first if it matters:
--   pg_dump -t trading.desk_settings_lock_log ...

BEGIN;
DROP TABLE IF EXISTS trading.desk_settings_lock_log;
DROP FUNCTION IF EXISTS trading.desk_settings_lock_log_append_only();
DROP TABLE IF EXISTS trading.desk_settings_locks;
COMMIT;
