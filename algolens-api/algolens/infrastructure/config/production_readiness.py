"""Fail-closed, read-only production runtime identity checks.

The checked-in manifests are dependency placeholders.  A placeholder can be
parsed so integration work is deterministic, but can never report readiness.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from threading import Lock
import time
from typing import Callable, Mapping


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_IMAGE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_FIXED_BUNDLE_DIRECTORY = Path("/app/qt-evaluator-bundle")
_FIXED_RUNTIME_CONFIG = Path("/app/runtime-control/manifest.json")
_ARTIFACT_KINDS = {
    "libtrade_ngin.so": "engine",
    "live_equity_mean_reversion": "system_publisher",
    "live_portfolio": "system_publisher",
    "live_portfolio_conservative": "system_publisher",
    "qt_desk_prepare_sources": "desk_tool",
    "qt_desk_run": "desk_tool",
    "qt_desk_worker": "desk_worker",
    "qt_evaluator": "evaluator",
}


class ProductionConfigurationError(RuntimeError):
    """Fixed public-safe production configuration refusal."""


def canonical_json(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def _configuration_error():
    raise ProductionConfigurationError("production_configuration_invalid")


def _object(pairs):
    value = {}
    for name, item in pairs:
        if name in value:
            raise ValueError("duplicate_json_key")
        value[name] = item
    return value


def _read_manifest(path_value: str, schema: str) -> tuple[dict, str]:
    try:
        path = Path(path_value)
        if not path.is_absolute() or path.is_symlink() or not path.is_file():
            _configuration_error()
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8", "strict"), object_pairs_hook=_object)
    except (OSError, ValueError, TypeError, UnicodeError):
        _configuration_error()
    if not isinstance(value, dict) or value.get("schema") != schema:
        _configuration_error()
    if schema == "algolens-database-identity/v1":
        if value.get("state") not in {"resolved", "dependency-placeholder"}:
            _configuration_error()
    elif "state" in value and value.get("state") != "dependency-placeholder":
        _configuration_error()
    return value, sha256(raw).hexdigest()


def _valid_digest(value) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _valid_release_artifact(artifact: dict) -> bool:
    if (artifact.get("state") == "dependency-placeholder"
            or artifact.get("integration") == {"pending_artifacts": ["qt_desk_worker"]}):
        return False
    try:
        if set(artifact) != {
            "schema", "source", "build", "image", "evaluator", "artifacts",
            "integration", "manifest_sha256",
        }:
            return False
        source, build, image = artifact["source"], artifact["build"], artifact["image"]
        evaluator, rows = artifact["evaluator"], artifact["artifacts"]
        if not (
            artifact["schema"] == "release-artifacts/v1"
            and set(source) == {"git_sha_full", "git_sha_short", "dirty"}
            and _GIT_SHA.fullmatch(source["git_sha_full"])
            and isinstance(source["git_sha_short"], str)
            and 7 <= len(source["git_sha_short"]) <= 40
            and source["git_sha_full"].startswith(source["git_sha_short"])
            and source["dirty"] is False
            and set(build) == {
                "build_type", "compiler", "cxx_standard", "toolchain_image_digest",
                "cmake_inputs",
            }
            and build["build_type"] == "Release"
            and build["cxx_standard"] == "20"
            and set(build["compiler"]) == {"id", "version"}
            and all(isinstance(build["compiler"][key], str) and build["compiler"][key].strip()
                    for key in ("id", "version"))
            and _IMAGE_DIGEST.fullmatch(build["toolchain_image_digest"])
            and isinstance(build["cmake_inputs"], list)
            and build["cmake_inputs"] == sorted(set(build["cmake_inputs"]))
            and bool(build["cmake_inputs"])
            and all(isinstance(item, str) and item and len(item) <= 512
                    for item in build["cmake_inputs"])
            and set(image) == {"digest"}
            and _IMAGE_DIGEST.fullmatch(image["digest"])
            and set(evaluator) == {
                "evaluator_build", "evaluator_sha256", "evaluator_bundle_sha256",
                "bundle_manifest_sha256", "install_path",
            }
            and evaluator["evaluator_build"] == source["git_sha_short"]
            and all(_valid_digest(evaluator[key]) for key in (
                "evaluator_sha256", "evaluator_bundle_sha256", "bundle_manifest_sha256",
            ))
            and evaluator["install_path"] == "qt-evaluator-bundle"
            and artifact["integration"] == {"pending_artifacts": []}
            and isinstance(rows, list)
            and len(rows) == len(_ARTIFACT_KINDS)
        ):
            return False
        names = []
        for row in rows:
            if not (
                isinstance(row, dict)
                and set(row) == {"name", "kind", "install_path", "size", "sha256"}
                and row["name"] in _ARTIFACT_KINDS
                and row["kind"] == _ARTIFACT_KINDS[row["name"]]
                and row["install_path"] == f"bin/Release/{row['name']}"
                and type(row["size"]) is int
                and 0 < row["size"] <= 1024 * 1024 * 1024
                and _valid_digest(row["sha256"])
            ):
                return False
            names.append(row["name"])
        if names != sorted(_ARTIFACT_KINDS):
            return False
        evaluator_row = next(row for row in rows if row["name"] == "qt_evaluator")
        if evaluator_row["sha256"] != evaluator["evaluator_sha256"]:
            return False
        unsigned = {key: value for key, value in artifact.items() if key != "manifest_sha256"}
        return (
            _valid_digest(artifact["manifest_sha256"])
            and sha256(canonical_json(unsigned)).hexdigest() == artifact["manifest_sha256"]
        )
    except (KeyError, TypeError, ValueError):
        return False


@dataclass(frozen=True)
class RuntimeContract:
    release_sha: str
    evaluator_bundle_directory: Path
    runtime_config_sha256: str
    artifact_manifest: dict
    artifact_manifest_sha256: str
    database_manifest: dict
    database_manifest_sha256: str


def load_runtime_contract(environment: Mapping[str, str] | None = None) -> RuntimeContract:
    environment = os.environ if environment is None else environment
    release_sha = environment.get("APP_RELEASE_SHA", "")
    bundle_directory = Path(environment.get("QT_EVALUATOR_BUNDLE_DIR", ""))
    runtime_config = Path(environment.get("QT_RUNTIME_CONFIG_MANIFEST", ""))
    runtime_config_sha256 = environment.get("QT_RUNTIME_CONFIG_SHA256", "")
    if (
        environment.get("FLASK_ENV") != "production"
        or environment.get("FLASK_DEBUG", "").lower() != "false"
        or environment.get("DEV_MODE") != "0"
        or _GIT_SHA.fullmatch(release_sha) is None
        or environment.get("QT_EMAIL_DELIVERY_ENABLED", "").lower() not in {"false", "0"}
        or environment.get("DB_NAME") != "new_algo_data"
        or bundle_directory != _FIXED_BUNDLE_DIRECTORY
        or runtime_config != _FIXED_RUNTIME_CONFIG
        or not _valid_digest(runtime_config_sha256)
    ):
        _configuration_error()
    artifact, artifact_sha256 = _read_manifest(
        environment.get("QT_RELEASE_ARTIFACT_MANIFEST", ""), "release-artifacts/v1"
    )
    database, database_sha256 = _read_manifest(
        environment.get("QT_DATABASE_IDENTITY_MANIFEST", ""), "algolens-database-identity/v1"
    )
    return RuntimeContract(
        release_sha.lower(), bundle_directory, runtime_config_sha256,
        artifact, artifact_sha256, database, database_sha256,
    )


@dataclass(frozen=True)
class ReadinessResult:
    checks: dict[str, str]
    failure_codes: tuple[str, ...]
    evidence: dict

    @property
    def ready(self) -> bool:
        return not self.failure_codes and all(value == "ok" for value in self.checks.values())

    def public_payload(self) -> dict:
        return {"status": "ready" if self.ready else "not_ready", "checks": dict(sorted(self.checks.items()))}

    def evidence_payload(self) -> dict:
        return self.evidence


class ReadinessSnapshotCache:
    """Serialize deep probes and reuse a result only for a short bounded TTL."""

    def __init__(self, ttl_seconds: float, *, clock=time.monotonic):
        if not isinstance(ttl_seconds, (int, float)) or not 0 < ttl_seconds <= 30:
            raise ValueError("invalid_readiness_cache_ttl")
        self._ttl_seconds = float(ttl_seconds)
        self._clock = clock
        self._lock = Lock()
        self._expires_at = 0.0
        self._value = None

    def get(self, probe: Callable):
        with self._lock:
            now = self._clock()
            if self._value is None or now >= self._expires_at:
                value = probe()
                self._value = value
                self._expires_at = now + self._ttl_seconds
            return self._value


def _contract_shape(contract: RuntimeContract) -> list[str]:
    failures = []
    artifact, database = contract.artifact_manifest, contract.database_manifest
    evaluator = artifact.get("evaluator")
    db = database.get("database")
    books = database.get("live_books")
    dependencies = database.get("dependencies")
    if (artifact.get("state") == "dependency-placeholder"
            or artifact.get("integration") == {"pending_artifacts": ["qt_desk_worker"]}):
        failures.append("artifact_contract_unresolved")
    elif not _valid_release_artifact(artifact):
        failures.append("artifact_contract_invalid")
    if database.get("state") != "resolved":
        failures.append("database_contract_unresolved")
    elif not (
        isinstance(db, dict)
        and db.get("name") == "new_algo_data"
        and all(isinstance(db.get(key), str) and db[key].strip()
                for key in ("server_addr", "data_directory", "role"))
        and _valid_digest(db.get("role_contract_sha256"))
        and _valid_digest(db.get("schema_sha256"))
        and isinstance(books, list)
        and len(books) == 1
        and isinstance(books[0], dict)
        and books[0].get("registry_id") == "trendfollowing"
        and books[0].get("strategy_id") == "LIVE_TREND_FOLLOWING"
        and books[0].get("book_id") == "CONSERVATIVE_PORTFOLIO"
        and books[0].get("lifecycle") == "live"
        and isinstance(books[0].get("evaluator_build"), str)
        and books[0]["evaluator_build"].strip()
        and _valid_digest(books[0].get("evaluator_sha256"))
        and _valid_digest(books[0].get("evaluator_bundle_sha256"))
        and isinstance(dependencies, dict)
    ):
        failures.append("database_contract_invalid")
    dependency_schemas = {
        "capability": "qt-capabilities/v1",
        "worker": "qt-worker-service/v1",
    }
    for name, dependency_schema in dependency_schemas.items():
        value = dependencies.get(name) if isinstance(dependencies, dict) else None
        if not isinstance(value, dict) or value.get("state") != "resolved":
            failures.append(f"{name}_contract_unresolved")
        elif value.get("schema") != dependency_schema or not _valid_digest(value.get("sha256")):
            failures.append(f"{name}_contract_invalid")
    return failures


_IDENTITY_SQL = """
SELECT current_database() AS database_name,
       COALESCE(inet_server_addr()::text, 'socket') AS server_addr,
       current_setting('data_directory') AS data_directory,
       current_user AS database_role
"""
_ROLE_SQL = """
SELECT rolsuper, rolcreaterole, rolcreatedb, rolreplication, rolbypassrls
FROM pg_roles WHERE rolname = current_user
"""
_LIVE_REGISTRY_SQL = """
SELECT r.id AS registry_id, r.strategy_type AS strategy_id,
       r.portfolio_id AS book_id, r.lifecycle
FROM trading.strategy_registry r
WHERE r.is_active IS TRUE AND r.lifecycle = 'live'
ORDER BY r.id, r.strategy_type, r.portfolio_id
"""
_EVALUATION_POLICY_SQL = """
SELECT p.book_id, p.evaluator_build, p.evaluator_sha256, p.evaluator_bundle_sha256
FROM trading.qt_source_policies p
WHERE p.purpose = 'evaluation' AND p.enabled IS TRUE
ORDER BY p.book_id
"""


def _selected_rows(rows, keys) -> list[dict]:
    return [{key: row[key] for key in keys} for row in rows]


def _evaluator_readiness_request(evaluator_build: str) -> dict:
    def key(component):
        return {
            "portfolio_id": "synthetic-book-A",
            "strategy_id": component,
            "strategy_name": "synthetic-alpha" if component == "component-1" else "synthetic-beta",
            "date": "2026-09-25",
            "symbol": "SYN",
            "portfolio_type": "qt_proposal",
        }

    instrument = {"instrument_type": "EQUITY", "symbol": "SYN"}
    slots = []
    quantities = []
    costs = []
    for component, previous, selected in (("component-1", "4", "5"), ("component-2", "2", "1")):
        component_key = key(component)
        slots.append({
            "key": component_key,
            "instrument": instrument,
            "editable": True,
            "previous": {
                "symbol": "SYN", "quantity_exact": previous, "average_price_exact": "100",
                "unrealized_pnl_exact": "0", "realized_pnl_exact": "0",
                "last_update": "2026-09-25T12:00:00Z",
            },
        })
        quantities.append({"key": component_key, "quantity_exact": selected})
        costs.append({
            "key": component_key, "instrument": instrument,
            "calculation_increment_exact": "1", "cash_cost_per_increment_exact": "0.01",
            "approved_model_id": "linear-cash-per-increment-v1",
            "source_id": "synthetic-cost-source-v1", "currency": "USD",
        })
    scope = {
        "expected_portfolio_id": "synthetic-book-A", "expected_date": "2026-09-25",
        "expected_portfolio_type": "qt_proposal", "expected_revision": "synthetic-revision-1",
    }
    return {
        "schema": "qt-eval/v1", "operation": "selected_book",
        "evaluator_build": evaluator_build, "context_fingerprint": "1" * 64,
        "risk_config_source_id": "synthetic-risk-policy-v1",
        "context": {
            "portfolio_id": "synthetic-book-A", "date": "2026-09-25",
            "portfolio_type": "qt_proposal", "revision": "synthetic-revision-1",
            "slots": slots,
        },
        "proposal": {**scope, "quantities": quantities},
        "risk_inputs": {
            **scope, "market_snapshot_id": "synthetic-market-v1",
            "valuation_time": "2026-09-25T12:00:00.123456Z", "capital_currency": "USD",
            "valuations": [{
                "instrument": instrument, "mark_as_of": "2026-09-25T12:00:00.123456Z",
                "mark": "100", "price_multiplier": "1", "quote_currency": "USD",
            }],
            "expected_observation_times": [
                "2026-09-22T12:00:00Z", "2026-09-23T12:00:00Z", "2026-09-24T12:00:00Z",
            ],
            "closes": [
                {"instrument": instrument, "timestamp": timestamp, "close": close}
                for timestamp, close in (
                    ("2026-09-22T12:00:00Z", "98"),
                    ("2026-09-23T12:00:00Z", "99"),
                    ("2026-09-24T12:00:00Z", "100"),
                )
            ],
        },
        "risk_config": {
            "var_limit": "0.15", "jump_risk_limit": "0.1", "max_correlation": "0.7",
            "corr_shock_threshold": "0.65", "jump_shock_threshold": "0.75",
            "max_gross_leverage": "4", "max_net_leverage": "2", "confidence_level": "0.99",
            "lookback_period": 3, "capital_exact": "1000000",
            "version": "synthetic-risk-config-v1",
        },
        "quantity_rules": [{
            "instrument": instrument, "increment_exact": "0.00000001",
            "mode": "reject_off_increment", "minimum_exact": "-1000000",
            "maximum_exact": "1000000",
        }],
        "component_cost_inputs": costs,
    }


def _valid_evaluator_readiness_response(response: dict, evaluator_build: str) -> bool:
    return (
        isinstance(response, dict)
        and response.get("schema") == "qt-eval/v1"
        and response.get("operation") == "selected_book"
        and response.get("evaluator_build") == evaluator_build
        and response.get("context_fingerprint") == "1" * 64
        and response.get("completeness") == "complete"
        and [row.get("quantity_exact") for row in response.get("evaluated_book", [])] == ["5", "1"]
        and isinstance(response.get("selected_risk"), dict)
        and response["selected_risk"].get("status") == "evaluated"
        and response["selected_risk"].get("passed") is True
        and isinstance(response.get("selected_costs"), dict)
        and response["selected_costs"].get("status") == "evaluated"
        and response["selected_costs"].get("total_exact") == "0.02"
    )


def evaluator_isolation_probe(contract: RuntimeContract, *, process_factory=None):
    """Run the manifest's deterministic request through the sealed bundle path."""
    if process_factory is None:
        from algolens.infrastructure.portfolio.qt_evaluator_process import QtEvaluatorProcess
        process_factory = QtEvaluatorProcess
    evaluator = contract.artifact_manifest["evaluator"]
    process = process_factory(
        contract.evaluator_bundle_directory / "bin" / "qt_evaluator",
        evaluator["evaluator_sha256"],
        evaluator["evaluator_build"],
        bundle_directory=contract.evaluator_bundle_directory,
        expected_bundle_sha256=evaluator["evaluator_bundle_sha256"],
    )
    return process.run(_evaluator_readiness_request(evaluator["evaluator_build"]))


def runtime_configuration_file_probe(contract: RuntimeContract) -> str:
    """Hash the exact fixed runtime-control file without following a final symlink."""
    path = _FIXED_RUNTIME_CONFIG
    if path.is_symlink() or not path.is_file():
        raise ProductionConfigurationError("runtime_configuration_unavailable")
    return sha256(path.read_bytes()).hexdigest()


def evaluate_readiness(
    contract: RuntimeContract,
    *,
    connection_factory: Callable | None = None,
    schema_probe: Callable | None = None,
    role_probe: Callable | None = None,
    runtime_configuration_probe: Callable | None = None,
    evaluator_probe: Callable | None = None,
    capability_probe: Callable | None = None,
    worker_probe: Callable | None = None,
) -> ReadinessResult:
    checks = {
        name: "error"
        for name in (
            "artifacts", "capability", "configuration", "database", "evaluator",
            "role", "runtime_config", "schema", "worker",
        )
    }
    checks["configuration"] = "ok"
    failures = _contract_shape(contract)
    if not failures:
        checks["artifacts"] = "ok"
    else:
        # Placeholder dependencies intentionally stop before opening a database or launching bytes.
        return ReadinessResult(
            checks,
            tuple(failures),
            {"schema": "algolens-readiness-evidence/v1", "status": "not_ready"},
        )

    database_manifest = contract.database_manifest
    expected_db = database_manifest["database"]
    evaluator = contract.artifact_manifest["evaluator"]
    expected_books = _selected_rows(
        database_manifest["live_books"],
        (
            "registry_id", "strategy_id", "book_id", "lifecycle", "evaluator_build",
            "evaluator_sha256", "evaluator_bundle_sha256",
        ),
    )
    expected_dependencies = {
        name: _selected_rows([database_manifest["dependencies"][name]],
                             ("schema", "state", "sha256"))[0]
        for name in ("capability", "worker")
    }
    if any(
        book.get("evaluator_build") != evaluator["evaluator_build"]
        or book.get("evaluator_sha256") != evaluator["evaluator_sha256"]
        or book.get("evaluator_bundle_sha256") != evaluator["evaluator_bundle_sha256"]
        for book in expected_books
    ):
        failures.append("artifact_policy_pin_mismatch")

    if runtime_configuration_probe is None:
        failures.append("runtime_configuration_dependency_unavailable")
    else:
        try:
            if runtime_configuration_probe(contract) != contract.runtime_config_sha256:
                failures.append("runtime_configuration_mismatch")
            else:
                checks["runtime_config"] = "ok"
        except Exception:
            failures.append("runtime_configuration_failed")

    identity = None
    database_verified = False
    schema_verified = False
    role_verified = False
    if connection_factory is None:
        failures.append("database_dependency_unavailable")
    else:
        connection = None
        try:
            connection = connection_factory()
            connection.set_session(readonly=True, autocommit=False)
            with connection.cursor() as cursor:
                cursor.execute(_IDENTITY_SQL)
                identity = cursor.fetchone()
                expected_identity = {
                    "database_name": expected_db["name"],
                    "server_addr": expected_db["server_addr"],
                    "data_directory": expected_db["data_directory"],
                    "database_role": expected_db["role"],
                }
                identity_verified = identity == expected_identity
                if not identity_verified:
                    failures.append("database_identity_mismatch")
                cursor.execute(_ROLE_SQL)
                role_attributes = cursor.fetchone()
                if role_attributes.get("rolsuper") is not False:
                    failures.append("database_role_is_superuser")
                role_flags_verified = all(
                    role_attributes.get(name) is False
                    for name in (
                        "rolsuper", "rolcreaterole", "rolcreatedb",
                        "rolreplication", "rolbypassrls",
                    )
                )
                if not role_flags_verified and role_attributes.get("rolsuper") is False:
                    failures.append("database_role_is_privileged")
                if role_probe is None:
                    failures.append("role_dependency_unavailable")
                else:
                    role_verified = role_probe(cursor) == expected_db["role_contract_sha256"]
                    if not role_verified:
                        failures.append("role_contract_mismatch")
                if schema_probe is None:
                    failures.append("schema_dependency_unavailable")
                else:
                    schema_verified = schema_probe(cursor) == expected_db["schema_sha256"]
                    if not schema_verified:
                        failures.append("schema_digest_mismatch")
                expected_registry = _selected_rows(
                    expected_books, ("registry_id", "strategy_id", "book_id", "lifecycle")
                )
                expected_policies = _selected_rows(
                    expected_books,
                    ("book_id", "evaluator_build", "evaluator_sha256", "evaluator_bundle_sha256"),
                )
                cursor.execute(_LIVE_REGISTRY_SQL)
                registry_verified = _selected_rows(
                    cursor.fetchall(), ("registry_id", "strategy_id", "book_id", "lifecycle")
                ) == expected_registry
                cursor.execute(_EVALUATION_POLICY_SQL)
                policies_verified = _selected_rows(
                    cursor.fetchall(),
                    ("book_id", "evaluator_build", "evaluator_sha256", "evaluator_bundle_sha256"),
                ) == expected_policies
                books_verified = registry_verified and policies_verified
                if not books_verified:
                    failures.append("live_book_contract_mismatch")
                database_verified = identity_verified and role_flags_verified and books_verified
            connection.rollback()
        except Exception:
            database_verified = False
            schema_verified = False
            role_verified = False
            failures.append("database_check_failed")
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    database_verified = False
                    schema_verified = False
                    role_verified = False
                    failures.append("database_check_failed")
    if database_verified:
        checks["database"] = "ok"
    if schema_verified:
        checks["schema"] = "ok"
    if role_verified:
        checks["role"] = "ok"

    handshake_response_sha256 = None
    if evaluator_probe is None:
        failures.append("evaluator_dependency_unavailable")
    else:
        try:
            response = evaluator_probe(contract)
            if not _valid_evaluator_readiness_response(response, evaluator["evaluator_build"]):
                failures.append("evaluator_handshake_mismatch")
            else:
                handshake_response_sha256 = sha256(canonical_json(response)).hexdigest()
        except Exception:
            failures.append("evaluator_handshake_failed")
    if not any(code.startswith("evaluator_") or code == "artifact_policy_pin_mismatch" for code in failures):
        checks["evaluator"] = "ok"

    for name, probe in (("capability", capability_probe), ("worker", worker_probe)):
        expected = expected_dependencies[name]
        try:
            if probe is None or probe(expected) is not True:
                failures.append(f"{name}_dependency_unready")
            else:
                checks[name] = "ok"
        except Exception:
            failures.append(f"{name}_dependency_unready")

    evidence = {
        "schema": "algolens-readiness-evidence/v1",
        "status": "ready" if not failures else "not_ready",
        "release_sha": contract.release_sha,
        "database": {
            "name": expected_db["name"],
            "server_addr": expected_db["server_addr"],
            "role": expected_db["role"],
            "role_contract_sha256": expected_db["role_contract_sha256"],
            "schema_sha256": expected_db["schema_sha256"],
        },
        "artifact": {
            **{
                key: evaluator[key]
                for key in (
                    "evaluator_build", "evaluator_sha256", "evaluator_bundle_sha256",
                    "bundle_manifest_sha256",
                )
            },
            "source_git_sha_full": contract.artifact_manifest["source"]["git_sha_full"],
            "image_digest": contract.artifact_manifest["image"]["digest"],
            "manifest_sha256": contract.artifact_manifest["manifest_sha256"],
            "handshake_response_sha256": handshake_response_sha256,
        },
        "live_books": expected_books,
        "dependencies": expected_dependencies,
        "runtime_config_sha256": contract.runtime_config_sha256,
        "manifests": {
            "release_artifacts_sha256": contract.artifact_manifest_sha256,
            "database_identity_sha256": contract.database_manifest_sha256,
        },
    }
    return ReadinessResult(dict(checks), tuple(dict.fromkeys(failures)), evidence)
