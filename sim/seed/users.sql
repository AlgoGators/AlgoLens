-- The simulator's three users, applied by `simctl load` after the snapshot (or the synthetic
-- fixture). The snapshot carries no auth.users rows on purpose.
--
--   qt@sim.local         the desk (QT trader)
--   vp@sim.local         VP, approver (QT_APPROVERS vp=)
--   president@sim.local  President, approver (QT_APPROVERS president=)
--
-- Password for all three: sim. The hash is werkzeug's generate_password_hash('sim') (scrypt),
-- the format AlgoLens checks with check_password_hash (auth.users.password_hash).
-- Screens (AlgoLens migration 003): member and qt for each.

BEGIN;

-- Prod's auth.users has no unique constraint on email: replace the three rows instead of
-- upserting them (this database is the sim's own).
DELETE FROM auth.user_screen_access WHERE user_id IN (
    SELECT id FROM auth.users WHERE email IN ('qt@sim.local', 'vp@sim.local', 'president@sim.local'));
DELETE FROM auth.users WHERE email IN ('qt@sim.local', 'vp@sim.local', 'president@sim.local');

INSERT INTO auth.users (email, password_hash, role, first_name, last_name)
VALUES
    ('qt@sim.local',
     'scrypt:32768:8:1$wGNaZmcVB0vQDcoM$92e271223334ccb1e61316a42ba3b0f53030b259afad72b0ae388434c104c5a19c1b801150a0973903a3593c92a81742c6c1679797f08271aba6343c86ad1d07',
     'general_member', 'QT', 'Desk'),
    ('vp@sim.local',
     'scrypt:32768:8:1$wGNaZmcVB0vQDcoM$92e271223334ccb1e61316a42ba3b0f53030b259afad72b0ae388434c104c5a19c1b801150a0973903a3593c92a81742c6c1679797f08271aba6343c86ad1d07',
     'general_member', 'Sim', 'VP'),
    ('president@sim.local',
     'scrypt:32768:8:1$wGNaZmcVB0vQDcoM$92e271223334ccb1e61316a42ba3b0f53030b259afad72b0ae388434c104c5a19c1b801150a0973903a3593c92a81742c6c1679797f08271aba6343c86ad1d07',
     'general_member', 'Sim', 'President')
;

INSERT INTO auth.user_screen_access (user_id, screen, granted_by)
SELECT u.id, s.screen, 'sim:seed'
FROM auth.users u
CROSS JOIN (VALUES ('member'), ('qt')) AS s(screen)
WHERE u.email IN ('qt@sim.local', 'vp@sim.local', 'president@sim.local')
ON CONFLICT DO NOTHING;

COMMIT;
