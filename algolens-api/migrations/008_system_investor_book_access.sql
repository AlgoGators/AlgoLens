-- Authorization is separate from engine onboarding. This table grants an
-- authenticated AlgoLens investor access to one immutable trade-ngin book.
BEGIN;

DO $$
BEGIN
    IF to_regclass('trading.investor_books') IS NULL OR
       to_regclass('trading.investor_book_publications') IS NULL THEN
        RAISE EXCEPTION 'trade-ngin investor book migration 026 is required';
    END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS trading.investor_book_access (
    portfolio_id varchar(100) NOT NULL
        REFERENCES trading.investor_books(portfolio_id) ON DELETE RESTRICT,
    user_id bigint NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
    is_active boolean NOT NULL DEFAULT true,
    granted_by bigint NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
    granted_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    revoked_at timestamptz,
    PRIMARY KEY (portfolio_id, user_id),
    CONSTRAINT investor_book_access_revocation_consistent CHECK (
        (is_active AND revoked_at IS NULL) OR
        (NOT is_active AND revoked_at IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS investor_book_access_active_user_idx
    ON trading.investor_book_access(user_id, portfolio_id)
    WHERE is_active;

CREATE OR REPLACE FUNCTION trading.protect_investor_book_access_identity()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.portfolio_id IS DISTINCT FROM OLD.portfolio_id OR
       NEW.user_id IS DISTINCT FROM OLD.user_id OR
       NEW.granted_by IS DISTINCT FROM OLD.granted_by OR
       NEW.granted_at IS DISTINCT FROM OLD.granted_at THEN
        RAISE EXCEPTION 'investor book access identity is immutable';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS investor_book_access_identity_immutable
    ON trading.investor_book_access;
CREATE TRIGGER investor_book_access_identity_immutable
BEFORE UPDATE ON trading.investor_book_access
FOR EACH ROW EXECUTE FUNCTION trading.protect_investor_book_access_identity();

COMMIT;
