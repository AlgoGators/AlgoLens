-- Rollback of 003_screen_access.sql. DESTRUCTIVE: drops every screen grant,
-- the access log and every uploaded investor report. Back up first:
--   pg_dump -n investor -t auth.user_screen_access -t auth.screen_access_log ...
-- Roll the AlgoLens images back BEFORE running this: the backend's role
-- fallback only covers a missing auth.user_screen_access, and investor routes
-- answer 503 without investor.reports.

BEGIN;
DROP TABLE IF EXISTS investor.reports;
DROP SCHEMA IF EXISTS investor;
DROP TABLE IF EXISTS auth.screen_access_log;
DROP TABLE IF EXISTS auth.user_screen_access;
COMMIT;
