-- Guarded access rollback for the QT live-futures runtime contract.
-- It deliberately retains roles, ownership, schemas, functions, and all data.
BEGIN;

DO $qt_rollback_sessions$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_stat_activity
     WHERE usename IN ('qt_migrator','qt_algolens_api','qt_system_publisher','qt_worker')
       AND pid<>pg_backend_pid()
  ) THEN
    RAISE EXCEPTION 'QT role rollback refuses while a runtime/migrator session exists';
  END IF;
END
$qt_rollback_sessions$;

ALTER ROLE qt_algolens_api NOLOGIN;
ALTER ROLE qt_system_publisher NOLOGIN;
ALTER ROLE qt_worker NOLOGIN;

DO $qt_rollback_database_acl$
BEGIN
  EXECUTE format('REVOKE ALL ON DATABASE %I FROM qt_algolens_api,qt_system_publisher,qt_worker',current_database());
END
$qt_rollback_database_acl$;
REVOKE ALL ON SCHEMA auth,trading,futures_data,metadata FROM qt_algolens_api,qt_system_publisher,qt_worker;
REVOKE ALL ON ALL TABLES IN SCHEMA auth,trading FROM qt_algolens_api,qt_system_publisher,qt_worker;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA auth,trading FROM qt_algolens_api,qt_system_publisher,qt_worker;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA auth,trading FROM qt_algolens_api,qt_system_publisher,qt_worker;
REVOKE ALL ON futures_data.ohlcv_1d,metadata.contract_metadata FROM qt_algolens_api,qt_system_publisher,qt_worker;
-- Table-level REVOKE does not remove column-level grants.
DO $live_config_rollback_columns$
DECLARE col record;
BEGIN
 FOR col IN SELECT table_name,column_name FROM information_schema.columns
 WHERE table_schema='trading' AND table_name IN ('live_config_versions','live_config_activations',
   'live_config_active','live_config_attempt_selections','live_config_attempt_safety') LOOP
  EXECUTE format('REVOKE ALL (%I) ON trading.%I FROM qt_algolens_api,qt_system_publisher,qt_worker',col.column_name,col.table_name);
 END LOOP;
END
$live_config_rollback_columns$;
REVOKE qt_schema_owner FROM qt_migrator;

DO $qt_rollback_policies$
DECLARE
  relation_name text;
  policy_name text;
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_policy p JOIN pg_class c ON c.oid=p.polrelid
    JOIN pg_namespace n ON n.oid=c.relnamespace
    WHERE n.nspname='trading'
      AND c.relname IN ('positions','live_results','equity_curve','executions','signals')
      AND p.polname NOT LIKE 'qt_role_%'
  ) THEN
    RAISE EXCEPTION 'rollback refuses an unowned policy on a QT shared stream';
  END IF;
  FOREACH relation_name IN ARRAY ARRAY['positions','live_results','equity_curve','executions','signals'] LOOP
    FOR policy_name IN SELECT p.polname FROM pg_policy p
      JOIN pg_class c ON c.oid=p.polrelid JOIN pg_namespace n ON n.oid=c.relnamespace
      WHERE n.nspname='trading' AND c.relname=relation_name AND p.polname LIKE 'qt_role_%'
    LOOP
      EXECUTE format('DROP POLICY %I ON trading.%I',policy_name,relation_name);
    END LOOP;
    EXECUTE format('ALTER TABLE trading.%I DISABLE ROW LEVEL SECURITY',relation_name);
  END LOOP;
END
$qt_rollback_policies$;

DO $qt_rollback_guards$
DECLARE
  item record;
BEGIN
  FOR item IN SELECT * FROM (VALUES
    ('auth','users'),('trading','strategy_registry'),('trading','qt_action_grants'),
    ('trading','qt_approver_allowlist'),('trading','qt_override_requests'),
    ('trading','qt_override_approvals'),('trading','qt_desk_receipts'),
    ('trading','qt_draft_heads'),('trading','qt_previews'),('trading','qt_decisions'),
    ('trading','runtime_intents'),('trading','run_inputs')
  ) AS values(schema_name,table_name)
  LOOP
    IF EXISTS (
      SELECT 1 FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
      JOIN pg_namespace n ON n.oid=c.relnamespace
      WHERE n.nspname=item.schema_name AND c.relname=item.table_name
        AND t.tgname='aa_qt_role_lock_only_guard' AND NOT t.tgisinternal
        AND t.tgfoid<>'trading.qt_role_reject_lock_mutation()'::regprocedure
    ) THEN
      RAISE EXCEPTION 'rollback refuses changed lock guard on %.%',item.schema_name,item.table_name;
    END IF;
    EXECUTE format('DROP TRIGGER IF EXISTS aa_qt_role_lock_only_guard ON %I.%I',item.schema_name,item.table_name);
  END LOOP;
END
$qt_rollback_guards$;

DROP FUNCTION IF EXISTS trading.qt_role_reject_lock_mutation();

DO $qt_rollback_lock_function$
BEGIN
  IF to_regprocedure('trading.lock_runtime_scope(text,text,boolean)') IS NOT NULL THEN
    IF (SELECT r.rolname FROM pg_proc p JOIN pg_roles r ON r.oid=p.proowner
        WHERE p.oid='trading.lock_runtime_scope(text,text,boolean)'::regprocedure)
       IS DISTINCT FROM 'qt_schema_owner' THEN
      RAISE EXCEPTION 'rollback refuses changed lock_runtime_scope owner';
    END IF;
    ALTER FUNCTION trading.lock_runtime_scope(text,text,boolean) SECURITY INVOKER;
    ALTER FUNCTION trading.lock_runtime_scope(text,text,boolean) RESET search_path;
  END IF;
END
$qt_rollback_lock_function$;

COMMIT;
