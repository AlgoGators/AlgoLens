-- Prerequisites: AlgoLens003/009 and Trade031. No person is automatically enrolled.
BEGIN;
ALTER TABLE trading.qt_action_grants DROP CONSTRAINT qt_action_grants_capability_check;
ALTER TABLE trading.qt_action_grants ADD CONSTRAINT qt_action_grants_capability_check
 CHECK (capability IN ('qt_submit','qt_approve','config_submit','config_approve'));
ALTER TABLE trading.live_config_versions ADD COLUMN IF NOT EXISTS submission_authority jsonb;
ALTER TABLE trading.live_config_versions DROP CONSTRAINT IF EXISTS live_config_submission_authority;
ALTER TABLE trading.live_config_versions ADD CONSTRAINT live_config_submission_authority CHECK
 (submission_authority IS NULL OR (
  jsonb_typeof(submission_authority)='object' AND
  submission_authority ?& ARRAY['user_id','person_id','grant_version','mapping_version'] AND
  submission_authority - ARRAY['user_id','person_id','grant_version','mapping_version'] = '{}'::jsonb AND
  jsonb_typeof(submission_authority->'user_id')='number' AND
  (submission_authority->>'user_id') ~ '^[1-9][0-9]*$' AND
  submission_authority->>'user_id'=submitted_by AND
  submission_authority->>'person_id'=submitter_person_id AND
  jsonb_typeof(submission_authority->'grant_version')='number' AND
  (submission_authority->>'grant_version') ~ '^[1-9][0-9]*$' AND
  jsonb_typeof(submission_authority->'mapping_version')='number' AND
  (submission_authority->>'mapping_version') ~ '^[1-9][0-9]*$'
  ) IS TRUE);
COMMIT;
