-- Final cross-repository QT live-futures authorization postlude.
-- Credentials are provisioned out of band. This file contains no passwords.
BEGIN;

DO $qt_roles$
DECLARE
  role_name text;
  unexpected bigint;
BEGIN
  FOREACH role_name IN ARRAY ARRAY[
    'qt_schema_owner','qt_migrator','qt_algolens_api','qt_system_publisher','qt_worker'
  ] LOOP
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname=role_name) THEN
      IF EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname=role_name
          AND (rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls)
      ) THEN
        RAISE EXCEPTION 'refusing privileged pre-existing QT role: %',role_name;
      END IF;
    ELSE
      EXECUTE format('CREATE ROLE %I',role_name);
    END IF;
  END LOOP;

  SELECT count(*) INTO unexpected
    FROM pg_auth_members m
    JOIN pg_roles parent ON parent.oid=m.roleid
    JOIN pg_roles member ON member.oid=m.member
   WHERE member.rolname IN
     ('qt_schema_owner','qt_migrator','qt_algolens_api','qt_system_publisher','qt_worker')
     AND NOT (member.rolname='qt_migrator' AND parent.rolname='qt_schema_owner');
  IF unexpected<>0 THEN
    RAISE EXCEPTION 'refusing unexpected QT role membership';
  END IF;

  ALTER ROLE qt_schema_owner NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
  ALTER ROLE qt_migrator NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
  ALTER ROLE qt_algolens_api LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
  ALTER ROLE qt_system_publisher LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
  ALTER ROLE qt_worker LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
END
$qt_roles$;

GRANT qt_schema_owner TO qt_migrator WITH INHERIT FALSE, SET TRUE;

ALTER ROLE qt_schema_owner SET search_path TO pg_catalog;
ALTER ROLE qt_migrator SET search_path TO pg_catalog;
ALTER ROLE qt_algolens_api SET search_path TO pg_catalog;
ALTER ROLE qt_system_publisher SET search_path TO pg_catalog;
ALTER ROLE qt_worker SET search_path TO pg_catalog;
ALTER ROLE qt_algolens_api SET row_security TO on;
ALTER ROLE qt_system_publisher SET row_security TO on;
ALTER ROLE qt_worker SET row_security TO on;

DO $qt_database_acl$
BEGIN
  EXECUTE format('REVOKE TEMPORARY ON DATABASE %I FROM PUBLIC',current_database());
  EXECUTE format('REVOKE CREATE,TEMPORARY ON DATABASE %I FROM qt_schema_owner,qt_migrator,qt_algolens_api,qt_system_publisher,qt_worker',current_database());
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO qt_algolens_api,qt_system_publisher,qt_worker',current_database());
END
$qt_database_acl$;

DO $qt_prerequisites$
DECLARE
  relation_name text;
BEGIN
  IF current_setting('server_version_num')::integer/10000<>16 THEN
    RAISE EXCEPTION 'QT role contract requires PostgreSQL 16';
  END IF;
  FOREACH relation_name IN ARRAY ARRAY[
    'auth.users','auth.account_retirements',
    'trading.strategy_registry','trading.strategy_book_memberships','trading.portfolios',
    'trading.portfolio_assignments','trading.strategy_lifecycle_log','trading.positions',
    'trading.position_overrides','trading.position_override_legacy_scopes','trading.risk_limits',
    'trading.live_results','trading.equity_curve','trading.executions','trading.signals',
    'trading.live_run_metadata','trading.run_inputs','trading.runtime_intents','trading.runtime_attempts',
    'trading.strategy_trading_days_metadata','trading.qt_workflow_capabilities',
    'trading.qt_action_grants','trading.qt_approver_allowlist','trading.qt_drafts',
    'trading.qt_draft_heads','trading.qt_previews','trading.qt_decisions',
    'trading.qt_override_requests','trading.qt_override_approvals','trading.qt_desk_receipts',
    'trading.qt_idempotency','trading.qt_source_policies','trading.qt_evaluation_snapshots',
    'trading.qt_execution_observations','trading.qt_desk_results','trading.qt_storage_capabilities',
    'trading.qt_model_seed_publications','trading.qt_desk_accounting_inputs',
    'trading.qt_desk_finalization_sources','trading.desk_run_results',
    'trading.qt_desk_market_sources','trading.qt_desk_finalizations',
    'trading.qt_first_day_anchors','trading.qt_desk_dispatch_jobs',
    'trading.qt_desk_dispatch_attempts','futures_data.ohlcv_1d','metadata.contract_metadata'
  ] LOOP
    IF to_regclass(relation_name) IS NULL THEN
      RAISE EXCEPTION 'QT role contract prerequisite missing: %',relation_name;
    END IF;
  END LOOP;
  IF to_regclass('trading.investor_books') IS NOT NULL
     OR to_regclass('trading.investor_book_publications') IS NOT NULL
     OR to_regclass('trading.qt_investor_publications') IS NOT NULL THEN
    RAISE EXCEPTION 'investor schema is outside the live-futures role contract';
  END IF;
END
$qt_prerequisites$;

-- Reassign only the two application schemas; data-owner schemas stay external.
DO $qt_reown$
DECLARE
  item record;
BEGIN
  FOR item IN
    SELECT n.nspname,c.relname,c.relkind
      FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
     WHERE n.nspname IN ('auth','trading') AND c.relkind IN ('r','p','v','m','S','f')
     ORDER BY n.nspname,c.relname
  LOOP
    IF item.relkind IN ('r','p') THEN
      EXECUTE format('ALTER TABLE %I.%I OWNER TO qt_schema_owner',item.nspname,item.relname);
    ELSIF item.relkind='S' THEN
      EXECUTE format('ALTER SEQUENCE %I.%I OWNER TO qt_schema_owner',item.nspname,item.relname);
    ELSIF item.relkind='v' THEN
      EXECUTE format('ALTER VIEW %I.%I OWNER TO qt_schema_owner',item.nspname,item.relname);
    ELSIF item.relkind='m' THEN
      EXECUTE format('ALTER MATERIALIZED VIEW %I.%I OWNER TO qt_schema_owner',item.nspname,item.relname);
    ELSIF item.relkind='f' THEN
      EXECUTE format('ALTER FOREIGN TABLE %I.%I OWNER TO qt_schema_owner',item.nspname,item.relname);
    END IF;
  END LOOP;
  FOR item IN
    SELECT n.nspname,t.typname,t.typtype
      FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace
     WHERE n.nspname IN ('auth','trading') AND t.typtype IN ('d','e','r')
       AND t.typrelid=0
       AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid=t.oid AND d.deptype='e')
     ORDER BY n.nspname,t.typname
  LOOP
    IF item.typtype='d' THEN
      EXECUTE format('ALTER DOMAIN %I.%I OWNER TO qt_schema_owner',item.nspname,item.typname);
    ELSE
      EXECUTE format('ALTER TYPE %I.%I OWNER TO qt_schema_owner',item.nspname,item.typname);
    END IF;
  END LOOP;
  FOR item IN
    SELECT n.nspname,p.proname,pg_get_function_identity_arguments(p.oid) AS args,p.prokind
      FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
     WHERE n.nspname IN ('auth','trading') AND p.prokind IN ('f','p')
     ORDER BY n.nspname,p.proname,args
  LOOP
    IF item.prokind='p' THEN
      EXECUTE format('ALTER PROCEDURE %I.%I(%s) OWNER TO qt_schema_owner',item.nspname,item.proname,item.args);
    ELSE
      EXECUTE format('ALTER FUNCTION %I.%I(%s) OWNER TO qt_schema_owner',item.nspname,item.proname,item.args);
    END IF;
  END LOOP;
  ALTER SCHEMA auth OWNER TO qt_schema_owner;
  ALTER SCHEMA trading OWNER TO qt_schema_owner;
END
$qt_reown$;

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON SCHEMA auth,trading FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA auth,trading FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA auth,trading FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA auth,trading FROM PUBLIC;
REVOKE ALL ON futures_data.ohlcv_1d,metadata.contract_metadata FROM PUBLIC;

REVOKE ALL ON ALL TABLES IN SCHEMA auth,trading FROM qt_algolens_api,qt_system_publisher,qt_worker;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA auth,trading FROM qt_algolens_api,qt_system_publisher,qt_worker;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA auth,trading FROM qt_algolens_api,qt_system_publisher,qt_worker;
REVOKE ALL ON futures_data.ohlcv_1d,metadata.contract_metadata FROM qt_algolens_api,qt_system_publisher,qt_worker;
REVOKE ALL ON SCHEMA auth,trading,futures_data,metadata FROM qt_algolens_api,qt_system_publisher,qt_worker;

ALTER DEFAULT PRIVILEGES FOR ROLE qt_schema_owner IN SCHEMA auth,trading REVOKE ALL ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE qt_schema_owner IN SCHEMA auth,trading REVOKE ALL ON SEQUENCES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE qt_schema_owner IN SCHEMA auth,trading REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;

GRANT USAGE ON SCHEMA trading TO qt_algolens_api,qt_system_publisher,qt_worker;
GRANT USAGE ON SCHEMA auth TO qt_algolens_api,qt_worker;
GRANT USAGE ON SCHEMA futures_data,metadata TO qt_algolens_api,qt_system_publisher,qt_worker;
GRANT SELECT ON futures_data.ohlcv_1d,metadata.contract_metadata TO qt_algolens_api,qt_system_publisher,qt_worker;

GRANT SELECT ON auth.users,auth.account_retirements TO qt_algolens_api;
GRANT SELECT ON auth.users TO qt_worker;
GRANT UPDATE(password_hash,first_name,last_name) ON auth.users TO qt_algolens_api;

GRANT SELECT ON
  trading.strategy_registry,trading.strategy_book_memberships,trading.portfolios,
  trading.portfolio_assignments,trading.strategy_lifecycle_log,trading.positions,
  trading.position_overrides,trading.position_override_legacy_scopes,trading.risk_limits,
  trading.live_results,trading.equity_curve,trading.executions,trading.live_run_metadata,
  trading.run_inputs,trading.runtime_intents,trading.runtime_attempts,
  trading.qt_workflow_capabilities,trading.qt_action_grants,trading.qt_approver_allowlist,
  trading.qt_drafts,trading.qt_draft_heads,trading.qt_previews,trading.qt_decisions,
  trading.qt_override_requests,trading.qt_override_approvals,trading.qt_desk_receipts,
  trading.qt_idempotency,trading.qt_source_policies,trading.qt_evaluation_snapshots,
  trading.qt_execution_observations,trading.qt_desk_results,trading.qt_storage_capabilities,
  trading.qt_model_seed_publications,trading.qt_desk_accounting_inputs,
  trading.qt_desk_finalization_sources,trading.desk_run_results,
  trading.qt_desk_market_sources,trading.qt_desk_finalizations,trading.qt_first_day_anchors
TO qt_algolens_api;

-- Readiness needs queue health, not decision identities or mutation authority.
GRANT SELECT(state,first_seen_at,lease_expires_at)
 ON trading.qt_desk_dispatch_jobs TO qt_algolens_api;

GRANT INSERT(draft_id,book_id,source_day,revision,model_publication_id,model_publication_version,
 seed_digest,source_digest,provenance_digest,draft_digest,selection_payload,created_by,updated_by)
 ON trading.qt_drafts TO qt_algolens_api;
GRANT INSERT(preview_id,book_id,source_day,draft_id,draft_revision,draft_digest,source_digest,
 provenance_digest,read_set_digest,optimizer_book_digest,selected_book_digest,payload_digest,
 payload,read_set_payload,evaluator_build,policy_version,availability,created_by,state)
 ON trading.qt_previews TO qt_algolens_api;
GRANT INSERT(decision_id,preview_id,book_id,source_day,status,model_publication_id,
 provenance_digest,draft_id,draft_revision,selected_book_digest,read_set_digest,
 workflow_capability_version,submitter_grant_version,policy_version,payload,created_by)
 ON trading.qt_decisions TO qt_algolens_api;
GRANT INSERT(request_id,decision_id,eligibility_version,required_approvals)
 ON trading.qt_override_requests TO qt_algolens_api;
GRANT INSERT(approval_id,request_id,person_id,user_id,mapping_version,grant_version)
 ON trading.qt_override_approvals TO qt_algolens_api;
GRANT INSERT(actor_id,book_id,operation,scope_id,idempotency_key,request_digest,response_payload)
 ON trading.qt_idempotency TO qt_algolens_api;
GRANT INSERT(book_id,source_day,draft_id,revision),UPDATE(draft_id,revision)
 ON trading.qt_draft_heads TO qt_algolens_api;
GRANT UPDATE(state) ON trading.qt_previews TO qt_algolens_api;
GRANT UPDATE(status) ON trading.qt_decisions TO qt_algolens_api;
GRANT INSERT(registry_id,portfolio_id,engine_strategy_id,action,registry_revision,config_snapshot,
 status,requested_by,request_reason),UPDATE(status,approved_by,approval_reason,approved_at)
 ON trading.runtime_intents TO qt_algolens_api;

GRANT SELECT ON
  trading.strategy_registry,trading.strategy_book_memberships,trading.runtime_intents,
  trading.runtime_attempts,trading.positions,trading.risk_limits,trading.live_results,
  trading.equity_curve,trading.executions,trading.signals,trading.live_run_metadata,
  trading.run_inputs,trading.qt_storage_capabilities,trading.qt_model_seed_publications,
  trading.strategy_trading_days_metadata
TO qt_system_publisher;
GRANT INSERT,UPDATE,DELETE ON trading.positions,trading.live_results,
  trading.equity_curve,trading.executions,trading.signals TO qt_system_publisher;
GRANT INSERT,UPDATE ON trading.risk_limits,trading.live_run_metadata TO qt_system_publisher;
GRANT INSERT ON trading.run_inputs,trading.runtime_attempts,trading.qt_model_seed_publications
  TO qt_system_publisher;
GRANT UPDATE(status,outcome,publication_id,failure_code,finished_at)
  ON trading.runtime_attempts TO qt_system_publisher;

GRANT SELECT ON
  trading.strategy_registry,trading.strategy_book_memberships,trading.positions,
  trading.position_overrides,trading.position_override_legacy_scopes,trading.risk_limits,
  trading.live_results,trading.equity_curve,trading.executions,trading.live_run_metadata,
  trading.run_inputs,trading.runtime_intents,trading.runtime_attempts,
  trading.qt_workflow_capabilities,trading.qt_action_grants,trading.qt_approver_allowlist,
  trading.qt_drafts,trading.qt_draft_heads,trading.qt_previews,trading.qt_decisions,
  trading.qt_override_requests,trading.qt_override_approvals,trading.qt_desk_receipts,
  trading.qt_idempotency,trading.qt_source_policies,trading.qt_evaluation_snapshots,
  trading.qt_execution_observations,trading.qt_desk_results,trading.qt_storage_capabilities,
  trading.qt_model_seed_publications,trading.qt_desk_accounting_inputs,
  trading.qt_desk_finalization_sources,trading.desk_run_results,
  trading.qt_desk_market_sources,trading.qt_desk_finalizations,trading.qt_first_day_anchors,
  trading.qt_desk_dispatch_jobs,trading.qt_desk_dispatch_attempts
TO qt_worker;
GRANT INSERT,UPDATE ON trading.positions TO qt_worker;
GRANT INSERT,UPDATE,DELETE ON trading.live_results TO qt_worker;
GRANT INSERT,UPDATE ON trading.equity_curve TO qt_worker;
GRANT INSERT,DELETE ON trading.executions TO qt_worker;
GRANT INSERT ON trading.position_overrides,trading.qt_execution_observations,
  trading.qt_desk_results,trading.qt_desk_accounting_inputs,trading.desk_run_results,
  trading.qt_desk_market_sources,trading.qt_desk_finalizations,
  trading.qt_desk_finalization_sources,trading.qt_first_day_anchors TO qt_worker;
GRANT INSERT ON trading.qt_desk_receipts TO qt_worker;
GRANT UPDATE(status,published_book_digest,processed_at,publication_payload,
 report_eligibility_status,report_reason_codes,row_manifest_digest)
 ON trading.qt_desk_receipts TO qt_worker;

-- Serial/identity privileges are resolved from the admitted insert columns only.
DO $qt_sequences$
DECLARE
  item record;
  sequence_name text;
  sequence_schema text;
BEGIN
  FOR item IN SELECT * FROM (VALUES
    ('qt_algolens_api','trading','runtime_intents','id'),
    ('qt_worker','trading','position_overrides','id'),
    ('qt_system_publisher','trading','live_results','id'),
    ('qt_system_publisher','trading','equity_curve','id'),
    ('qt_system_publisher','trading','live_run_metadata','id'),
    ('qt_system_publisher','trading','risk_limits','id'),
    ('qt_system_publisher','trading','signals','id'),
    ('qt_worker','trading','live_results','id'),
    ('qt_worker','trading','equity_curve','id')
  ) AS values(role_name,schema_name,table_name,column_name)
  LOOP
    sequence_name:=pg_get_serial_sequence(
      format('%I.%I',item.schema_name,item.table_name),item.column_name);
    IF sequence_name IS NULL THEN
      RAISE EXCEPTION 'required admitted sequence missing for %.%',item.table_name,item.column_name;
    END IF;
    SELECT n.nspname INTO sequence_schema
      FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
     WHERE c.oid=sequence_name::regclass AND c.relkind='S';
    IF sequence_schema IS DISTINCT FROM 'trading' THEN
      RAISE EXCEPTION 'admitted sequence escaped trading schema';
    END IF;
    EXECUTE format('GRANT USAGE,SELECT ON SEQUENCE %s TO %I',sequence_name,item.role_name);
  END LOOP;
END
$qt_sequences$;

-- Shared financial streams require row predicates, not only table ACLs.
DO $qt_rls$
DECLARE
  relation_name text;
  policy_name text;
  publisher_predicate text;
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_policy p JOIN pg_class c ON c.oid=p.polrelid
    JOIN pg_namespace n ON n.oid=c.relnamespace
    WHERE n.nspname='trading'
      AND c.relname IN ('positions','live_results','equity_curve','executions','signals')
      AND p.polname NOT LIKE 'qt_role_%'
  ) THEN
    RAISE EXCEPTION 'unexpected pre-existing policy on QT shared stream';
  END IF;
  FOREACH relation_name IN ARRAY ARRAY['positions','live_results','equity_curve','executions','signals'] LOOP
    EXECUTE format('ALTER TABLE trading.%I ENABLE ROW LEVEL SECURITY',relation_name);
    FOR policy_name IN SELECT polname FROM pg_policy p
      JOIN pg_class c ON c.oid=p.polrelid JOIN pg_namespace n ON n.oid=c.relnamespace
      WHERE n.nspname='trading' AND c.relname=relation_name AND polname LIKE 'qt_role_%'
    LOOP
      EXECUTE format('DROP POLICY %I ON trading.%I',policy_name,relation_name);
    END LOOP;
    -- Signals are a legacy, System-only table: no portfolio_type exists and
    -- the native writer rejects signals for non-System results. Do not invent
    -- a QT stream here or grant a worker policy on the publisher-only table.
    publisher_predicate:=CASE WHEN relation_name='signals' THEN 'true'
      WHEN relation_name='positions'
      THEN 'portfolio_type IN (''system'',''qt_proposal'')'
      ELSE 'portfolio_type=''system''' END;
    EXECUTE format('CREATE POLICY qt_role_read_all ON trading.%I FOR SELECT TO qt_algolens_api,qt_system_publisher,qt_worker USING (true)',relation_name);
    EXECUTE format('CREATE POLICY qt_role_publisher_insert ON trading.%I FOR INSERT TO qt_system_publisher WITH CHECK (%s)',relation_name,publisher_predicate);
    EXECUTE format('CREATE POLICY qt_role_publisher_update ON trading.%I FOR UPDATE TO qt_system_publisher USING (%s) WITH CHECK (%s)',relation_name,publisher_predicate,publisher_predicate);
    EXECUTE format('CREATE POLICY qt_role_publisher_delete ON trading.%I FOR DELETE TO qt_system_publisher USING (%s)',relation_name,publisher_predicate);
    IF relation_name<>'signals' THEN
      EXECUTE format('CREATE POLICY qt_role_worker_insert ON trading.%I FOR INSERT TO qt_worker WITH CHECK (portfolio_type=''qt'')',relation_name);
      EXECUTE format('CREATE POLICY qt_role_worker_update ON trading.%I FOR UPDATE TO qt_worker USING (portfolio_type=''qt'') WITH CHECK (portfolio_type=''qt'')',relation_name);
      EXECUTE format('CREATE POLICY qt_role_worker_delete ON trading.%I FOR DELETE TO qt_worker USING (portfolio_type=''qt'')',relation_name);
    END IF;
  END LOOP;
END
$qt_rls$;

-- Column UPDATE is required by PostgreSQL for SELECT ... FOR UPDATE. Each
-- nominal lock column has a trigger that rejects an actual UPDATE with 42501.
CREATE OR REPLACE FUNCTION trading.qt_role_reject_lock_mutation()
RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $qt_guard$
BEGIN
  IF current_user::text=ANY(TG_ARGV) THEN
    RAISE EXCEPTION 'QT role is lock-only on this relation' USING ERRCODE='42501';
  END IF;
  RETURN NEW;
END
$qt_guard$;
ALTER FUNCTION trading.qt_role_reject_lock_mutation() OWNER TO qt_schema_owner;
REVOKE ALL ON FUNCTION trading.qt_role_reject_lock_mutation() FROM PUBLIC;

GRANT UPDATE(id) ON auth.users TO qt_worker;
GRANT UPDATE(id) ON trading.strategy_registry TO qt_algolens_api,qt_worker;
GRANT UPDATE(user_id) ON trading.qt_action_grants TO qt_algolens_api,qt_worker;
GRANT UPDATE(person_id) ON trading.qt_approver_allowlist TO qt_algolens_api,qt_worker;
GRANT UPDATE(request_id) ON trading.qt_override_requests TO qt_algolens_api,qt_worker;
GRANT UPDATE(approval_id) ON trading.qt_override_approvals TO qt_algolens_api,qt_worker;
GRANT UPDATE(decision_id) ON trading.qt_desk_receipts TO qt_algolens_api;
GRANT UPDATE(book_id) ON trading.qt_draft_heads TO qt_worker;
GRANT UPDATE(preview_id) ON trading.qt_previews TO qt_worker;
GRANT UPDATE(decision_id) ON trading.qt_decisions TO qt_worker;
GRANT UPDATE(id) ON trading.runtime_intents TO qt_system_publisher;
GRANT UPDATE(portfolio_id) ON trading.run_inputs TO qt_system_publisher;

DO $qt_lock_guards$
DECLARE
  item record;
BEGIN
  FOR item IN SELECT * FROM (VALUES
    ('auth','users','id','qt_worker'),
    ('trading','strategy_registry','id','qt_algolens_api,qt_worker'),
    ('trading','qt_action_grants','user_id','qt_algolens_api,qt_worker'),
    ('trading','qt_approver_allowlist','person_id','qt_algolens_api,qt_worker'),
    ('trading','qt_override_requests','request_id','qt_algolens_api,qt_worker'),
    ('trading','qt_override_approvals','approval_id','qt_algolens_api,qt_worker'),
    ('trading','qt_desk_receipts','decision_id','qt_algolens_api'),
    ('trading','qt_draft_heads','book_id','qt_worker'),
    ('trading','qt_previews','preview_id','qt_worker'),
    ('trading','qt_decisions','decision_id','qt_worker'),
    ('trading','runtime_intents','id','qt_system_publisher'),
    ('trading','run_inputs','portfolio_id','qt_system_publisher')
  ) AS values(schema_name,table_name,column_name,role_names)
  LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS qt_role_lock_only_guard ON %I.%I',item.schema_name,item.table_name);
    EXECUTE format('DROP TRIGGER IF EXISTS aa_qt_role_lock_only_guard ON %I.%I',item.schema_name,item.table_name);
    EXECUTE format(
      'CREATE TRIGGER aa_qt_role_lock_only_guard BEFORE UPDATE OF %I ON %I.%I FOR EACH ROW EXECUTE FUNCTION trading.qt_role_reject_lock_mutation(%s)',
      item.column_name,item.schema_name,item.table_name,
      (SELECT string_agg(quote_literal(value),',') FROM unnest(string_to_array(item.role_names,',')) value)
    );
  END LOOP;
END
$qt_lock_guards$;

-- Harden only the reviewed cross-role entry points.
DO $qt_functions$
DECLARE
  function_oid oid;
  source_text text;
BEGIN
  IF to_regprocedure('trading.lock_runtime_scope(text,text,boolean)') IS NULL THEN
    RAISE EXCEPTION 'reviewed lock_runtime_scope signature missing';
  END IF;
  SELECT p.oid,p.prosrc INTO function_oid,source_text FROM pg_proc p
   WHERE p.oid='trading.lock_runtime_scope(text,text,boolean)'::regprocedure;
  IF position('trading.strategy_registry' in source_text)=0 THEN
    RAISE EXCEPTION 'lock_runtime_scope definition is outside the reviewed live scope';
  END IF;

  IF (SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
      WHERE n.nspname='trading' AND p.proname='get_trading_days')<>2
     OR to_regprocedure('trading.get_trading_days(character varying,date)') IS NULL
     OR to_regprocedure('trading.get_trading_days(character varying,date,character varying)') IS NULL THEN
    RAISE EXCEPTION 'get_trading_days overload set differs from audited production';
  END IF;
  FOR function_oid IN SELECT p.oid FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
    WHERE n.nspname='trading' AND p.proname='get_trading_days'
  LOOP
    SELECT p.prosrc INTO source_text FROM pg_proc p WHERE p.oid=function_oid;
    IF (SELECT prosecdef FROM pg_proc WHERE oid=function_oid)
       OR position('trading.strategy_trading_days_metadata' in source_text)=0
       OR position('trading.live_results' in source_text)=0 THEN
      RAISE EXCEPTION 'get_trading_days definition failed the audited invoker/scope contract';
    END IF;
  END LOOP;
END
$qt_functions$;

ALTER FUNCTION trading.lock_runtime_scope(text,text,boolean) SECURITY DEFINER;
ALTER FUNCTION trading.lock_runtime_scope(text,text,boolean) SET search_path TO pg_catalog,trading;
ALTER FUNCTION trading.lock_runtime_scope(text,text,boolean) OWNER TO qt_schema_owner;
REVOKE ALL ON FUNCTION trading.lock_runtime_scope(text,text,boolean) FROM PUBLIC;
-- The worker reaches this function through the invoker-mode
-- fence_runtime_publication_row() trigger on its admitted QT stream writes.
GRANT EXECUTE ON FUNCTION trading.lock_runtime_scope(text,text,boolean)
  TO qt_system_publisher,qt_worker;

ALTER FUNCTION trading.get_trading_days(character varying,date) SECURITY INVOKER;
ALTER FUNCTION trading.get_trading_days(character varying,date) SET search_path TO pg_catalog,trading;
ALTER FUNCTION trading.get_trading_days(character varying,date) OWNER TO qt_schema_owner;
ALTER FUNCTION trading.get_trading_days(character varying,date,character varying) SECURITY INVOKER;
ALTER FUNCTION trading.get_trading_days(character varying,date,character varying) SET search_path TO pg_catalog,trading;
ALTER FUNCTION trading.get_trading_days(character varying,date,character varying) OWNER TO qt_schema_owner;
REVOKE ALL ON FUNCTION trading.get_trading_days(character varying,date) FROM PUBLIC;
REVOKE ALL ON FUNCTION trading.get_trading_days(character varying,date,character varying) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION trading.get_trading_days(character varying,date) TO qt_system_publisher;

ALTER FUNCTION trading.enqueue_qt_desk_dispatch(uuid,uuid,uuid,uuid,uuid) SECURITY DEFINER;
ALTER FUNCTION trading.enqueue_qt_desk_dispatch(uuid,uuid,uuid,uuid,uuid) SET search_path TO pg_catalog,trading;
ALTER FUNCTION trading.enqueue_qt_desk_dispatch(uuid,uuid,uuid,uuid,uuid) OWNER TO qt_schema_owner;
ALTER FUNCTION trading.claim_qt_desk_dispatch(uuid,interval) SECURITY DEFINER;
ALTER FUNCTION trading.claim_qt_desk_dispatch(uuid,interval) SET search_path TO pg_catalog,trading;
ALTER FUNCTION trading.claim_qt_desk_dispatch(uuid,interval) OWNER TO qt_schema_owner;
ALTER FUNCTION trading.finish_qt_desk_dispatch(uuid,uuid,text,text,text,interval) SECURITY DEFINER;
ALTER FUNCTION trading.finish_qt_desk_dispatch(uuid,uuid,text,text,text,interval) SET search_path TO pg_catalog,trading;
ALTER FUNCTION trading.finish_qt_desk_dispatch(uuid,uuid,text,text,text,interval) OWNER TO qt_schema_owner;
ALTER FUNCTION trading.renew_qt_desk_dispatch(uuid,uuid,interval) SECURITY DEFINER;
ALTER FUNCTION trading.renew_qt_desk_dispatch(uuid,uuid,interval) SET search_path TO pg_catalog,trading;
ALTER FUNCTION trading.renew_qt_desk_dispatch(uuid,uuid,interval) OWNER TO qt_schema_owner;
REVOKE ALL ON FUNCTION trading.enqueue_qt_desk_dispatch(uuid,uuid,uuid,uuid,uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION trading.claim_qt_desk_dispatch(uuid,interval) FROM PUBLIC;
REVOKE ALL ON FUNCTION trading.finish_qt_desk_dispatch(uuid,uuid,text,text,text,interval) FROM PUBLIC;
REVOKE ALL ON FUNCTION trading.renew_qt_desk_dispatch(uuid,uuid,interval) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION trading.enqueue_qt_desk_dispatch(uuid,uuid,uuid,uuid,uuid) TO qt_worker;
GRANT EXECUTE ON FUNCTION trading.claim_qt_desk_dispatch(uuid,interval) TO qt_worker;
GRANT EXECUTE ON FUNCTION trading.finish_qt_desk_dispatch(uuid,uuid,text,text,text,interval) TO qt_worker;
GRANT EXECUTE ON FUNCTION trading.renew_qt_desk_dispatch(uuid,uuid,interval) TO qt_worker;

-- Final role-shape assertions turn accidental normalization into a failure.
-- Governed configuration extension is optional for historical installations.
-- When present it must be complete (Trade031 then AlgoLens011); partial enablement refuses.
DO $live_config_roles$
DECLARE relation_name text; col record;
BEGIN
 IF to_regclass('trading.live_config_versions') IS NOT NULL THEN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='trading'
                 AND table_name='live_config_versions' AND column_name='submission_authority') THEN
   RAISE EXCEPTION 'live config authority migration required';
  END IF;
  FOREACH relation_name IN ARRAY ARRAY['live_config_versions','live_config_activations',
      'live_config_active','live_config_attempt_selections','live_config_attempt_safety'] LOOP
   IF to_regclass('trading.'||relation_name) IS NULL THEN
    RAISE EXCEPTION 'incomplete live config schema';
   END IF;
   EXECUTE format('REVOKE ALL ON trading.%I FROM PUBLIC,qt_algolens_api,qt_system_publisher,qt_worker',relation_name);
   FOR col IN SELECT column_name FROM information_schema.columns
              WHERE table_schema='trading' AND table_name=relation_name LOOP
    EXECUTE format('REVOKE ALL (%I) ON trading.%I FROM PUBLIC,qt_algolens_api,qt_system_publisher,qt_worker',col.column_name,relation_name);
   END LOOP;
  END LOOP;
  GRANT SELECT,INSERT ON trading.live_config_versions,trading.live_config_activations TO qt_algolens_api;
  GRANT SELECT ON trading.live_config_active,trading.live_config_attempt_selections TO qt_algolens_api;
  GRANT SELECT ON trading.live_config_versions,trading.live_config_activations,trading.live_config_active,
    trading.live_config_attempt_selections,trading.live_config_attempt_safety TO qt_system_publisher;
  GRANT INSERT ON trading.live_config_attempt_selections TO qt_system_publisher;
  GRANT INSERT(attempt_id) ON trading.live_config_attempt_safety TO qt_system_publisher;
  GRANT EXECUTE ON FUNCTION trading.lock_live_config_scope(text,text) TO qt_algolens_api,qt_system_publisher;
 END IF;
END
$live_config_roles$;

DO $qt_assert$
BEGIN
  IF (SELECT count(*) FROM pg_roles WHERE rolname IN
      ('qt_schema_owner','qt_migrator','qt_algolens_api','qt_system_publisher','qt_worker')
      AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication
      AND NOT rolbypassrls AND NOT rolinherit
      AND rolcanlogin=(rolname IN ('qt_algolens_api','qt_system_publisher','qt_worker')))<>5 THEN
    RAISE EXCEPTION 'QT role attributes do not match the exact contract';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_auth_members m JOIN pg_roles parent ON parent.oid=m.roleid
    JOIN pg_roles member ON member.oid=m.member
    WHERE member.rolname IN ('qt_algolens_api','qt_system_publisher','qt_worker','qt_schema_owner')
  ) THEN
    RAISE EXCEPTION 'runtime/owner role unexpectedly inherits membership';
  END IF;
  IF (SELECT count(*) FROM pg_auth_members m JOIN pg_roles parent ON parent.oid=m.roleid
      JOIN pg_roles member ON member.oid=m.member
      WHERE member.rolname='qt_migrator' AND parent.rolname='qt_schema_owner'
        AND NOT m.inherit_option AND m.set_option)<>1 THEN
    RAISE EXCEPTION 'migrator membership does not require explicit SET ROLE';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_class c JOIN pg_roles r ON r.oid=c.relowner
     WHERE r.rolname IN ('qt_migrator','qt_algolens_api','qt_system_publisher','qt_worker')
    UNION ALL
    SELECT 1 FROM pg_proc p JOIN pg_roles r ON r.oid=p.proowner
     WHERE r.rolname IN ('qt_migrator','qt_algolens_api','qt_system_publisher','qt_worker')
    UNION ALL
    SELECT 1 FROM pg_namespace n JOIN pg_roles r ON r.oid=n.nspowner
     WHERE r.rolname IN ('qt_migrator','qt_algolens_api','qt_system_publisher','qt_worker')
    UNION ALL
    SELECT 1 FROM pg_database d JOIN pg_roles r ON r.oid=d.datdba
     WHERE r.rolname IN ('qt_migrator','qt_algolens_api','qt_system_publisher','qt_worker')
  ) THEN
    RAISE EXCEPTION 'runtime/migrator role unexpectedly owns a database object';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_namespace n JOIN pg_roles r ON r.oid=n.nspowner
     WHERE n.nspname IN ('auth','trading') AND r.rolname<>'qt_schema_owner'
    UNION ALL
    SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
      JOIN pg_roles r ON r.oid=c.relowner
     WHERE n.nspname IN ('auth','trading') AND c.relkind IN ('r','p','v','m','S','f')
       AND r.rolname<>'qt_schema_owner'
    UNION ALL
    SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
      JOIN pg_roles r ON r.oid=p.proowner
     WHERE n.nspname IN ('auth','trading') AND r.rolname<>'qt_schema_owner'
    UNION ALL
    SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace
      JOIN pg_roles r ON r.oid=t.typowner
     WHERE n.nspname IN ('auth','trading') AND t.typtype IN ('d','e','r')
       AND t.typrelid=0 AND r.rolname<>'qt_schema_owner'
  ) THEN
    RAISE EXCEPTION 'application object ownership is outside qt_schema_owner';
  END IF;
  IF EXISTS (
    SELECT 1 FROM unnest(ARRAY['qt_algolens_api','qt_system_publisher','qt_worker']) role_name
     WHERE has_database_privilege(role_name,current_database(),'CREATE')
        OR has_database_privilege(role_name,current_database(),'TEMP')
        OR has_schema_privilege(role_name,'public','CREATE')
        OR has_schema_privilege(role_name,'auth','CREATE')
        OR has_schema_privilege(role_name,'trading','CREATE')
  ) THEN
    RAISE EXCEPTION 'runtime role retains database/schema creation or temporary privilege';
  END IF;
END
$qt_assert$;

COMMIT;
