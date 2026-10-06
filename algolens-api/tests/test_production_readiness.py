import json
from hashlib import sha256
import os
from pathlib import Path
import subprocess
import sys

import pytest

from algolens.infrastructure.config.production_readiness import (
    ProductionConfigurationError,
    ReadinessSnapshotCache,
    capability_contract_digest,
    canonical_json,
    evaluator_isolation_probe,
    evaluate_readiness,
    evaluate_runtime_readiness,
    load_runtime_contract,
    role_contract_probe,
    schema_contract_probe,
    worker_contract_digest,
)


FIXTURES = Path(__file__).with_name("fixtures") / "production_readiness"
RELEASE_FIXTURE = FIXTURES / "release-artifacts.v1.placeholder.json"
DATABASE_FIXTURE = FIXTURES / "database-identity.v1.placeholder.json"


def handshake_response(evaluator_build):
    return {
        "schema": "qt-eval/v1",
        "operation": "selected_book",
        "evaluator_build": evaluator_build,
        "context_fingerprint": "1" * 64,
        "completeness": "complete",
        "evaluated_book": [{"quantity_exact": "5"}, {"quantity_exact": "1"}],
        "selected_risk": {"status": "evaluated", "passed": True},
        "selected_costs": {"status": "evaluated", "total_exact": "0.02"},
    }


def production_environment(**changes):
    environment = {
        "FLASK_ENV": "production",
        "FLASK_DEBUG": "false",
        "DEV_MODE": "0",
        "APP_RELEASE_SHA": "a" * 40,
        "QT_EMAIL_DELIVERY_ENABLED": "false",
        "DB_NAME": "new_algo_data",
        "DB_USER": "algolens_api_runtime",
        "QT_EVALUATOR_BUNDLE_DIR": "/app/qt-evaluator-bundle",
        "QT_RUNTIME_CONFIG_MANIFEST": "/app/runtime-control/manifest.json",
        "QT_RUNTIME_CONFIG_SHA256": "0" * 64,
        "QT_RELEASE_ARTIFACT_MANIFEST": str(RELEASE_FIXTURE),
        "QT_DATABASE_IDENTITY_MANIFEST": str(DATABASE_FIXTURE),
    }
    environment.update(changes)
    return environment


def resolved_manifests(tmp_path):
    artifact = {
        "schema": "release-artifacts/v1",
        "source": {
            "git_sha_full": "b" * 40,
            "git_sha_short": "b" * 12,
            "dirty": False,
        },
        "build": {
            "build_type": "Release",
            "compiler": {"id": "GNU", "version": "14.2.0"},
            "cxx_standard": "20",
            "toolchain_image_digest": "sha256:" + "c" * 64,
            "cmake_inputs": ["CMAKE_BUILD_TYPE=Release"],
        },
        "image": {"digest": "sha256:" + "4" * 64},
        "evaluator": {
            "evaluator_build": "b" * 12,
            "evaluator_sha256": "d" * 64,
            "evaluator_bundle_sha256": "e" * 64,
            "bundle_manifest_sha256": "f" * 64,
            "install_path": "qt-evaluator-bundle",
        },
        "artifacts": [],
        "integration": {"pending_artifacts": []},
    }
    kinds = {
        "libtrade_ngin.so": "engine",
        "live_equity_mean_reversion": "system_publisher",
        "live_portfolio": "system_publisher",
        "live_portfolio_conservative": "system_publisher",
        "qt_desk_prepare_sources": "desk_tool",
        "qt_desk_run": "desk_tool",
        "qt_desk_worker": "desk_worker",
        "qt_evaluator": "evaluator",
    }
    artifact["artifacts"] = [
        {
            "name": name,
            "kind": kind,
            "install_path": f"bin/Release/{name}",
            "size": 100 + slot,
            "sha256": ("d" * 64 if name == "qt_evaluator" else f"{slot:x}" * 64),
        }
        for slot, (name, kind) in enumerate(sorted(kinds.items()), start=1)
    ]
    artifact["manifest_sha256"] = sha256(canonical_json(artifact)).hexdigest()
    books = [{
        "registry_id": "trendfollowing",
        "strategy_id": "LIVE_TREND_FOLLOWING",
        "book_id": "CONSERVATIVE_PORTFOLIO",
        "lifecycle": "live",
            "evaluator_build": artifact["evaluator"]["evaluator_build"],
        "evaluator_sha256": artifact["evaluator"]["evaluator_sha256"],
        "evaluator_bundle_sha256": artifact["evaluator"]["evaluator_bundle_sha256"],
    }]
    database = {
        "schema": "algolens-database-identity/v1",
        "state": "resolved",
        "database": {
            "name": "new_algo_data",
            "server_addr": "192.0.2.10",
            "data_directory": "/approved/postgres/data",
            "role": "algolens_api_runtime",
            "role_contract_sha256": "9" * 64,
            "schema_sha256": "1" * 64,
        },
        "live_books": books,
        "dependencies": {
            "capability": {"schema": "qt-capabilities/v1", "state": "resolved", "sha256": "2" * 64},
            "worker": {"schema": "qt-worker-service/v1", "state": "resolved", "sha256": "3" * 64},
        },
    }
    artifact_path = tmp_path / "release.json"
    database_path = tmp_path / "database.json"
    artifact_path.write_text(json.dumps(artifact))
    database_path.write_text(json.dumps(database))
    return artifact_path, database_path, artifact, database


def test_checked_in_dependency_fixtures_are_versioned_but_never_ready():
    contract = load_runtime_contract(production_environment())
    assert contract.artifact_manifest["schema"] == "release-artifacts/v1"
    assert contract.database_manifest["schema"] == "algolens-database-identity/v1"
    result = evaluate_readiness(contract)
    assert result.ready is False
    assert result.public_payload() == {
        "status": "not_ready",
        "checks": {
            "artifacts": "error",
            "capability": "error",
            "configuration": "ok",
            "database": "error",
                "evaluator": "error",
                "role": "error",
                "runtime_config": "error",
                "schema": "error",
            "worker": "error",
        },
    }
    assert set(result.failure_codes) == {
        "artifact_contract_unresolved",
        "database_contract_unresolved",
        "capability_contract_unresolved",
        "worker_contract_unresolved",
    }


def test_readiness_snapshot_cache_is_single_source_and_bounded_by_ttl():
    now = [100.0]
    calls = []
    cache = ReadinessSnapshotCache(ttl_seconds=15.0, clock=lambda: now[0])

    def probe():
        calls.append(len(calls) + 1)
        return calls[-1]

    assert cache.get(probe) == 1
    assert cache.get(probe) == 1
    assert calls == [1]
    now[0] += 15.0
    assert cache.get(probe) == 2


@pytest.mark.parametrize(
    "damage,expected_code",
    [
        ("book_shape", "database_contract_invalid"),
        ("book_scope", "database_contract_invalid"),
        ("capability_schema", "capability_contract_invalid"),
        ("worker_schema", "worker_contract_invalid"),
        ("pending_worker", "artifact_contract_unresolved"),
    ],
)
def test_malformed_resolved_contract_is_a_fixed_not_ready_result(tmp_path, damage, expected_code):
    artifact_path, database_path, _artifact, database = resolved_manifests(tmp_path)
    if damage == "book_shape":
        database["live_books"] = ["not-a-book"]
    elif damage == "book_scope":
        database["live_books"][0]["book_id"] = "UNAPPROVED_BOOK"
    elif damage == "capability_schema":
        database["dependencies"]["capability"]["schema"] = "wrong/v1"
    elif damage == "worker_schema":
        database["dependencies"]["worker"]["schema"] = "wrong/v1"
    else:
        artifact = json.loads(artifact_path.read_text())
        artifact["integration"]["pending_artifacts"] = ["qt_desk_worker"]
        artifact["manifest_sha256"] = sha256(canonical_json(
            {key: value for key, value in artifact.items() if key != "manifest_sha256"}
        )).hexdigest()
        artifact_path.write_text(json.dumps(artifact))
    database_path.write_text(json.dumps(database))
    contract = load_runtime_contract(production_environment(
        QT_RELEASE_ARTIFACT_MANIFEST=str(artifact_path),
        QT_DATABASE_IDENTITY_MANIFEST=str(database_path),
    ))

    result = evaluate_readiness(contract)

    assert result.ready is False
    assert expected_code in result.failure_codes
    assert result.public_payload()["status"] == "not_ready"


@pytest.mark.parametrize(
    "name,value",
    [
        ("FLASK_ENV", "development"),
        ("FLASK_DEBUG", "true"),
        ("DEV_MODE", "1"),
        ("APP_RELEASE_SHA", "main"),
        ("QT_EMAIL_DELIVERY_ENABLED", "true"),
        ("DB_NAME", "qt_rehearsal_migrated"),
        ("QT_EVALUATOR_BUNDLE_DIR", "relative/bundle"),
        ("QT_RUNTIME_CONFIG_MANIFEST", "relative/runtime.json"),
        ("QT_RUNTIME_CONFIG_SHA256", "not-a-digest"),
    ],
)
def test_production_configuration_refuses_unsafe_values(name, value):
    with pytest.raises(ProductionConfigurationError, match="production_configuration_invalid"):
        load_runtime_contract(production_environment(**{name: value}))


def test_readiness_proves_exact_read_only_identity_and_dependency_pins(tmp_path):
    artifact_path, database_path, artifact, database = resolved_manifests(tmp_path)
    database["live_books"][0]["unexpected"] = "private-book-extension"
    database["dependencies"]["capability"]["unexpected"] = "private-dependency-extension"
    database_path.write_text(json.dumps(database))
    contract = load_runtime_contract(production_environment(
        QT_RELEASE_ARTIFACT_MANIFEST=str(artifact_path),
        QT_DATABASE_IDENTITY_MANIFEST=str(database_path),
    ))

    class Cursor:
        def __init__(self):
            self.query = None

        def execute(self, query, params=None):
            self.query = " ".join(query.split())

        def fetchone(self):
            if "worker_schema_ready" in self.query:
                return {"worker_schema_ready": True, "active_workers": 1, "queue_healthy": True}
            if "current_database()" in self.query:
                return {
                    "database_name": "new_algo_data",
                    "server_addr": "192.0.2.10",
                    "data_directory": "/approved/postgres/data",
                    "database_role": "algolens_api_runtime",
                }
            if "FROM pg_roles" in self.query:
                return {
                    "rolsuper": False,
                    "rolcreaterole": False,
                    "rolcreatedb": False,
                    "rolreplication": False,
                    "rolbypassrls": False,
                }
            raise AssertionError(self.query)

        def fetchall(self):
            if "strategy_registry" in self.query:
                return [{key: book[key] for key in
                         ("registry_id", "strategy_id", "book_id", "lifecycle")}
                        for book in database["live_books"]]
            assert "qt_source_policies" in self.query
            return [{key: book[key] for key in
                     ("book_id", "evaluator_build", "evaluator_sha256", "evaluator_bundle_sha256")}
                    for book in database["live_books"]]

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class Connection:
        def __init__(self):
            self.readonly = None
            self.closed = False

        def set_session(self, *, readonly, autocommit):
            self.readonly = (readonly, autocommit)

        def cursor(self):
            return Cursor()

        def rollback(self):
            pass

        def close(self):
            self.closed = True

    connection = Connection()
    response = handshake_response(artifact["evaluator"]["evaluator_build"])
    artifact_path.write_text(json.dumps(artifact))
    contract = load_runtime_contract(production_environment(
        QT_RELEASE_ARTIFACT_MANIFEST=str(artifact_path),
        QT_DATABASE_IDENTITY_MANIFEST=str(database_path),
    ))

    result = evaluate_readiness(
        contract,
        connection_factory=lambda: connection,
        schema_probe=lambda _cursor: "1" * 64,
        role_probe=lambda _cursor: "9" * 64,
        runtime_configuration_probe=lambda _contract: "0" * 64,
        evaluator_probe=lambda _contract: response,
        capability_probe=lambda _cursor, expected: expected["state"] == "resolved",
        worker_probe=lambda _cursor, expected: expected["state"] == "resolved",
    )

    assert result.ready is True, result.failure_codes
    assert connection.readonly == (True, False)
    assert connection.closed is True
    assert result.public_payload()["status"] == "ready"
    evidence = result.evidence_payload()
    assert evidence["schema"] == "algolens-readiness-evidence/v1"
    assert evidence["database"]["name"] == "new_algo_data"
    assert evidence["database"]["role"] == "algolens_api_runtime"
    assert evidence["artifact"]["evaluator_bundle_sha256"] == "e" * 64
    assert evidence["database"]["role_contract_sha256"] == "9" * 64
    assert evidence["runtime_config_sha256"] == "0" * 64
    assert "data_directory" not in json.dumps(evidence)
    assert "private-" not in json.dumps(evidence)


def test_manifest_parser_rejects_duplicate_keys(tmp_path):
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(
        '{"schema":"release-artifacts/v1","schema":"release-artifacts/v1",'
        '"state":"dependency-placeholder"}'
    )
    with pytest.raises(ProductionConfigurationError, match="production_configuration_invalid"):
        load_runtime_contract(production_environment(QT_RELEASE_ARTIFACT_MANIFEST=str(duplicate)))


def test_unavailable_database_never_reports_schema_as_verified(tmp_path):
    artifact_path, database_path, _artifact, _database = resolved_manifests(tmp_path)
    contract = load_runtime_contract(production_environment(
        QT_RELEASE_ARTIFACT_MANIFEST=str(artifact_path),
        QT_DATABASE_IDENTITY_MANIFEST=str(database_path),
    ))

    result = evaluate_readiness(contract)

    assert result.ready is False
    assert result.public_payload()["checks"]["database"] == "error"
    assert result.public_payload()["checks"]["schema"] == "error"


@pytest.mark.parametrize(
    "damage,expected_code",
    [
        ("database", "database_identity_mismatch"),
        ("superuser", "database_role_is_superuser"),
        ("schema", "schema_digest_mismatch"),
        ("books", "live_book_contract_mismatch"),
        ("registry_extra", "live_book_contract_mismatch"),
        ("evaluator", "evaluator_handshake_mismatch"),
        ("capability", "capability_dependency_unready"),
        ("worker", "worker_dependency_unready"),
        ("role_flags", "database_role_is_privileged"),
        ("role_contract", "role_contract_mismatch"),
        ("runtime_config", "runtime_configuration_mismatch"),
        ("close", "database_check_failed"),
    ],
)
def test_readiness_refuses_each_identity_boundary(tmp_path, damage, expected_code):
    artifact_path, database_path, artifact, database = resolved_manifests(tmp_path)
    response = handshake_response(artifact["evaluator"]["evaluator_build"])
    artifact_path.write_text(json.dumps(artifact))
    contract = load_runtime_contract(production_environment(
        QT_RELEASE_ARTIFACT_MANIFEST=str(artifact_path),
        QT_DATABASE_IDENTITY_MANIFEST=str(database_path),
    ))

    identity = {
        "database_name": "wrong" if damage == "database" else "new_algo_data",
        "server_addr": "192.0.2.10",
        "data_directory": "/approved/postgres/data",
        "database_role": "algolens_api_runtime",
    }

    class Cursor:
        query = ""
        def execute(self, query, params=None): self.query = query
        def fetchone(self):
            if "pg_roles" in self.query:
                return {
                    "rolsuper": damage == "superuser",
                    "rolcreaterole": damage == "role_flags",
                    "rolcreatedb": False,
                    "rolreplication": False,
                    "rolbypassrls": False,
                }
            return identity
        def fetchall(self):
            books = [] if damage == "books" else database["live_books"]
            if "strategy_registry" in self.query:
                rows = [{key: book[key] for key in
                         ("registry_id", "strategy_id", "book_id", "lifecycle")}
                        for book in books]
                if damage == "registry_extra":
                    rows.append({"registry_id": "hidden", "strategy_id": "LIVE_HIDDEN",
                                 "book_id": "HIDDEN_BOOK", "lifecycle": "live"})
                return rows
            return [{key: book[key] for key in
                     ("book_id", "evaluator_build", "evaluator_sha256", "evaluator_bundle_sha256")}
                    for book in books]
        def __enter__(self): return self
        def __exit__(self, *args): return False
    class Connection:
        def set_session(self, **kwargs): pass
        def cursor(self): return Cursor()
        def rollback(self): pass
        def close(self):
            if damage == "close":
                raise RuntimeError("close failed")

    result = evaluate_readiness(
        contract,
        connection_factory=Connection,
        schema_probe=lambda _cursor: "9" * 64 if damage == "schema" else "1" * 64,
        role_probe=lambda _cursor: "0" * 64 if damage == "role_contract" else "9" * 64,
        runtime_configuration_probe=lambda _contract: (
            "f" * 64 if damage == "runtime_config" else "0" * 64
        ),
        evaluator_probe=lambda _contract: {"wrong": True} if damage == "evaluator" else response,
        capability_probe=lambda _cursor, _expected: damage != "capability",
        worker_probe=lambda _cursor, _expected: damage != "worker",
    )
    assert result.ready is False
    assert expected_code in result.failure_codes
    assert expected_code not in json.dumps(result.public_payload())


def test_evaluator_probe_uses_only_the_pinned_bundle_and_deterministic_request(tmp_path):
    artifact_path, database_path, artifact, _database = resolved_manifests(tmp_path)
    artifact_path.write_text(json.dumps(artifact))
    contract = load_runtime_contract(production_environment(
        QT_RELEASE_ARTIFACT_MANIFEST=str(artifact_path),
        QT_DATABASE_IDENTITY_MANIFEST=str(database_path),
    ))
    observed = {}

    class Process:
        def __init__(self, executable, expected_sha256, expected_build, *, bundle_directory, expected_bundle_sha256):
            observed["configuration"] = {
                "executable": executable,
                "expected_sha256": expected_sha256,
                "expected_build": expected_build,
                "bundle_directory": bundle_directory,
                "expected_bundle_sha256": expected_bundle_sha256,
            }

        def run(self, request):
            observed["request"] = request
            return handshake_response(artifact["evaluator"]["evaluator_build"])

    response = evaluator_isolation_probe(contract, process_factory=Process)
    assert observed == {
        "configuration": {
            "executable": Path("/app/qt-evaluator-bundle/bin/qt_evaluator"),
            "expected_sha256": "d" * 64,
            "expected_build": "b" * 12,
            "bundle_directory": Path("/app/qt-evaluator-bundle"),
            "expected_bundle_sha256": "e" * 64,
        },
        "request": observed["request"],
    }
    assert observed["request"]["schema"] == "qt-eval/v1"
    assert observed["request"]["operation"] == "selected_book"
    assert observed["request"]["evaluator_build"] == "b" * 12
    assert observed["request"]["context_fingerprint"] == "1" * 64
    assert response == handshake_response("b" * 12)


def test_cli_refuses_placeholder_dependencies_without_connecting_or_leaking_details():
    result = subprocess.run(
        [sys.executable, "scripts/production_readiness.py"],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, **production_environment()},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 1
    assert json.loads(result.stdout) == {
        "checks": {
            "artifacts": "error",
            "capability": "error",
            "configuration": "ok",
            "database": "error",
                "evaluator": "error",
                "role": "error",
                "runtime_config": "error",
                "schema": "error",
            "worker": "error",
        },
        "status": "not_ready",
    }
    assert result.stderr == ""


def test_catalog_probes_hash_bounded_read_only_schema_and_role_acl_rls_rows():
    class Cursor:
        query = ""

        def __init__(self):
            self.executed = []

        def execute(self, query, params=None):
            self.query = " ".join(query.split())
            self.executed.append((self.query, params))

        def fetchall(self):
            if "pg_get_policy" in self.query or "pg_policy" in self.query:
                return [
                    {"canonical_line": "policy|trading.qt_rows.qt_owner|roles=api|cmd=r"},
                    {"canonical_line": "relation|trading.qt_rows|acl=api=r|rls=true|force=true"},
                ]
            return [
                {"canonical_line": "column|trading.qt_rows.id|uuid|NO|"},
                {"canonical_line": "constraint|trading.qt_rows.qt_rows_pkey|PRIMARY KEY (id)"},
            ]

    cursor = Cursor()
    role_digest = sha256(
        b"policy|trading.qt_rows.qt_owner|roles=api|cmd=r\n"
        b"relation|trading.qt_rows|acl=api=r|rls=true|force=true\n"
    ).hexdigest()
    assert schema_contract_probe(cursor) == sha256(
        b"column|trading.qt_rows.id|uuid|NO|\n"
        b"constraint|trading.qt_rows.qt_rows_pkey|PRIMARY KEY (id)\n"
        + ("role-policy-digest|" + role_digest + "\n").encode()
    ).hexdigest()
    assert role_contract_probe(cursor) == sha256(
        b"policy|trading.qt_rows.qt_owner|roles=api|cmd=r\n"
        b"relation|trading.qt_rows|acl=api=r|rls=true|force=true\n"
    ).hexdigest()
    timeout_calls = [(query, params) for query, params in cursor.executed
                     if "_timeout" in query]
    assert timeout_calls == [
        ("SET LOCAL statement_timeout = %s", (5000,)),
        ("SET LOCAL lock_timeout = %s", (5000,)),
        ("SET LOCAL statement_timeout = %s", (5000,)),
        ("SET LOCAL lock_timeout = %s", (5000,)),
        ("SET LOCAL statement_timeout = %s", (5000,)),
        ("SET LOCAL lock_timeout = %s", (5000,)),
    ]


def test_rehearsal_contract_is_explicit_socket_only_and_fixed_name(tmp_path):
    artifact_path, database_path, _artifact, database = resolved_manifests(tmp_path)
    root = Path("/dev/shm/algolens-qt-rehearsal.synthetic")
    database["database"].update({
        "name": "qt_rehearsal_migrated",
        "server_addr": "socket",
        "data_directory": str(root / "data"),
        "role": "qt_algolens_api",
    })
    database_path.write_text(json.dumps(database))
    environment = production_environment(
        FLASK_ENV="rehearsal",
        DB_NAME="qt_rehearsal_migrated",
        DB_HOST=str(root / "socket"),
        DB_USER="qt_algolens_api",
        QT_RELEASE_ARTIFACT_MANIFEST=str(artifact_path),
        QT_DATABASE_IDENTITY_MANIFEST=str(database_path),
    )

    contract = load_runtime_contract(
        environment, context="rehearsal", rehearsal_root=root
    )
    assert contract.context == "rehearsal"
    assert contract.database_manifest["database"]["name"] == "qt_rehearsal_migrated"

    for changes in (
        {"FLASK_ENV": "production"},
        {"DB_NAME": "new_algo_data"},
        {"DB_NAME": "arbitrary_rehearsal"},
        {"DB_HOST": "127.0.0.1"},
        {"DB_HOST": "/tmp/postgresql"},
    ):
        with pytest.raises(ProductionConfigurationError, match="production_configuration_invalid"):
            load_runtime_contract(
                {**environment, **changes}, context="rehearsal", rehearsal_root=root
            )


def test_runtime_composition_wires_all_real_probes_in_one_read_only_transaction(tmp_path):
    from flask import Flask
    from algolens.adapters.http.capability_guard import install_capability_guard, open_route

    artifact_path, database_path, artifact, database = resolved_manifests(tmp_path)
    app = Flask(__name__)

    @app.get("/health")
    @open_route
    def health():
        return {"status": "ok"}

    install_capability_guard(app)
    app.config["CAPABILITY_GUARD_INSTALLED"] = True
    database["dependencies"]["capability"]["sha256"] = capability_contract_digest(app)
    database["dependencies"]["worker"]["sha256"] = worker_contract_digest(artifact)
    database_path.write_text(json.dumps(database))
    artifact_path.write_text(json.dumps(artifact))
    contract = load_runtime_contract(production_environment(
        QT_RELEASE_ARTIFACT_MANIFEST=str(artifact_path),
        QT_DATABASE_IDENTITY_MANIFEST=str(database_path),
    ))

    class Cursor:
        query = ""

        def execute(self, query, params=None):
            self.query = " ".join(query.split())

        def fetchone(self):
            if "worker_schema_ready" in self.query:
                return {"worker_schema_ready": True, "active_workers": 1, "queue_healthy": True}
            if "current_database()" in self.query:
                return {
                    "database_name": "new_algo_data",
                    "server_addr": "192.0.2.10",
                    "data_directory": "/approved/postgres/data",
                    "database_role": "algolens_api_runtime",
                }
            if "FROM pg_roles" in self.query:
                return {name: False for name in (
                    "rolsuper", "rolcreaterole", "rolcreatedb", "rolreplication", "rolbypassrls"
                )}
            if "capability_tables_ready" in self.query:
                return {"capability_tables_ready": True, "launch_authority_ready": True}
            raise AssertionError(self.query)

        def fetchall(self):
            if "strategy_registry" in self.query:
                return [{key: database["live_books"][0][key] for key in
                         ("registry_id", "strategy_id", "book_id", "lifecycle")}]
            if "qt_source_policies" in self.query:
                return [{key: database["live_books"][0][key] for key in
                         ("book_id", "evaluator_build", "evaluator_sha256", "evaluator_bundle_sha256")}]
            if "pg_policy" in self.query:
                return [{"canonical_line": "role-contract"}]
            if "WITH catalog" in self.query:
                return [{"canonical_line": "schema-contract"}]
            raise AssertionError(self.query)

        def __enter__(self): return self
        def __exit__(self, *args): return False

    database["database"]["role_contract_sha256"] = sha256(b"role-contract\n").hexdigest()
    database["database"]["schema_sha256"] = sha256((
        "schema-contract\nrole-policy-digest|" + database["database"]["role_contract_sha256"] + "\n"
    ).encode()).hexdigest()
    database_path.write_text(json.dumps(database))
    contract = load_runtime_contract(production_environment(
        QT_RELEASE_ARTIFACT_MANIFEST=str(artifact_path),
        QT_DATABASE_IDENTITY_MANIFEST=str(database_path),
    ))

    class Connection:
        def __init__(self):
            self.session = None
            self.rolled_back = False
            self.closed = False
        def set_session(self, **kwargs): self.session = kwargs
        def cursor(self): return Cursor()
        def rollback(self): self.rolled_back = True
        def close(self): self.closed = True

    connection = Connection()
    result = evaluate_runtime_readiness(
        contract,
        application=app,
        connection_factory=lambda: connection,
        runtime_configuration_probe=lambda _contract: "0" * 64,
        evaluator_probe=lambda _contract: handshake_response(
            artifact["evaluator"]["evaluator_build"]
        ),
    )
    assert result.ready is True, result.failure_codes
    assert connection.session == {"readonly": True, "autocommit": False}
    assert connection.rolled_back is True
    assert connection.closed is True


def test_cli_uses_application_route_inventory_and_runtime_probe_composition(monkeypatch, capsys):
    import scripts.production_readiness as command

    application = object()
    contract = object()
    observed = {}

    class Result:
        ready = True
        failure_codes = ()
        def public_payload(self): return {"status": "ready"}
        def evidence_payload(self): return {"schema": "algolens-readiness-evidence/v1"}

    monkeypatch.setattr(command, "create_app", lambda: application)
    monkeypatch.setattr(command, "load_runtime_contract", lambda *args, **kwargs: contract)
    monkeypatch.setattr(command, "evaluate_readiness", lambda _contract: Result())

    def composed(received, **kwargs):
        observed.update(contract=received, **kwargs)
        return Result()

    monkeypatch.setattr(command, "evaluate_runtime_readiness", composed)
    assert command.main([]) == 0
    assert observed["contract"] is contract
    assert observed["application"] is application
    assert observed["connection_factory"] is command.get_db_connection
    assert json.loads(capsys.readouterr().out) == {"status": "ready"}


def test_ready_endpoint_uses_the_same_concrete_runtime_composition(monkeypatch, tmp_path):
    import algolens.infrastructure.config.app_factory as factory

    contract = object()
    observed = {}

    class Result:
        ready = True
        def public_payload(self): return {"status": "ready", "checks": {}}

    monkeypatch.chdir(tmp_path)
    for name, value in {
        "FLASK_ENV": "production",
        "FLASK_DEBUG": "false",
        "DEV_MODE": "0",
        "CORS_ORIGINS": "https://example.invalid",
        "JWT_SECRET_KEY": "synthetic-test-key-with-more-than-32-bytes",
        "APP_RELEASE_SHA": "a" * 40,
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(factory, "load_runtime_contract", lambda: contract)

    def composed(received, **kwargs):
        observed.update(contract=received, **kwargs)
        return Result()

    monkeypatch.setattr(factory, "evaluate_runtime_readiness", composed)
    app = factory.create_app()
    response = app.test_client().get("/ready")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ready", "checks": {}}
    assert observed["contract"] is contract
    assert observed["application"] is app
    assert observed["connection_factory"] is factory.get_db_connection


def test_rehearsal_factory_requires_explicit_root_and_retains_production_guards(monkeypatch, tmp_path):
    import algolens.infrastructure.config.app_factory as factory
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FLASK_ENV", "rehearsal")
    monkeypatch.setenv("DEV_MODE", "0")
    monkeypatch.setenv("FLASK_DEBUG", "false")
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    with pytest.raises(RuntimeError, match="Explicit rehearsal root required"):
        factory.create_app()
    observed = {}
    def load(**kwargs):
        observed.update(kwargs)
        return object()
    monkeypatch.setattr(factory, "load_runtime_contract", load)
    monkeypatch.setenv("CORS_ORIGINS", "https://example.invalid")
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    root = Path("/dev/shm/algolens-qt-rehearsal.synthetic")
    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY must be set"):
        factory.create_app(rehearsal_root=root)
    monkeypatch.setenv("JWT_SECRET_KEY", "synthetic-test-key-with-more-than-32-bytes")
    app = factory.create_app(rehearsal_root=root)
    assert app.config["ALGOLENS_IS_PRODUCTION"] is True
    assert app.config["JWT_COOKIE_SECURE"] is True
    assert app.config["CAPABILITY_GUARD_INSTALLED"] is True
    assert observed == {"context": "rehearsal", "rehearsal_root": root}


@pytest.mark.parametrize("changes", [
    {"active_workers": 0}, {"active_workers": True}, {"queue_healthy": False},
    {"worker_schema_ready": False},
])
def test_worker_probe_refuses_absence_stale_queue_and_unresolved_schema(tmp_path, changes):
    from algolens.infrastructure.config.production_readiness import worker_readiness_probe
    artifact_path, database_path, artifact, database = resolved_manifests(tmp_path)
    contract = load_runtime_contract(production_environment(
        QT_RELEASE_ARTIFACT_MANIFEST=str(artifact_path),
        QT_DATABASE_IDENTITY_MANIFEST=str(database_path),
    ))
    expected = {"schema": "qt-worker-service/v1", "sha256": worker_contract_digest(artifact)}
    class Cursor:
        def execute(self, query, params=None): pass
        def fetchone(self):
            return {"worker_schema_ready": True, "active_workers": 1,
                    "queue_healthy": True, **changes}
    assert worker_readiness_probe(Cursor(), expected, contract) is False


def test_schema_catalog_is_role_independent_and_role_digest_covers_security_settings():
    from algolens.infrastructure.config.production_readiness import (
        _IDENTITY_SQL, _SCHEMA_CONTRACT_SQL, _ROLE_CONTRACT_SQL, _WORKER_READINESS_SQL,
    )
    assert "information_schema.columns" not in _SCHEMA_CONTRACT_SQL
    assert "pg_attribute" in _SCHEMA_CONTRACT_SQL
    assert "data_directory" not in _IDENTITY_SQL
    for catalog in ("pg_auth_members", "pg_default_acl", "pg_policy", "pg_db_role_setting"):
        assert catalog in _ROLE_CONTRACT_SQL
    assert "proconfig" in _ROLE_CONTRACT_SQL
    assert "usename='qt_worker'" in _WORKER_READINESS_SQL
    assert "backend_type" not in _WORKER_READINESS_SQL


def test_capability_probe_refuses_changed_launch_authority():
    from algolens.infrastructure.config.production_readiness import capability_readiness_probe
    class Cursor:
        def execute(self, query, params=None): pass
        def fetchone(self):
            return {"capability_tables_ready": True, "launch_authority_ready": False}
    assert capability_readiness_probe(Cursor(), {}, None) is False
