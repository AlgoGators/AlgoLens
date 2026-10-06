BEGIN;
LOCK TABLE trading.qt_action_grants,trading.live_config_versions IN ACCESS EXCLUSIVE MODE;
DO $$ BEGIN
 IF EXISTS (SELECT 1 FROM trading.qt_action_grants WHERE capability IN ('config_submit','config_approve'))
 OR EXISTS (SELECT 1 FROM trading.live_config_versions WHERE submission_authority IS NOT NULL) THEN
  RAISE EXCEPTION 'live_config_authority_history_exists';
 END IF;
END $$;
ALTER TABLE trading.live_config_versions DROP COLUMN submission_authority;
ALTER TABLE trading.qt_action_grants DROP CONSTRAINT qt_action_grants_capability_check;
ALTER TABLE trading.qt_action_grants ADD CONSTRAINT qt_action_grants_capability_check
 CHECK (capability IN ('qt_submit','qt_approve'));
COMMIT;
