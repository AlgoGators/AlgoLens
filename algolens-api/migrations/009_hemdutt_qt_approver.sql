-- Retire the removed approval identity and enroll the one unambiguous Hemdutt Rao account.
-- Inactive historical mappings remain so immutable approval foreign keys stay valid.
BEGIN;

LOCK TABLE auth.users IN SHARE ROW EXCLUSIVE MODE;
LOCK TABLE trading.qt_action_grants IN SHARE ROW EXCLUSIVE MODE;
LOCK TABLE trading.qt_approver_allowlist IN SHARE ROW EXCLUSIVE MODE;

WITH retired AS (
    SELECT user_id
    FROM trading.qt_approver_allowlist
    WHERE person_id = 'eric_shwartz'
    FOR UPDATE
)
UPDATE trading.qt_action_grants AS grant_row
SET active = false,
    version = grant_row.version + 1,
    updated_at = now()
WHERE grant_row.capability = 'qt_approve'
  AND grant_row.active
  AND grant_row.user_id IN (SELECT user_id FROM retired);

UPDATE trading.qt_approver_allowlist
SET active = false,
    mapping_version = mapping_version + 1,
    updated_at = now()
WHERE person_id = 'eric_shwartz'
  AND active;

ALTER TABLE trading.qt_approver_allowlist
    DROP CONSTRAINT IF EXISTS qt_approver_identity;
ALTER TABLE trading.qt_approver_allowlist
    ADD CONSTRAINT qt_approver_identity CHECK (
        NOT active OR
        (person_id = 'john_riley' AND display_label = 'john riley') OR
        (person_id = 'xander_robbins' AND display_label = 'xander robbins') OR
        (person_id = 'hemdutt_rao' AND display_label = 'hemdutt rao') OR
        (person_id = 'dominick_dupuoy' AND display_label = 'dominick dupuoy')
    );

DO $$
DECLARE
    matched_count bigint;
    hemdutt_user_id bigint;
    hemdutt_role text;
BEGIN
    SELECT count(*), min(id)
    INTO matched_count, hemdutt_user_id
    FROM auth.users
    WHERE lower(btrim(coalesce(first_name, ''))) = 'hemdutt'
      AND lower(btrim(coalesce(last_name, ''))) = 'rao';

    IF matched_count <> 1 THEN
        RAISE EXCEPTION 'QT approver enrollment requires exactly one Hemdutt Rao account; found %', matched_count;
    END IF;

    SELECT role::text INTO hemdutt_role
    FROM auth.users
    WHERE id = hemdutt_user_id;
    IF hemdutt_role <> 'exec_board' THEN
        RAISE EXCEPTION 'Hemdutt Rao must retain the exec_board role; found %', hemdutt_role;
    END IF;

    IF EXISTS (
        SELECT 1 FROM trading.qt_approver_allowlist
        WHERE user_id = hemdutt_user_id AND person_id <> 'hemdutt_rao'
    ) OR EXISTS (
        SELECT 1 FROM trading.qt_approver_allowlist
        WHERE person_id = 'hemdutt_rao' AND user_id <> hemdutt_user_id
    ) THEN
        RAISE EXCEPTION 'Hemdutt Rao approval identity conflicts with an existing mapping';
    END IF;

    INSERT INTO trading.qt_action_grants(user_id, capability, active, version)
    VALUES (hemdutt_user_id, 'qt_approve', true, 1)
    ON CONFLICT (user_id, capability) DO UPDATE
    SET active = true,
        version = CASE
            WHEN trading.qt_action_grants.active THEN trading.qt_action_grants.version
            ELSE trading.qt_action_grants.version + 1
        END,
        updated_at = CASE
            WHEN trading.qt_action_grants.active THEN trading.qt_action_grants.updated_at
            ELSE now()
        END;

    INSERT INTO trading.qt_approver_allowlist(person_id, display_label, user_id, active, mapping_version)
    VALUES ('hemdutt_rao', 'hemdutt rao', hemdutt_user_id, true, 1)
    ON CONFLICT (person_id) DO UPDATE
    SET display_label = 'hemdutt rao',
        active = true,
        mapping_version = CASE
            WHEN trading.qt_approver_allowlist.active THEN trading.qt_approver_allowlist.mapping_version
            ELSE trading.qt_approver_allowlist.mapping_version + 1
        END,
        updated_at = CASE
            WHEN trading.qt_approver_allowlist.active THEN trading.qt_approver_allowlist.updated_at
            ELSE now()
        END
    WHERE trading.qt_approver_allowlist.user_id = EXCLUDED.user_id;

    IF NOT EXISTS (
        SELECT 1 FROM trading.qt_approver_allowlist
        WHERE person_id = 'hemdutt_rao'
          AND user_id = hemdutt_user_id
          AND display_label = 'hemdutt rao'
          AND active
    ) THEN
        RAISE EXCEPTION 'Hemdutt Rao approval identity was not enrolled';
    END IF;
END
$$;

COMMIT;
