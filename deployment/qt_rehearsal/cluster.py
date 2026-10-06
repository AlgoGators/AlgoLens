"""PostgreSQL 16 socket-only cluster orchestration.

All mutating SQL is prefixed by an identity guard in the same psql session.
The only exception is PostgreSQL bootstrap database creation, which uses the
same guard against the cluster's fixed `postgres` maintenance database before
creating the three fixed rehearsal databases.
"""

import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess

from .harness import (
    ADMIN_ROLE,
    DATABASES,
    ManifestError,
    SafetyError,
    build_identity_guard,
    safe_restore_flags,
    validate_database_name,
    validate_rehearsal_root,
    validate_sql_payload,
    verify_manifest_sources,
)


class RehearsalCluster:
    def __init__(self, root, pg_bin):
        self.root = Path(root)
        self.pg_bin = Path(pg_bin)
        self.data_directory = self.root / "data"
        self.socket_directory = self.root / "socket"
        self.log_directory = self.root / "logs"
        self.admin_role = ADMIN_ROLE

    def command_environment(self):
        allowed = ("PATH", "LD_LIBRARY_PATH", "LANG", "LC_ALL", "TZ")
        environment = {key: os.environ[key] for key in allowed if key in os.environ}
        environment.update(
            {
                "PGCONNECT_TIMEOUT": "5",
                "PGSSLMODE": "disable",
                "PGPASSFILE": "/dev/null",
            }
        )
        return environment

    def _tool(self, name):
        path = self.pg_bin / name
        if not path.is_file() or not os.access(path, os.X_OK):
            raise SafetyError(f"required PostgreSQL tool is unavailable: {name}")
        return str(path)

    def _run(self, args, *, input_text=None, check=True, timeout=120):
        try:
            return subprocess.run(
                args,
                input=input_text,
                text=True,
                capture_output=True,
                check=check,
                timeout=timeout,
                env=self.command_environment(),
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise SafetyError(f"rehearsal command failed: {args[0]}: {error}") from error

    def _psql_args(self, database):
        return [
            self._tool("psql"),
            "-X",
            "--no-psqlrc",
            "--no-password",
            "--set=ON_ERROR_STOP=1",
            "--set=VERBOSITY=verbose",
            "--quiet",
            "--tuples-only",
            "--no-align",
            "--host", str(self.socket_directory),
            "--username", self.admin_role,
            "--dbname", database,
        ]

    def _maintenance_guard(self):
        data = str(self.data_directory).replace("'", "''")
        role = self.admin_role.replace("'", "''")
        return f"""
DO $qt_identity$
BEGIN
  IF current_database() IS DISTINCT FROM 'postgres'
     OR inet_server_addr() IS NOT NULL
     OR current_setting('data_directory') IS DISTINCT FROM '{data}'
     OR current_user IS DISTINCT FROM '{role}' THEN
    RAISE EXCEPTION 'qt_rehearsal_identity_mismatch';
  END IF;
END
$qt_identity$;
""".strip()

    def _guard(self, database):
        if database == "postgres":
            return self._maintenance_guard()
        return build_identity_guard(
            database=database,
            data_directory=self.data_directory,
            role=self.admin_role,
        )

    def _psql(self, database, sql, *, check=True):
        return self._run(
            [*self._psql_args(database), "--file=-"],
            input_text=sql,
            check=check,
            timeout=300,
        )

    def initialize(self):
        validate_rehearsal_root(self.root)
        if any(self.root.iterdir()):
            raise SafetyError("rehearsal root must be empty before initialization")
        for name in ("initdb", "postgres", "pg_ctl", "createdb", "psql", "pg_dump", "pg_restore"):
            self._tool(name)
        version = self._run([self._tool("postgres"), "--version"]).stdout.strip()
        if not re.search(r"\b16\.\d+\b", version):
            raise SafetyError("the rehearsal requires PostgreSQL 16")

        self.socket_directory.mkdir(mode=0o700)
        self.log_directory.mkdir(mode=0o700)
        self._run(
            [
                self._tool("initdb"),
                "--pgdata", str(self.data_directory),
                "--username", self.admin_role,
                "--auth-local=trust",
                "--auth-host=reject",
                "--encoding=UTF8",
                "--no-locale",
            ],
            timeout=300,
        )
        configuration = self.data_directory / "postgresql.conf"
        with configuration.open("a", encoding="utf-8") as stream:
            escaped_socket = str(self.socket_directory).replace("'", "''")
            stream.write("\n# QT rehearsal isolation\n")
            stream.write("listen_addresses = ''\n")
            stream.write(f"unix_socket_directories = '{escaped_socket}'\n")
            stream.write("unix_socket_permissions = 0700\n")
            stream.write("ssl = off\n")
            stream.write("password_encryption = 'scram-sha-256'\n")
        hba = (self.data_directory / "pg_hba.conf").read_text(encoding="utf-8")
        if "host    all             all             127.0.0.1/32            reject" not in hba or "::1/128" not in hba:
            raise SafetyError("initdb did not install explicit host rejection")
        self._run(
            [
                self._tool("pg_ctl"),
                "-D", str(self.data_directory),
                "-l", str(self.log_directory / "postgres.log"),
                "-w", "start",
            ],
            timeout=300,
        )
        statements = [self._maintenance_guard()]
        statements.extend(f'CREATE DATABASE "{database}";' for database in DATABASES)
        statements.append(self._maintenance_guard())
        self._psql("postgres", "\n".join(statements))
        if self.database_names() != ["postgres", *sorted(DATABASES)]:
            raise SafetyError("cluster contains an unexpected non-template database")
        for database in DATABASES:
            self.identity(database)

    def identity(self, database):
        validate_database_name(database)
        query = (
            "SELECT current_database(),COALESCE(inet_server_addr()::text,'socket'),"
            "current_setting('data_directory'),current_user;"
        )
        result = self._run([*self._psql_args(database), "--field-separator=|", "--command", query])
        rows = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if len(rows) != 1:
            raise SafetyError("database identity query returned an unexpected shape")
        identity = tuple(rows[0].split("|"))
        expected = (database, "socket", str(self.data_directory), self.admin_role)
        if identity != expected:
            raise SafetyError("database identity does not match the private rehearsal target")
        return identity

    def database_names(self):
        self._psql("postgres", self._maintenance_guard())
        result = self._run(
            [
                *self._psql_args("postgres"),
                "--command",
                "SELECT datname FROM pg_database WHERE NOT datistemplate ORDER BY datname;",
            ]
        )
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def apply_sql(self, database, sql):
        validate_database_name(database)
        validate_rehearsal_root(self.root)
        validate_sql_payload(sql)
        script = f"{self._guard(database)}\n{sql}\n{self._guard(database)}\n"
        self._psql(database, script)

    def query_scalar(self, database, sql):
        validate_database_name(database)
        validate_rehearsal_root(self.root)
        validate_sql_payload(sql)
        if not re.match(r"(?is)^\s*(?:select|with)\b", sql):
            raise SafetyError("read query must begin with SELECT or WITH")
        self.identity(database)
        result = self._run([*self._psql_args(database), "--command", sql])
        rows = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if len(rows) != 1:
            raise SafetyError("scalar query returned an unexpected shape")
        return rows[0]

    def restore_archive(self, database, archive, expected_sha256):
        if database not in ("qt_rehearsal_baseline", "qt_rehearsal_migrated"):
            raise SafetyError("archives may restore only into baseline or migrated rehearsal databases")
        validate_rehearsal_root(self.root)
        archive_path = Path(archive)
        if archive_path.is_symlink() or not archive_path.is_file():
            raise SafetyError("restore archive must be a regular non-symlink file")
        if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256 or ""):
            raise SafetyError("restore archive requires an exact SHA-256")
        actual = hashlib.sha256(archive_path.read_bytes()).hexdigest()
        if actual != expected_sha256:
            raise SafetyError("restore archive SHA-256 mismatch")
        toc = self._run([self._tool("pg_restore"), "--list", str(archive_path)], timeout=300).stdout
        if re.search(r"(?im);\s+\d+\s+\d+\s+DATABASE(?:\s|$)", toc) or "DATABASE PROPERTIES" in toc:
            raise SafetyError("restore archive contains database creation metadata")
        restore = subprocess.Popen(
            [self._tool("pg_restore"), *safe_restore_flags(), str(archive_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self.command_environment(),
        )
        psql = subprocess.Popen(
            [*self._psql_args(database), "--file=-"],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            env=self.command_environment(),
        )
        try:
            assert restore.stdout is not None and psql.stdin is not None
            psql.stdin.write(("BEGIN;\n" + self._guard(database) + "\n").encode("utf-8"))
            while True:
                chunk = restore.stdout.read(1024 * 1024)
                if not chunk:
                    break
                psql.stdin.write(chunk)
            restore_stderr = restore.stderr.read() if restore.stderr is not None else b""
            restore_code = restore.wait(timeout=300)
            if restore_code:
                raise SafetyError("pg_restore could not render the supplied archive: " + restore_stderr.decode("utf-8", "replace")[-1000:])
            psql.stdin.write(("\n" + self._guard(database) + "\nCOMMIT;\n").encode("utf-8"))
            psql.stdin.close()
            psql_stderr = psql.stderr.read() if psql.stderr is not None else b""
            psql_code = psql.wait(timeout=300)
            if psql_code:
                raise SafetyError("identity-guarded restore failed: " + psql_stderr.decode("utf-8", "replace")[-1000:])
        except Exception:
            restore.kill()
            psql.kill()
            restore.wait(timeout=5)
            psql.wait(timeout=5)
            raise
        finally:
            for stream in (restore.stdout, restore.stderr, psql.stdin, psql.stderr):
                if stream is not None and not stream.closed:
                    stream.close()
        self.identity(database)

    def schema_digest(self, database):
        query = r"""
WITH catalog(kind, identity, definition) AS (
  SELECT 'column', table_schema||'.'||table_name||'.'||column_name,
         data_type||'|'||is_nullable||'|'||coalesce(column_default,'')
    FROM information_schema.columns
   WHERE table_schema NOT IN ('pg_catalog','information_schema')
  UNION ALL
  SELECT 'constraint', n.nspname||'.'||c.relname||'.'||x.conname,
         pg_get_constraintdef(x.oid, true)
    FROM pg_constraint x JOIN pg_class c ON c.oid=x.conrelid
    JOIN pg_namespace n ON n.oid=c.relnamespace
   WHERE n.nspname NOT IN ('pg_catalog','information_schema')
  UNION ALL
  SELECT 'function', n.nspname||'.'||p.proname||'('||pg_get_function_identity_arguments(p.oid)||')',
         pg_get_functiondef(p.oid)
    FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
   WHERE n.nspname NOT IN ('pg_catalog','information_schema')
  UNION ALL
  SELECT 'trigger', n.nspname||'.'||c.relname||'.'||t.tgname, pg_get_triggerdef(t.oid, true)
    FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
    JOIN pg_namespace n ON n.oid=c.relnamespace
   WHERE NOT t.tgisinternal AND n.nspname NOT IN ('pg_catalog','information_schema')
)
SELECT kind||'|'||identity||'|'||definition FROM catalog ORDER BY kind,identity,definition;
"""
        validate_database_name(database)
        self.identity(database)
        result = self._run([*self._psql_args(database), "--command", query])
        canonical = "\n".join(line.rstrip() for line in result.stdout.splitlines() if line.strip()) + "\n"
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _predicate_applies(self, database, predicate):
        if predicate["type"] == "always":
            return True
        schema = predicate["schema"].replace("'", "''")
        table = predicate["table"].replace("'", "''")
        if predicate["type"] == "table_absent":
            sql = f"SELECT to_regclass('{schema}.{table}') IS NULL;"
        else:
            column = predicate["column"].replace("'", "''")
            sql = (
                "SELECT NOT EXISTS (SELECT 1 FROM information_schema.columns "
                f"WHERE table_schema='{schema}' AND table_name='{table}' AND column_name='{column}');"
            )
        return self.query_scalar(database, sql) == "t"

    def apply_manifest(self, manifest, repositories):
        if manifest.target_database not in ("qt_rehearsal_migrated", "qt_rehearsal_destructive_tests"):
            raise ManifestError("manifest must target an isolated migration rehearsal database")
        entries = verify_manifest_sources(manifest, repositories)
        results = []
        for entry in entries:
            applies = self._predicate_applies(manifest.target_database, entry.apply_predicate)
            if applies:
                repository = Path(repositories[entry.repository]).resolve(strict=True)
                sql = (repository / entry.path).read_text(encoding="utf-8")
                self.apply_sql(manifest.target_database, sql)
                outcome = "applied"
            else:
                outcome = "skipped"
            digest = self.schema_digest(manifest.target_database)
            if digest != entry.expected_schema_digest:
                raise ManifestError(f"schema digest mismatch after migration {entry.id}")
            results.append({"id": entry.id, "outcome": outcome, "schema_digest": digest})
        return results

    def verify_role_contract(self, contract):
        if contract.database != "qt_rehearsal_migrated":
            raise SafetyError("role probes require the migrated rehearsal database")
        names = {role.domain: role.name for role in contract.roles}
        results = []
        for probe in contract.probes:
            role = names[probe.role_domain]
            script = (
                self._guard(contract.database)
                + "\nBEGIN;\nSET LOCAL ROLE \""
                + role
                + "\";\n"
                + probe.sql
                + ";\nROLLBACK;\n"
            )
            completed = self._psql(contract.database, script, check=False)
            permission_denied = completed.returncode != 0 and "42501" in completed.stderr
            passed = completed.returncode == 0 if probe.expect == "allowed" else permission_denied
            results.append(
                {
                    "probe": probe.id,
                    "role_domain": probe.role_domain,
                    "expect": probe.expect,
                    "outcome": "allowed" if completed.returncode == 0 else "denied" if permission_denied else "error",
                    "passed": passed,
                }
            )
        if not all(result["passed"] for result in results):
            raise SafetyError("one or more role probes did not match the role contract")
        return results

    def root_fingerprint(self):
        path = validate_rehearsal_root(self.root)
        return hashlib.sha256(str(path).encode("utf-8")).hexdigest()

    def _is_running(self):
        if not self.data_directory.exists():
            return False
        result = self._run(
            [self._tool("pg_ctl"), "-D", str(self.data_directory), "status"],
            check=False,
            timeout=30,
        )
        return result.returncode == 0

    def cleanup(self):
        validate_rehearsal_root(self.root)
        if self._is_running():
            count = self.query_scalar(
                "qt_rehearsal_baseline",
                "SELECT count(*) FROM pg_stat_activity WHERE datname IN "
                "('qt_rehearsal_baseline','qt_rehearsal_migrated','qt_rehearsal_destructive_tests') "
                "AND pid<>pg_backend_pid();",
            )
            if count != "0":
                raise SafetyError("rehearsal cleanup refuses while an active session exists")
            self._run(
                [self._tool("pg_ctl"), "-D", str(self.data_directory), "-m", "fast", "-w", "stop"],
                timeout=300,
            )
        validate_rehearsal_root(self.root)
        if self.socket_directory.exists() and list(self.socket_directory.glob(".s.PGSQL.*")):
            raise SafetyError("rehearsal socket remains after PostgreSQL stop")
        shutil.rmtree(self.root)
        if self.root.exists():
            raise SafetyError("rehearsal root still exists after cleanup")
