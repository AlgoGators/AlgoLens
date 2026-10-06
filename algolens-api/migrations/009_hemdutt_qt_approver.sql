-- Resolve the five exact normalized production identities without guessed IDs.
-- John Riley is the sole QT submitter. Hemdutt Rao, Xander Robbins and
-- Dominick Dupuy are the only active approvers. Historical mappings (including
-- Eric Shwartz and the old dominick_dupuoy spelling) remain inactive so
-- immutable approval foreign keys continue to resolve. Dominick's personal
-- Gmail row is retained for audit references but retired in favor of his UFL row.
-- Dominick's exact UFL row is promoted from its known general_member baseline.
BEGIN;

CREATE TABLE IF NOT EXISTS auth.account_retirements (
    user_id bigint PRIMARY KEY REFERENCES auth.users(id) ON DELETE RESTRICT,
    replacement_user_id bigint NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
    reason text NOT NULL,
    retired_by_migration text NOT NULL,
    retired_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT account_retirement_distinct_users CHECK (user_id <> replacement_user_id)
);

LOCK TABLE auth.users IN SHARE ROW EXCLUSIVE MODE;
LOCK TABLE auth.account_retirements IN SHARE ROW EXCLUSIVE MODE;
LOCK TABLE trading.qt_action_grants IN SHARE ROW EXCLUSIVE MODE;
LOCK TABLE trading.qt_approver_allowlist IN SHARE ROW EXCLUSIVE MODE;

ALTER TABLE trading.qt_approver_allowlist
    DROP CONSTRAINT IF EXISTS qt_approver_identity;
ALTER TABLE trading.qt_approver_allowlist
    DROP CONSTRAINT IF EXISTS qt_approver_allowlist_user_id_key;
CREATE UNIQUE INDEX IF NOT EXISTS qt_approver_allowlist_active_user_key
    ON trading.qt_approver_allowlist(user_id) WHERE active;

DO $$
DECLARE
    matched_count bigint;
    john_id bigint;
    hemdutt_id bigint;
    xander_id bigint;
    dominick_id bigint;
    dominick_personal_id bigint;
    actual_role text;
BEGIN
    SELECT count(*), min(id) INTO matched_count, john_id FROM auth.users
      WHERE lower(btrim(email)) = 'john.riley@ufl.edu';
    IF matched_count <> 1 THEN
        RAISE EXCEPTION 'QT identity migration requires exactly one john.riley@ufl.edu account; found %', matched_count;
    END IF;
    SELECT role::text INTO actual_role FROM auth.users WHERE id = john_id;
    IF actual_role IS DISTINCT FROM 'general_member' THEN
        RAISE EXCEPTION 'John Riley must have role general_member; found %', actual_role;
    END IF;

    SELECT count(*), min(id) INTO matched_count, hemdutt_id FROM auth.users
      WHERE lower(btrim(email)) = 'raohemdutt@ufl.edu';
    IF matched_count <> 1 THEN
        RAISE EXCEPTION 'QT identity migration requires exactly one raohemdutt@ufl.edu account; found %', matched_count;
    END IF;
    SELECT role::text INTO actual_role FROM auth.users WHERE id = hemdutt_id;
    IF actual_role IS DISTINCT FROM 'exec_board' THEN
        RAISE EXCEPTION 'Hemdutt Rao must have role exec_board; found %', actual_role;
    END IF;

    SELECT count(*), min(id) INTO matched_count, xander_id FROM auth.users
      WHERE lower(btrim(email)) = 'robbins.a@ufl.edu';
    IF matched_count <> 1 THEN
        RAISE EXCEPTION 'QT identity migration requires exactly one robbins.a@ufl.edu account; found %', matched_count;
    END IF;
    SELECT role::text INTO actual_role FROM auth.users WHERE id = xander_id;
    IF actual_role IS DISTINCT FROM 'general_member' THEN
        RAISE EXCEPTION 'Xander Robbins must have role general_member; found %', actual_role;
    END IF;

    SELECT count(*), min(id) INTO matched_count, dominick_id FROM auth.users
      WHERE lower(btrim(email)) = 'dominickdupuy@ufl.edu';
    IF matched_count <> 1 THEN
        RAISE EXCEPTION 'QT identity migration requires exactly one dominickdupuy@ufl.edu account; found %', matched_count;
    END IF;
    SELECT role::text INTO actual_role FROM auth.users WHERE id = dominick_id;
    IF actual_role IS DISTINCT FROM 'general_member'
       AND actual_role IS DISTINCT FROM 'exec_board' THEN
        RAISE EXCEPTION 'Dominick Dupuy must start as general_member or exec_board; found %', actual_role;
    END IF;
    UPDATE auth.users SET role = 'exec_board'
     WHERE id = dominick_id AND role = 'general_member';
    SELECT role::text INTO actual_role FROM auth.users WHERE id = dominick_id;
    IF actual_role IS DISTINCT FROM 'exec_board' THEN
        RAISE EXCEPTION 'Dominick Dupuy could not be promoted to exec_board';
    END IF;

    SELECT count(*), min(id) INTO matched_count, dominick_personal_id FROM auth.users
      WHERE lower(btrim(email)) = 'domdd305@gmail.com';
    IF matched_count <> 1 THEN
        RAISE EXCEPTION 'QT identity migration requires exactly one domdd305@gmail.com account; found %', matched_count;
    END IF;
    IF dominick_personal_id = dominick_id THEN
        RAISE EXCEPTION 'Dominick personal and UFL identities must be distinct accounts';
    END IF;

    IF EXISTS (
        SELECT 1 FROM trading.qt_approver_allowlist
        WHERE (person_id = 'hemdutt_rao' AND user_id <> hemdutt_id)
           OR (person_id = 'xander_robbins' AND user_id <> xander_id)
           OR (person_id = 'dominick_dupuy' AND user_id <> dominick_id)
    ) THEN
        RAISE EXCEPTION 'QT approval identity conflicts with an existing account mapping';
    END IF;

    UPDATE trading.qt_approver_allowlist
       SET active = false, mapping_version = mapping_version + 1, updated_at = now()
     WHERE active
       AND NOT ((person_id = 'hemdutt_rao' AND user_id = hemdutt_id)
             OR (person_id = 'xander_robbins' AND user_id = xander_id)
             OR (person_id = 'dominick_dupuy' AND user_id = dominick_id));

    UPDATE trading.qt_action_grants
       SET active = false, version = version + 1, updated_at = now()
     WHERE active AND capability = 'qt_submit' AND user_id <> john_id;
    UPDATE trading.qt_action_grants
       SET active = false, version = version + 1, updated_at = now()
     WHERE active AND capability = 'qt_approve'
       AND user_id NOT IN (hemdutt_id, xander_id, dominick_id);

    -- Retire any remaining personal-account authority before recording the
    -- retirement. Rows are deactivated, not deleted, so their versions and
    -- every historical user foreign key remain auditable.
    UPDATE trading.qt_action_grants
       SET active = false, version = version + 1, updated_at = now()
     WHERE user_id = dominick_personal_id AND active;
    UPDATE trading.qt_approver_allowlist
       SET active = false, mapping_version = mapping_version + 1, updated_at = now()
     WHERE user_id = dominick_personal_id AND active;

    INSERT INTO auth.account_retirements(
        user_id, replacement_user_id, reason, retired_by_migration
    ) VALUES (
        dominick_personal_id,
        dominick_id,
        'duplicate personal identity retired in favor of verified UFL account',
        '009_hemdutt_qt_approver'
    )
    ON CONFLICT (user_id) DO NOTHING;

    IF (SELECT count(*) FROM auth.account_retirements
        WHERE user_id = dominick_personal_id
          AND replacement_user_id = dominick_id
          AND reason = 'duplicate personal identity retired in favor of verified UFL account'
          AND retired_by_migration = '009_hemdutt_qt_approver') <> 1 THEN
        RAISE EXCEPTION 'Dominick personal account could not be retired safely';
    END IF;

    INSERT INTO trading.qt_action_grants(user_id, capability, active, version)
    VALUES (john_id, 'qt_submit', true, 1)
    ON CONFLICT (user_id, capability) DO UPDATE SET
      active = true,
      version = CASE WHEN trading.qt_action_grants.active THEN trading.qt_action_grants.version
                     ELSE trading.qt_action_grants.version + 1 END,
      updated_at = CASE WHEN trading.qt_action_grants.active THEN trading.qt_action_grants.updated_at ELSE now() END;

    INSERT INTO trading.qt_action_grants(user_id, capability, active, version)
    VALUES (hemdutt_id, 'qt_approve', true, 1),
           (xander_id, 'qt_approve', true, 1),
           (dominick_id, 'qt_approve', true, 1)
    ON CONFLICT (user_id, capability) DO UPDATE SET
      active = true,
      version = CASE WHEN trading.qt_action_grants.active THEN trading.qt_action_grants.version
                     ELSE trading.qt_action_grants.version + 1 END,
      updated_at = CASE WHEN trading.qt_action_grants.active THEN trading.qt_action_grants.updated_at ELSE now() END;

    INSERT INTO trading.qt_approver_allowlist(person_id, display_label, user_id, active, mapping_version)
    VALUES ('hemdutt_rao', 'hemdutt rao', hemdutt_id, true, 1),
           ('xander_robbins', 'xander robbins', xander_id, true, 1),
           ('dominick_dupuy', 'dominick dupuy', dominick_id, true, 1)
    ON CONFLICT (person_id) DO UPDATE SET
      display_label = EXCLUDED.display_label,
      active = true,
      mapping_version = CASE WHEN trading.qt_approver_allowlist.active
                             THEN trading.qt_approver_allowlist.mapping_version
                             ELSE trading.qt_approver_allowlist.mapping_version + 1 END,
      updated_at = CASE WHEN trading.qt_approver_allowlist.active
                        THEN trading.qt_approver_allowlist.updated_at ELSE now() END
    WHERE trading.qt_approver_allowlist.user_id = EXCLUDED.user_id;

    IF (SELECT count(*) FROM trading.qt_action_grants
        WHERE capability = 'qt_submit' AND active) <> 1
       OR NOT EXISTS (SELECT 1 FROM trading.qt_action_grants
                      WHERE user_id = john_id AND capability = 'qt_submit' AND active) THEN
        RAISE EXCEPTION 'QT submit authority was not made exclusive to John Riley';
    END IF;
    IF (SELECT count(*) FROM trading.qt_action_grants
        WHERE capability = 'qt_approve' AND active) <> 3
       OR (SELECT count(*) FROM trading.qt_approver_allowlist WHERE active) <> 3 THEN
        RAISE EXCEPTION 'QT approval authority was not made exclusive to the three-person pool';
    END IF;
    IF EXISTS (SELECT 1 FROM trading.qt_action_grants
               WHERE user_id = dominick_personal_id AND active)
       OR EXISTS (SELECT 1 FROM trading.qt_approver_allowlist
                  WHERE user_id = dominick_personal_id AND active) THEN
        RAISE EXCEPTION 'Dominick personal account still has active QT authority';
    END IF;
END
$$;

-- Preserve the retirement invariant after this migration: a retired identity
-- cannot be granted or mapped to active QT authority, and an account with live
-- QT authority cannot be retired behind the application's back.
CREATE OR REPLACE FUNCTION auth.reject_retired_qt_authority() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.active AND EXISTS (
        SELECT 1 FROM auth.account_retirements WHERE user_id = NEW.user_id
    ) THEN
        RAISE EXCEPTION 'retired account cannot receive active QT authority';
    END IF;
    RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS qt_grant_reject_retired_account ON trading.qt_action_grants;
CREATE TRIGGER qt_grant_reject_retired_account
    BEFORE INSERT OR UPDATE ON trading.qt_action_grants
    FOR EACH ROW EXECUTE FUNCTION auth.reject_retired_qt_authority();

DROP TRIGGER IF EXISTS qt_mapping_reject_retired_account ON trading.qt_approver_allowlist;
CREATE TRIGGER qt_mapping_reject_retired_account
    BEFORE INSERT OR UPDATE ON trading.qt_approver_allowlist
    FOR EACH ROW EXECUTE FUNCTION auth.reject_retired_qt_authority();

CREATE OR REPLACE FUNCTION auth.reject_retirement_with_active_qt_authority() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM trading.qt_action_grants
               WHERE user_id = NEW.user_id AND active)
       OR EXISTS (SELECT 1 FROM trading.qt_approver_allowlist
                  WHERE user_id = NEW.user_id AND active) THEN
        RAISE EXCEPTION 'account with active QT authority cannot be retired';
    END IF;
    RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS account_retirement_reject_active_qt_authority
    ON auth.account_retirements;
CREATE TRIGGER account_retirement_reject_active_qt_authority
    BEFORE INSERT ON auth.account_retirements
    FOR EACH ROW EXECUTE FUNCTION auth.reject_retirement_with_active_qt_authority();

CREATE OR REPLACE FUNCTION auth.reject_account_retirement_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'account retirement records are immutable';
END $$;

DROP TRIGGER IF EXISTS account_retirement_immutable ON auth.account_retirements;
CREATE TRIGGER account_retirement_immutable
    BEFORE UPDATE OR DELETE ON auth.account_retirements
    FOR EACH ROW EXECUTE FUNCTION auth.reject_account_retirement_change();

-- Historical inactive identities may retain their original spelling/label;
-- only an active mapping must be one of the three approved people. Add this
-- after retiring old active rows so PostgreSQL can validate the whole table.
ALTER TABLE trading.qt_approver_allowlist
    ADD CONSTRAINT qt_approver_identity CHECK (
        NOT active OR
        (person_id = 'xander_robbins' AND display_label = 'xander robbins') OR
        (person_id = 'hemdutt_rao' AND display_label = 'hemdutt rao') OR
        (person_id = 'dominick_dupuy' AND display_label = 'dominick dupuy')
    );

COMMIT;
