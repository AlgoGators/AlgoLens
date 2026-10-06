-- Resolve the four named production identities without guessed IDs.
-- John Riley is the sole QT submitter. Hemdutt Rao, Xander Robbins and
-- Dominick Dupuy are the only active approvers. Historical mappings (including
-- Eric Shwartz and the old dominick_dupuoy spelling) remain inactive so
-- immutable approval foreign keys continue to resolve.
BEGIN;

LOCK TABLE auth.users IN SHARE ROW EXCLUSIVE MODE;
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
    actual_role text;
BEGIN
    SELECT count(*), min(id) INTO matched_count, john_id FROM auth.users
      WHERE lower(btrim(coalesce(first_name, ''))) = 'john'
        AND lower(btrim(coalesce(last_name, ''))) = 'riley';
    IF matched_count <> 1 THEN
        RAISE EXCEPTION 'QT identity migration requires exactly one John Riley account; found %', matched_count;
    END IF;
    SELECT role::text INTO actual_role FROM auth.users WHERE id = john_id;
    IF actual_role <> 'general_member' THEN
        RAISE EXCEPTION 'John Riley must have role general_member; found %', actual_role;
    END IF;

    SELECT count(*), min(id) INTO matched_count, hemdutt_id FROM auth.users
      WHERE lower(btrim(coalesce(first_name, ''))) = 'hemdutt'
        AND lower(btrim(coalesce(last_name, ''))) = 'rao';
    IF matched_count <> 1 THEN
        RAISE EXCEPTION 'QT identity migration requires exactly one Hemdutt Rao account; found %', matched_count;
    END IF;
    SELECT role::text INTO actual_role FROM auth.users WHERE id = hemdutt_id;
    IF actual_role <> 'exec_board' THEN
        RAISE EXCEPTION 'Hemdutt Rao must have role exec_board; found %', actual_role;
    END IF;

    SELECT count(*), min(id) INTO matched_count, xander_id FROM auth.users
      WHERE lower(btrim(coalesce(first_name, ''))) = 'xander'
        AND lower(btrim(coalesce(last_name, ''))) = 'robbins';
    IF matched_count <> 1 THEN
        RAISE EXCEPTION 'QT identity migration requires exactly one Xander Robbins account; found %', matched_count;
    END IF;
    SELECT role::text INTO actual_role FROM auth.users WHERE id = xander_id;
    IF actual_role <> 'general_member' THEN
        RAISE EXCEPTION 'Xander Robbins must have role general_member; found %', actual_role;
    END IF;

    SELECT count(*), min(id) INTO matched_count, dominick_id FROM auth.users
      WHERE lower(btrim(coalesce(first_name, ''))) = 'dominick'
        AND lower(btrim(coalesce(last_name, ''))) = 'dupuy';
    IF matched_count <> 1 THEN
        RAISE EXCEPTION 'QT identity migration requires exactly one Dominick Dupuy account; found %', matched_count;
    END IF;
    SELECT role::text INTO actual_role FROM auth.users WHERE id = dominick_id;
    IF actual_role <> 'general_member' THEN
        RAISE EXCEPTION 'Dominick Dupuy must have role general_member; found %', actual_role;
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
END
$$;

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
