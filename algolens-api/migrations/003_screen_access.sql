-- Screen access and investor reports (Dom, 2026-10-11).
--
-- AlgoLens has three screens: member, investor and qt. An admin (role
-- exec_board) assigns each user any of them; the roles themselves are
-- unchanged. The backend reads auth.user_screen_access on every request, so a
-- grant or revoke takes effect at once. Every change is logged, append-only,
-- in auth.screen_access_log.
--
-- investor.reports holds the PDF reports and letters an admin uploads for the
-- investor screen. Reports are never deleted, only unpublished.
--
-- Backfill (keeps today's access): every general_member, team_lead and
-- exec_board user gets member; exec_board also gets qt (the desk). New
-- sign-ups get nothing until an admin grants a screen.
--
-- Grants go to svc_algolens (qt_algolens_app inherits it), when that role
-- exists. Transactional; safe to run more than once. Rollback:
-- 003_screen_access_rollback.sql.

BEGIN;

CREATE TABLE IF NOT EXISTS auth.user_screen_access (
    user_id    INTEGER     NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    screen     TEXT        NOT NULL CHECK (screen IN ('member', 'investor', 'qt')),
    granted_by TEXT        NOT NULL,
    granted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, screen)
);

-- No foreign key: the log outlives a deleted user.
CREATE TABLE IF NOT EXISTS auth.screen_access_log (
    id       BIGSERIAL   PRIMARY KEY,
    user_id  INTEGER     NOT NULL,
    screen   TEXT        NOT NULL CHECK (screen IN ('member', 'investor', 'qt')),
    action   TEXT        NOT NULL CHECK (action IN ('grant', 'revoke')),
    by_email TEXT        NOT NULL,
    at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_screen_access_log_user
    ON auth.screen_access_log (user_id, at DESC);

CREATE SCHEMA IF NOT EXISTS investor;

CREATE TABLE IF NOT EXISTS investor.reports (
    id           BIGSERIAL   PRIMARY KEY,
    title        TEXT        NOT NULL CHECK (length(btrim(title)) BETWEEN 1 AND 200),
    kind         TEXT        NOT NULL CHECK (kind IN ('monthly', 'quarterly', 'letter', 'other')),
    period_label TEXT        NULL CHECK (period_label IS NULL OR length(period_label) <= 40),
    filename     TEXT        NOT NULL,
    content_type TEXT        NOT NULL CHECK (content_type = 'application/pdf'),
    size_bytes   INTEGER     NOT NULL CHECK (size_bytes > 0 AND size_bytes <= 10485760),
    content      BYTEA       NOT NULL CHECK (octet_length(content) = size_bytes),
    sha256       TEXT        NOT NULL,
    uploaded_by  TEXT        NOT NULL,
    uploaded_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    published    BOOLEAN     NOT NULL DEFAULT TRUE
);
CREATE INDEX IF NOT EXISTS idx_investor_reports_uploaded
    ON investor.reports (uploaded_at DESC);

-- Backfill. role is the auth.user_role enum; compare as text.
INSERT INTO auth.user_screen_access (user_id, screen, granted_by)
SELECT id, 'member', 'migration:003' FROM auth.users
WHERE role::text IN ('general_member', 'team_lead', 'exec_board')
ON CONFLICT DO NOTHING;

INSERT INTO auth.user_screen_access (user_id, screen, granted_by)
SELECT id, 'qt', 'migration:003' FROM auth.users
WHERE role::text = 'exec_board'
ON CONFLICT DO NOTHING;

INSERT INTO auth.screen_access_log (user_id, screen, action, by_email)
SELECT a.user_id, a.screen, 'grant', 'migration:003'
FROM auth.user_screen_access a
WHERE a.granted_by = 'migration:003'
  AND NOT EXISTS (
      SELECT 1 FROM auth.screen_access_log l
      WHERE l.user_id = a.user_id AND l.screen = a.screen AND l.by_email = 'migration:003'
  );

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'svc_algolens') THEN
        GRANT USAGE ON SCHEMA investor TO svc_algolens;
        GRANT SELECT, INSERT, DELETE ON auth.user_screen_access TO svc_algolens;
        GRANT SELECT, INSERT ON auth.screen_access_log TO svc_algolens;
        GRANT USAGE ON SEQUENCE auth.screen_access_log_id_seq TO svc_algolens;
        GRANT SELECT, INSERT, UPDATE ON investor.reports TO svc_algolens;
        GRANT USAGE ON SEQUENCE investor.reports_id_seq TO svc_algolens;
    END IF;
END $$;

COMMIT;
