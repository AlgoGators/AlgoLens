-- Each investor follows one portfolio and one of its books (HD D-25, decision 13, 2026-10-16).
--
-- The investor screen showed the house QT book of every desk portfolio to every investor. Now an
-- investor sees only their own portfolio, in the book they follow: the QT book (the desk's edits)
-- or the model book, set per investor by an admin; with no row the investor follows the QT book
-- (decision 13: QT by default). Every change is logged, append-only.
--
-- book is the row set the investor reads: 'qt' (a desk-editable portfolio's final book) or
-- 'system' (a model book). AlgoLens checks the pair against the registry when it is set.
--
-- Safe to run more than once.

BEGIN;

CREATE TABLE IF NOT EXISTS investor.portfolio_links (
    user_id      INTEGER     PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    portfolio_id TEXT        NOT NULL CHECK (btrim(portfolio_id) <> ''),
    book         TEXT        NOT NULL CHECK (book IN ('qt', 'system')),
    set_by       TEXT        NOT NULL,
    set_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS investor.portfolio_link_log (
    id           BIGSERIAL   PRIMARY KEY,
    user_id      INTEGER     NOT NULL,
    portfolio_id TEXT        NOT NULL,
    book         TEXT        NOT NULL,
    set_by       TEXT        NOT NULL,
    set_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION investor.portfolio_link_log_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'investor.portfolio_link_log is append-only';
END $$;

DROP TRIGGER IF EXISTS portfolio_link_log_append_only ON investor.portfolio_link_log;
CREATE TRIGGER portfolio_link_log_append_only
    BEFORE UPDATE OR DELETE ON investor.portfolio_link_log
    FOR EACH ROW EXECUTE FUNCTION investor.portfolio_link_log_append_only();

DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'svc_algolens') THEN
        GRANT SELECT, INSERT, UPDATE ON investor.portfolio_links TO svc_algolens;
        GRANT SELECT, INSERT ON investor.portfolio_link_log TO svc_algolens;
        GRANT USAGE ON SEQUENCE investor.portfolio_link_log_id_seq TO svc_algolens;
    END IF;
END $$;

COMMIT;
