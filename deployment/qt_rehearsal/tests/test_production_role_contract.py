import subprocess
import json
from pathlib import Path
import signal
import tempfile
import time
import unittest

from deployment.qt_rehearsal.cluster import RehearsalCluster
from deployment.qt_rehearsal.harness import SafetyError, load_role_contract
from deployment.qt_rehearsal.postgres_toolchain import PostgresToolchainError, resolve_postgres_bin


try:
    PG_BIN = resolve_postgres_bin()
except PostgresToolchainError:
    PG_BIN = None


@unittest.skipUnless(PG_BIN is not None, "PostgreSQL 16 toolchain unavailable via QT_REHEARSAL_PG_BIN or PATH")
class ProductionRoleContractTests(unittest.TestCase):
    REPOSITORY = Path(__file__).resolve().parents[3]
    FORWARD = REPOSITORY / "deployment/database/qt_runtime_role_contract.sql"
    ROLLBACK = REPOSITORY / "deployment/database/qt_runtime_role_contract_rollback.sql"
    CONTRACT = REPOSITORY / "deployment/qt_rehearsal/contracts/qt-live-futures-roles.v1.json"

    def setUp(self):
        assert PG_BIN is not None
        self.root = Path(tempfile.mkdtemp(prefix="algolens-qt-rehearsal.", dir="/dev/shm"))
        self.root.chmod(0o700)
        self.cluster = RehearsalCluster(self.root, PG_BIN)
        self.cluster.initialize()

    def tearDown(self):
        if not self.root.exists():
            return
        try:
            self.cluster.cleanup()
        except Exception:
            subprocess.run(
                [str(PG_BIN / "pg_ctl"), "-D", str(self.root / "data"), "-m", "immediate", "stop"],
                check=False,
                capture_output=True,
                text=True,
            )
            if self.root.exists():
                for child in sorted(self.root.rglob("*"), reverse=True):
                    if child.is_file() or child.is_symlink():
                        child.unlink(missing_ok=True)
                    elif child.exists():
                        child.rmdir()
                self.root.rmdir()

    def _apply_fixture(self):
        database = "qt_rehearsal_migrated"
        self.cluster.apply_sql(
            database,
            """
CREATE SCHEMA auth;
CREATE SCHEMA trading;
CREATE SCHEMA futures_data;
CREATE SCHEMA metadata;
CREATE DOMAIN auth.user_label AS text;
CREATE TABLE auth.users(
  id bigint PRIMARY KEY,email text NOT NULL,role text NOT NULL,
  password_hash text,first_name text,last_name text
);
INSERT INTO auth.users(id,email,role) VALUES
 (1,'john.riley@ufl.edu','general_member'),
 (2,'raohemdutt@ufl.edu','exec_board'),
 (3,'robbins.a@ufl.edu','general_member'),
 (4,'dominickdupuy@ufl.edu','general_member'),
 (5,'domdd305@gmail.com','general_member');
CREATE TABLE trading.strategy_registry(
 id text PRIMARY KEY,strategy_type text NOT NULL,portfolio_id text NOT NULL,
 lifecycle text NOT NULL,is_active boolean NOT NULL,runtime_revision bigint NOT NULL DEFAULT 0
);
INSERT INTO trading.strategy_registry VALUES
 ('trendfollowing','LIVE_TREND_FOLLOWING','CONSERVATIVE_PORTFOLIO','live',true,0);
CREATE TABLE trading.strategy_book_memberships(strategy_id text,portfolio_id text);
CREATE TABLE trading.portfolios(portfolio_id text PRIMARY KEY);
CREATE TABLE trading.portfolio_assignments(id bigint PRIMARY KEY);
CREATE TABLE trading.strategy_lifecycle_log(id bigint PRIMARY KEY);
CREATE TABLE trading.positions(
 strategy_id text,portfolio_id text,portfolio_type text NOT NULL,quantity numeric NOT NULL DEFAULT 0
);
CREATE TABLE trading.risk_limits(strategy_id text,portfolio_id text,limits jsonb);
CREATE TABLE trading.live_results(
 strategy_id text,portfolio_id text,portfolio_type text NOT NULL,date timestamptz DEFAULT now()
);
CREATE TABLE trading.equity_curve(
 strategy_id text,portfolio_id text,portfolio_type text NOT NULL
);
CREATE TABLE trading.executions(
 strategy_id text,portfolio_id text,portfolio_type text NOT NULL
);
CREATE TABLE trading.signals(
 strategy_id text,portfolio_id text,portfolio_type text NOT NULL
);
CREATE TABLE trading.live_run_metadata(strategy_id text,portfolio_id text);
CREATE TABLE trading.run_inputs(
 portfolio_id text,strategy_id text,date date,trade_ngin_sha text,
 config_snapshot jsonb,universe jsonb,data_window jsonb,engine_flags jsonb,
 PRIMARY KEY(portfolio_id,strategy_id,date)
);
CREATE TABLE trading.runtime_intents(
 id bigserial PRIMARY KEY,registry_id text,portfolio_id text,engine_strategy_id text,
 action text,registry_revision bigint,config_snapshot jsonb,status text,
 requested_by text,request_reason text,requested_at timestamptz DEFAULT now(),
 approved_by text,approval_reason text,approved_at timestamptz
);
CREATE TABLE trading.runtime_attempts(
 id text PRIMARY KEY,intent_id bigint,registry_revision bigint,config_snapshot jsonb,
 run_date date,producer_version text,status text,started_at timestamptz DEFAULT now(),
 finished_at timestamptz,publication_id text,outcome text,failure_code text
);
CREATE TABLE trading.position_overrides(id bigserial PRIMARY KEY);
CREATE TABLE trading.position_override_legacy_scopes(id bigint PRIMARY KEY);
CREATE TABLE trading.strategy_trading_days_metadata(strategy_id varchar PRIMARY KEY,live_start_date date);
CREATE TABLE futures_data.ohlcv_1d(id bigint PRIMARY KEY);
CREATE TABLE metadata.contract_metadata(id bigint PRIMARY KEY);
""",
        )
        for name in (
            "003_qt_decision_workflow.sql",
            "004_qt_governed_sources.sql",
            "005_qt_evaluator_bundle.sql",
            "007_strategy_registry_asset_class.sql",
            "009_hemdutt_qt_approver.sql",
            "010_qt_submitter_approval_guard.sql",
        ):
            self.cluster.apply_sql(
                database,
                (self.REPOSITORY / "algolens-api/migrations" / name).read_text(encoding="utf-8"),
            )
        self.cluster.apply_sql(
            database,
            """
CREATE TABLE trading.qt_storage_capabilities(id bigint PRIMARY KEY);
CREATE TABLE trading.qt_model_seed_publications(
 publication_id uuid PRIMARY KEY,portfolio_id text,source_day date,strategy_id text
);
CREATE TABLE trading.qt_desk_accounting_inputs(id uuid PRIMARY KEY);
CREATE TABLE trading.qt_desk_finalization_sources(id uuid PRIMARY KEY);
CREATE TABLE trading.desk_run_results(id uuid PRIMARY KEY);
CREATE TABLE trading.qt_desk_market_sources(id uuid PRIMARY KEY);
CREATE TABLE trading.qt_desk_finalizations(id uuid PRIMARY KEY);
CREATE TABLE trading.qt_first_day_anchors(id uuid PRIMARY KEY);
CREATE TABLE trading.qt_desk_dispatch_jobs(decision_id uuid PRIMARY KEY);
CREATE TABLE trading.qt_desk_dispatch_attempts(event_id bigserial PRIMARY KEY);
CREATE FUNCTION trading.enqueue_qt_desk_dispatch(uuid,uuid,uuid,uuid,uuid) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,trading AS $$ BEGIN END $$;
CREATE FUNCTION trading.claim_qt_desk_dispatch(uuid,interval) RETURNS TABLE(decision_id uuid)
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,trading AS $$ BEGIN RETURN; END $$;
CREATE FUNCTION trading.finish_qt_desk_dispatch(uuid,uuid,text,text,text,interval) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,trading AS $$ BEGIN END $$;
CREATE FUNCTION trading.renew_qt_desk_dispatch(uuid,uuid,interval) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,trading AS $$ BEGIN END $$;
CREATE FUNCTION trading.lock_runtime_scope(text,text,boolean DEFAULT false)
 RETURNS TABLE(registry_id text,registry_revision bigint) LANGUAGE plpgsql AS $$
 BEGIN
  RETURN QUERY SELECT r.id,r.runtime_revision FROM trading.strategy_registry r
   WHERE r.strategy_type=$1 AND r.portfolio_id=$2 FOR UPDATE OF r;
 END $$;
CREATE FUNCTION trading.get_trading_days(identity varchar,target_day date) RETURNS integer
 LANGUAGE sql STABLE AS $$
  SELECT greatest(1,target_day-coalesce(
    (SELECT min(l.date)::date FROM trading.live_results l
      JOIN trading.strategy_trading_days_metadata m ON m.strategy_id=identity),target_day)+1)
 $$;
CREATE FUNCTION trading.get_trading_days(identity varchar,target_day date,book varchar) RETURNS integer
 LANGUAGE sql STABLE AS $$
  SELECT greatest(1,target_day-coalesce(
    (SELECT min(l.date)::date FROM trading.live_results l
      JOIN trading.strategy_trading_days_metadata m ON m.strategy_id=identity
     WHERE l.portfolio_id=book),target_day)+1)
 $$;
INSERT INTO trading.positions(strategy_id,portfolio_id,portfolio_type,quantity) VALUES
 ('LIVE_TREND_FOLLOWING','CONSERVATIVE_PORTFOLIO','system',1),
 ('LIVE_TREND_FOLLOWING','CONSERVATIVE_PORTFOLIO','qt',1);
INSERT INTO trading.strategy_trading_days_metadata VALUES('LIVE_TREND_FOLLOWING',date '2026-01-01');
""",
        )

    def _seed_lock_rows(self):
        self.cluster.apply_sql(
            "qt_rehearsal_migrated",
            """
INSERT INTO trading.qt_drafts(
 draft_id,book_id,source_day,revision,source_digest,provenance_digest,draft_digest,
 selection_payload,created_by,updated_by
) VALUES(
 '10000000-0000-4000-8000-000000000001','CONSERVATIVE_PORTFOLIO',date '2026-10-06',1,
 'source','provenance','draft','{}',1,1
);
INSERT INTO trading.qt_draft_heads(book_id,source_day,draft_id,revision) VALUES(
 'CONSERVATIVE_PORTFOLIO',date '2026-10-06','10000000-0000-4000-8000-000000000001',1
);
INSERT INTO trading.qt_previews(
 preview_id,book_id,source_day,draft_id,draft_revision,draft_digest,source_digest,
 provenance_digest,read_set_digest,optimizer_book_digest,selected_book_digest,
 payload_digest,payload,read_set_payload,evaluator_build,policy_version,
 availability,created_by,state
) VALUES(
 '20000000-0000-4000-8000-000000000001','CONSERVATIVE_PORTFOLIO',date '2026-10-06',
 '10000000-0000-4000-8000-000000000001',1,'draft','source','provenance','read-set',
 'optimizer','selected','payload','{}','{}','build','policy','ready',1,'pending_override'
);
INSERT INTO trading.qt_decisions(
 decision_id,preview_id,book_id,source_day,status,provenance_digest,draft_id,draft_revision,
 selected_book_digest,read_set_digest,workflow_capability_version,submitter_grant_version,
 policy_version,payload,created_by
) VALUES(
 '30000000-0000-4000-8000-000000000001','20000000-0000-4000-8000-000000000001',
 'CONSERVATIVE_PORTFOLIO',date '2026-10-06','pending_override','provenance',
 '10000000-0000-4000-8000-000000000001',1,'selected','read-set',1,1,'policy','{}',1
);
INSERT INTO trading.qt_override_requests(request_id,decision_id,eligibility_version,required_approvals)
 VALUES('40000000-0000-4000-8000-000000000001','30000000-0000-4000-8000-000000000001',1,2);
INSERT INTO trading.qt_approver_allowlist(person_id,display_label,user_id,active,mapping_version)
 VALUES('self_submitter','self submitter',1,false,1);
INSERT INTO trading.qt_override_approvals(
 approval_id,request_id,person_id,user_id,mapping_version,grant_version
) VALUES(
 '50000000-0000-4000-8000-000000000002','40000000-0000-4000-8000-000000000001',
 'hemdutt_rao',2,1,1
);
INSERT INTO trading.qt_desk_receipts(
 decision_id,attempt_id,status,report_eligibility_status,report_reason_codes
) VALUES(
 '30000000-0000-4000-8000-000000000001','60000000-0000-4000-8000-000000000001',
 'pending','unavailable','[]'
);
INSERT INTO trading.runtime_intents(
 registry_id,portfolio_id,engine_strategy_id,action,registry_revision,config_snapshot,
 status,requested_by,request_reason
) VALUES(
 'trendfollowing','CONSERVATIVE_PORTFOLIO','LIVE_TREND_FOLLOWING','run',0,'{}',
 'pending','probe','probe'
);
INSERT INTO trading.run_inputs(
 portfolio_id,strategy_id,date,trade_ngin_sha,config_snapshot,universe,data_window,engine_flags
) VALUES(
 'CONSERVATIVE_PORTFOLIO','LIVE_TREND_FOLLOWING',date '2026-10-06','probe','{}','[]','{}','{}'
);
""",
        )

    def _as_role(self, role, sql):
        database = "qt_rehearsal_migrated"
        script = (
            self.cluster._guard(database)
            + "\nBEGIN;\nSET LOCAL ROLE \""
            + role
            + "\";\n"
            + sql
            + ";\nROLLBACK;\n"
        )
        return self.cluster._psql(database, script, check=False)

    def test_postlude_is_idempotent_and_enforces_runtime_isolation(self):
        """Catches broad grants, unguarded locks, unsafe definers, and cross-stream writes."""
        for path in (self.FORWARD, self.ROLLBACK, self.CONTRACT):
            self.assertTrue(path.is_file(), f"missing production role-contract artifact: {path.name}")
        self._apply_fixture()
        database = "qt_rehearsal_migrated"
        forward = self.FORWARD.read_text(encoding="utf-8")
        self.cluster.apply_sql(database, forward)
        first_digest = self.cluster.role_policy_digest(database)
        self.cluster.apply_sql(database, forward)
        self.assertEqual(self.cluster.role_policy_digest(database), first_digest)

        exact_roles = self.cluster.query_scalar(
            database,
            "SELECT count(*) FROM pg_roles WHERE rolname IN "
            "('qt_schema_owner','qt_migrator','qt_algolens_api','qt_system_publisher','qt_worker') "
            "AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication "
            "AND NOT rolbypassrls AND NOT rolinherit AND "
            "rolcanlogin=(rolname IN ('qt_algolens_api','qt_system_publisher','qt_worker'));",
        )
        self.assertEqual(exact_roles, "5")
        self.assertEqual(
            self.cluster.query_scalar(
                database,
                "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "JOIN pg_roles r ON r.oid=c.relowner WHERE n.nspname IN ('auth','trading') "
                "AND c.relkind IN ('r','p','v','m','S','f') AND r.rolname<>'qt_schema_owner';",
            ),
            "0",
        )
        self.assertEqual(
            self.cluster.query_scalar(
                database,
                "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='trading' AND c.relname IN "
                "('positions','live_results','equity_curve','executions','signals') AND c.relrowsecurity;",
            ),
            "5",
        )

        results = self.cluster.verify_role_contract(load_role_contract(self.CONTRACT))
        self.assertTrue(all(result["passed"] for result in results), json.dumps(results, sort_keys=True))
        self.assertTrue(
            all("role_policy_digest" in result for result in results),
            "role verification results must carry the canonical role/policy attestation",
        )
        self.assertEqual(len({result["role_policy_digest"] for result in results}), 1)
        self.assertRegex(results[0]["role_policy_digest"], r"^[0-9a-f]{64}$")

        self.assertEqual(
            self._as_role(
                "qt_algolens_api",
                "SELECT id FROM trading.strategy_registry WHERE id='trendfollowing' FOR UPDATE",
            ).returncode,
            0,
        )
        denied = self._as_role(
            "qt_algolens_api",
            "UPDATE trading.strategy_registry SET id=id WHERE id='trendfollowing'",
        )
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn("42501", denied.stderr)
        for role, stream in (("qt_system_publisher", "qt"), ("qt_worker", "system")):
            denied = self._as_role(
                role,
                "INSERT INTO trading.positions(strategy_id,portfolio_id,portfolio_type,quantity) "
                f"VALUES('LIVE_TREND_FOLLOWING','CONSERVATIVE_PORTFOLIO','{stream}',1)",
            )
            self.assertNotEqual(denied.returncode, 0)
            self.assertIn("42501", denied.stderr)
        for role, stream in (
            ("qt_system_publisher", "system"),
            ("qt_system_publisher", "qt_proposal"),
            ("qt_worker", "qt"),
        ):
            allowed = self._as_role(
                role,
                "INSERT INTO trading.positions(strategy_id,portfolio_id,portfolio_type,quantity) "
                f"VALUES('LIVE_TREND_FOLLOWING','CONSERVATIVE_PORTFOLIO','{stream}',1)",
            )
            self.assertEqual(allowed.returncode, 0, allowed.stderr)

        self.assertEqual(
            self._as_role(
                "qt_system_publisher",
                "SELECT trading.get_trading_days('LIVE_TREND_FOLLOWING'::varchar,date '2026-10-06')",
            ).returncode,
            0,
        )
        self.assertIn(
            "42501",
            self._as_role(
                "qt_system_publisher",
                "SELECT trading.get_trading_days('LIVE_TREND_FOLLOWING'::varchar,date '2026-10-06','CONSERVATIVE_PORTFOLIO'::varchar)",
            ).stderr,
        )

    def test_guarded_rollback_disables_access_without_dropping_data(self):
        """Catches rollback that drops data, leaves login enabled, or cannot be reapplied."""
        for path in (self.FORWARD, self.ROLLBACK):
            self.assertTrue(path.is_file(), f"missing production role-contract artifact: {path.name}")
        self._apply_fixture()
        database = "qt_rehearsal_migrated"
        forward = self.FORWARD.read_text(encoding="utf-8")
        self.cluster.apply_sql(database, forward)
        row_count = self.cluster.query_scalar(database, "SELECT count(*) FROM trading.positions;")
        sleeper = subprocess.Popen(
            [
                str(PG_BIN / "psql"), "-X", "--no-psqlrc", "--no-password",
                "--host", str(self.root / "socket"), "--username", "qt_worker",
                "--dbname", database, "--command", "SELECT pg_sleep(30)",
            ],
            env=self.cluster.command_environment(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if self.cluster.query_scalar(
                    database,
                    "SELECT count(*) FROM pg_stat_activity WHERE usename='qt_worker' "
                    "AND pid<>pg_backend_pid();",
                ) == "1":
                    break
                time.sleep(0.05)
            else:
                self.fail("runtime session did not become visible to rollback guard")
            with self.assertRaises(SafetyError):
                self.cluster.apply_sql(database, self.ROLLBACK.read_text(encoding="utf-8"))
        finally:
            sleeper.send_signal(signal.SIGINT)
            sleeper.wait(timeout=5)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if self.cluster.query_scalar(
                database,
                "SELECT count(*) FROM pg_stat_activity WHERE usename='qt_worker' "
                "AND pid<>pg_backend_pid();",
            ) == "0":
                break
            time.sleep(0.05)
        else:
            self.fail("runtime session remained visible after local test client exit")
        self.cluster.apply_sql(database, self.ROLLBACK.read_text(encoding="utf-8"))
        self.assertEqual(self.cluster.query_scalar(database, "SELECT count(*) FROM trading.positions;"), row_count)
        self.assertEqual(
            self.cluster.query_scalar(
                database,
                "SELECT count(*) FROM pg_roles WHERE rolname IN "
                "('qt_algolens_api','qt_system_publisher','qt_worker') AND rolcanlogin;",
            ),
            "0",
        )
        self.assertEqual(
            self.cluster.query_scalar(
                database,
                "SELECT count(*) FROM pg_policy WHERE polname LIKE 'qt_role_%';",
            ),
            "0",
        )
        self.cluster.apply_sql(database, forward)
        self.assertEqual(
            self.cluster.query_scalar(
                database,
                "SELECT count(*) FROM pg_roles WHERE rolname IN "
                "('qt_algolens_api','qt_system_publisher','qt_worker') AND rolcanlogin;",
            ),
            "3",
        )

    def test_every_lock_only_surface_locks_but_rejects_mutation_with_42501(self):
        """Catches a late/missing guard or a lock column that PostgreSQL cannot use."""
        self.assertTrue(self.FORWARD.is_file())
        self._apply_fixture()
        database = "qt_rehearsal_migrated"
        self.cluster.apply_sql(database, self.FORWARD.read_text(encoding="utf-8"))
        self._seed_lock_rows()
        probes = (
            ("qt_algolens_api", "auth.users", "id", "id=1"),
            ("qt_worker", "auth.users", "id", "id=1"),
            ("qt_algolens_api", "trading.strategy_registry", "id", "id='trendfollowing'"),
            ("qt_worker", "trading.strategy_registry", "id", "id='trendfollowing'"),
            ("qt_algolens_api", "trading.qt_action_grants", "user_id", "user_id=1 AND capability='qt_submit'"),
            ("qt_worker", "trading.qt_action_grants", "user_id", "user_id=1 AND capability='qt_submit'"),
            ("qt_algolens_api", "trading.qt_approver_allowlist", "person_id", "person_id='hemdutt_rao'"),
            ("qt_worker", "trading.qt_approver_allowlist", "person_id", "person_id='hemdutt_rao'"),
            ("qt_algolens_api", "trading.qt_draft_heads", "book_id", "book_id='CONSERVATIVE_PORTFOLIO'"),
            ("qt_worker", "trading.qt_draft_heads", "book_id", "book_id='CONSERVATIVE_PORTFOLIO'"),
            ("qt_algolens_api", "trading.qt_previews", "preview_id", "preview_id='20000000-0000-4000-8000-000000000001'"),
            ("qt_worker", "trading.qt_previews", "preview_id", "preview_id='20000000-0000-4000-8000-000000000001'"),
            ("qt_algolens_api", "trading.qt_decisions", "decision_id", "decision_id='30000000-0000-4000-8000-000000000001'"),
            ("qt_worker", "trading.qt_decisions", "decision_id", "decision_id='30000000-0000-4000-8000-000000000001'"),
            ("qt_algolens_api", "trading.qt_override_requests", "request_id", "request_id='40000000-0000-4000-8000-000000000001'"),
            ("qt_worker", "trading.qt_override_requests", "request_id", "request_id='40000000-0000-4000-8000-000000000001'"),
            ("qt_algolens_api", "trading.qt_override_approvals", "approval_id", "approval_id='50000000-0000-4000-8000-000000000002'"),
            ("qt_worker", "trading.qt_override_approvals", "approval_id", "approval_id='50000000-0000-4000-8000-000000000002'"),
            ("qt_algolens_api", "trading.qt_desk_receipts", "decision_id", "decision_id='30000000-0000-4000-8000-000000000001'"),
            ("qt_worker", "trading.qt_desk_receipts", "decision_id", "decision_id='30000000-0000-4000-8000-000000000001'"),
            ("qt_system_publisher", "trading.runtime_intents", "id", "id=1"),
            ("qt_system_publisher", "trading.run_inputs", "portfolio_id", "portfolio_id='CONSERVATIVE_PORTFOLIO'"),
        )
        for role, table, key, predicate in probes:
            with self.subTest(role=role, table=table):
                locked = self._as_role(role, f"SELECT {key} FROM {table} WHERE {predicate} FOR UPDATE")
                self.assertEqual(locked.returncode, 0, locked.stderr)
                denied = self._as_role(role, f"UPDATE {table} SET {key}={key} WHERE {predicate}")
                self.assertNotEqual(denied.returncode, 0)
                self.assertIn("42501", denied.stderr)

    def test_final_api_role_preserves_retirement_and_self_approval_guards(self):
        """Catches a role ACL that bypasses identity retirement or same-submitter rejection."""
        self.assertTrue(self.FORWARD.is_file())
        self._apply_fixture()
        database = "qt_rehearsal_migrated"
        self.cluster.apply_sql(database, self.FORWARD.read_text(encoding="utf-8"))
        self._seed_lock_rows()
        self_approval = self._as_role(
            "qt_algolens_api",
            "INSERT INTO trading.qt_override_approvals(approval_id,request_id,person_id,user_id,mapping_version,grant_version) "
            "VALUES('50000000-0000-4000-8000-000000000001','40000000-0000-4000-8000-000000000001',"
            "'self_submitter',1,1,1)",
        )
        self.assertNotEqual(self_approval.returncode, 0)
        self.assertIn("42501", self_approval.stderr)

        retired_regrant = self.cluster._psql(
            database,
            self.cluster._guard(database)
            + "\nINSERT INTO trading.qt_action_grants(user_id,capability,active,version) "
            "VALUES(5,'qt_approve',true,1);",
            check=False,
        )
        self.assertNotEqual(retired_regrant.returncode, 0)
        active_retirement = self.cluster._psql(
            database,
            self.cluster._guard(database)
            + "\nINSERT INTO auth.account_retirements(user_id,replacement_user_id,reason,retired_by_migration) "
            "VALUES(1,2,'probe','probe');",
            check=False,
        )
        self.assertNotEqual(active_retirement.returncode, 0)
        immutable_retirement = self.cluster._psql(
            database,
            self.cluster._guard(database)
            + "\nUPDATE auth.account_retirements SET reason='probe' WHERE user_id=5;",
            check=False,
        )
        self.assertNotEqual(immutable_retirement.returncode, 0)


if __name__ == "__main__":
    unittest.main()
