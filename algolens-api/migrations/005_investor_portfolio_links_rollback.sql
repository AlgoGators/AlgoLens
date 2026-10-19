-- Rollback of 005_investor_portfolio_links.sql: every investor goes back to the default (the
-- QT book). Back up the log first if it matters: pg_dump -t investor.portfolio_link_log ...

BEGIN;
DROP TABLE IF EXISTS investor.portfolio_link_log;
DROP FUNCTION IF EXISTS investor.portfolio_link_log_append_only();
DROP TABLE IF EXISTS investor.portfolio_links;
COMMIT;
