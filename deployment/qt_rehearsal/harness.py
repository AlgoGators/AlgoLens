"""Fail-closed primitives shared by the QT PostgreSQL rehearsal CLI.

This module does not inspect process database environment variables. Callers
must provide an exact private root, database, role, repository, and artifact.
"""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess


DATABASES = (
    "qt_rehearsal_baseline",
    "qt_rehearsal_migrated",
    "qt_rehearsal_destructive_tests",
)
ADMIN_ROLE = "qt_rehearsal_admin"
ROLE_DOMAINS = (
    "schema_owner",
    "migrator",
    "algolens_api",
    "system_publisher",
    "qt_worker",
)
_HEX_40 = re.compile(r"[0-9a-f]{40}\Z")
_HEX_64 = re.compile(r"[0-9a-f]{64}\Z")
_IDENTIFIER = re.compile(r"[a-z][a-z0-9_]{0,62}\Z")
_ROOT_NAME = re.compile(r"algolens-qt-rehearsal\.[A-Za-z0-9_-]{6,64}\Z")


class SafetyError(ValueError):
    """A target, SQL payload, or execution boundary is unsafe."""


class ManifestError(ValueError):
    """The ordered migration manifest is invalid or does not match source."""


class EvidenceError(ValueError):
    """Evidence contains unapproved or sensitive content."""


class RoleContractError(ValueError):
    """The role contract is incomplete or malformed."""


class InputLockError(ValueError):
    """The cross-lane input lock is incomplete or does not match bytes."""


@dataclass(frozen=True)
class ManifestEntry:
    id: str
    repository: str
    git_sha: str
    path: str
    sha256: str
    depends_on: tuple[str, ...]
    apply_predicate: dict
    rollback_policy: dict
    expected_schema_digest: str


@dataclass(frozen=True)
class Manifest:
    schema_version: str
    profile: str
    target_database: str
    entries: tuple[ManifestEntry, ...]


@dataclass(frozen=True)
class Role:
    domain: str
    name: str


@dataclass(frozen=True)
class RoleProbe:
    id: str
    role_domain: str
    sql: str
    expect: str


@dataclass(frozen=True)
class RoleContract:
    database: str
    roles: tuple[Role, ...]
    probes: tuple[RoleProbe, ...]


@dataclass(frozen=True)
class InputLockEntry:
    kind: str
    path: str
    sha256: str


@dataclass(frozen=True)
class InputLock:
    schema_version: str
    entries: tuple[InputLockEntry, ...]


def _exact_keys(value, required, *, label, error_type):
    if not isinstance(value, dict) or set(value) != set(required):
        raise error_type(f"{label} must contain exactly: {', '.join(required)}")


def validate_rehearsal_root(root):
    path = Path(root)
    if path.is_symlink():
        raise SafetyError("rehearsal root must not be a symlink")
    if not path.is_absolute() or path.parent != Path("/dev/shm"):
        raise SafetyError("rehearsal root must be one direct child of /dev/shm")
    if not _ROOT_NAME.fullmatch(path.name):
        raise SafetyError("rehearsal root name must match algolens-qt-rehearsal.<unique>")
    if not path.exists() or not path.is_dir():
        raise SafetyError("rehearsal root must be an existing directory")
    stat = path.stat(follow_symlinks=False)
    if stat.st_uid != os.getuid():
        raise SafetyError("rehearsal root must be owned by the current user")
    if stat.st_mode & 0o777 != 0o700:
        raise SafetyError("rehearsal root must have mode 0700")
    if path.resolve(strict=True) != path:
        raise SafetyError("rehearsal root realpath mismatch")
    return path


def validate_database_name(database):
    if database not in DATABASES:
        raise SafetyError("database must be one of the three fixed non-production rehearsal names")
    return database


def _sql_literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def build_identity_guard(*, database, data_directory, role):
    validate_database_name(database)
    if not _IDENTIFIER.fullmatch(role) or role == "postgres":
        raise SafetyError("rehearsal role must be an explicit non-postgres identifier")
    data = Path(data_directory)
    if not data.is_absolute() or data.name != "data" or data.parent.parent != Path("/dev/shm"):
        raise SafetyError("data directory must be the rehearsal root data directory")
    return f"""
DO $qt_identity$
BEGIN
  IF current_database() IS DISTINCT FROM {_sql_literal(database)}
     OR inet_server_addr() IS NOT NULL
     OR current_setting('data_directory') IS DISTINCT FROM {_sql_literal(str(data))}
     OR current_user IS DISTINCT FROM {_sql_literal(role)} THEN
    RAISE EXCEPTION 'qt_rehearsal_identity_mismatch';
  END IF;
END
$qt_identity$;
""".strip()


_UNSAFE_SQL = (
    re.compile(r"(?im)^\s*\\"),
    re.compile(r"(?i)\b(?:create|drop)\s+database\b"),
    re.compile(r"(?i)\balter\s+system\b"),
    re.compile(r"(?i)\bcopy\b[\s\S]*?\bprogram\b"),
    re.compile(r"(?i)\b(?:postgres_fdw|file_fdw|dblink(?:_connect)?)\b"),
    re.compile(r"(?i)\bnew_algo_data\b"),
)


def validate_sql_payload(sql):
    if not isinstance(sql, str) or not sql.strip():
        raise SafetyError("SQL payload must be non-empty text")
    if "\x00" in sql:
        raise SafetyError("SQL payload contains a NUL byte")
    for pattern in _UNSAFE_SQL:
        if pattern.search(sql):
            raise SafetyError("SQL payload contains a session, production, or external-access escape")
    return sql


def safe_restore_flags():
    return ("--exit-on-error", "--no-owner", "--no-privileges", "--file=-")


def _load_json(path, error_type):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise error_type(f"cannot load JSON: {error}") from error


def _validate_relative_path(value):
    if not isinstance(value, str):
        raise ManifestError("migration path must be relative text")
    path = PurePosixPath(value)
    if path.is_absolute():
        raise ManifestError("migration path must be relative")
    if not path.parts or any(part in ("", ".", "..") for part in path.parts):
        raise ManifestError("migration path must not escape its repository")
    if path.suffix != ".sql":
        raise ManifestError("migration path must name a SQL file")
    return value


def _validate_predicate(value):
    if not isinstance(value, dict) or value.get("type") not in ("always", "table_absent", "column_absent"):
        raise ManifestError("unsupported structured apply predicate")
    kind = value["type"]
    required = {"type"} if kind == "always" else {"type", "schema", "table"}
    if kind == "column_absent":
        required.add("column")
    if set(value) != required:
        raise ManifestError("apply predicate fields do not match its type")
    for key in required - {"type"}:
        if not isinstance(value[key], str) or not _IDENTIFIER.fullmatch(value[key]):
            raise ManifestError("apply predicate identifiers are invalid")
    return dict(value)


def load_manifest(path):
    value = _load_json(path, ManifestError)
    _exact_keys(value, ("schema_version", "profile", "target_database", "entries"), label="migration manifest", error_type=ManifestError)
    if value["schema_version"] != "qt-rehearsal-migration-manifest/v1":
        raise ManifestError("unsupported migration manifest schema version")
    if value["profile"] not in ("live-futures", "destructive-fixture"):
        raise ManifestError("unsupported rehearsal profile")
    expected_database = "qt_rehearsal_migrated" if value["profile"] == "live-futures" else "qt_rehearsal_destructive_tests"
    if value["target_database"] != expected_database:
        raise ManifestError("manifest target database does not match its profile")
    if not isinstance(value["entries"], list) or not value["entries"]:
        raise ManifestError("migration manifest entries must be a non-empty ordered list")
    entries = []
    seen = set()
    entry_keys = ("id", "repository", "git_sha", "path", "sha256", "depends_on", "apply_predicate", "rollback_policy", "expected_schema_digest")
    for raw in value["entries"]:
        _exact_keys(raw, entry_keys, label="migration entry", error_type=ManifestError)
        if not isinstance(raw["id"], str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,79}", raw["id"]):
            raise ManifestError("migration entry id is invalid")
        if raw["id"] in seen:
            raise ManifestError("duplicate migration entry id")
        if raw["repository"] not in ("algolens", "trade-ngin"):
            raise ManifestError("migration repository is unsupported")
        if not isinstance(raw["git_sha"], str) or not _HEX_40.fullmatch(raw["git_sha"]):
            raise ManifestError("migration Git SHA must be exact lowercase 40-hex")
        relative_path = _validate_relative_path(raw["path"])
        lowered = relative_path.lower()
        if value["profile"] == "live-futures" and ("002_backfill_qt_from_system" in lowered or any(token in lowered for token in ("investor", "equity", "incubating"))):
            raise ManifestError("live-futures profile refuses backfill, investor, equity, and incubating migrations")
        if not isinstance(raw["sha256"], str) or not _HEX_64.fullmatch(raw["sha256"]):
            raise ManifestError("migration SHA-256 must be exact lowercase 64-hex")
        if not isinstance(raw["depends_on"], list) or len(set(raw["depends_on"])) != len(raw["depends_on"]):
            raise ManifestError("migration dependencies must be a unique list")
        if any(dependency not in seen for dependency in raw["depends_on"]):
            raise ManifestError("every migration dependency must appear earlier in the manifest")
        predicate = _validate_predicate(raw["apply_predicate"])
        rollback = raw["rollback_policy"]
        _exact_keys(rollback, ("type", "reason"), label="rollback policy", error_type=ManifestError)
        if rollback["type"] not in ("forward_only", "reversible") or not isinstance(rollback["reason"], str) or not rollback["reason"].strip():
            raise ManifestError("rollback policy is invalid")
        if not isinstance(raw["expected_schema_digest"], str) or not _HEX_64.fullmatch(raw["expected_schema_digest"]):
            raise ManifestError("expected schema digest must be exact lowercase 64-hex")
        entries.append(ManifestEntry(raw["id"], raw["repository"], raw["git_sha"], relative_path, raw["sha256"], tuple(raw["depends_on"]), predicate, dict(rollback), raw["expected_schema_digest"]))
        seen.add(raw["id"])
    governed = (("trade-ngin", "migrations/031_live_config_overrides.sql"),
                ("algolens", "algolens-api/migrations/011_live_config_authority.sql"),
                ("algolens", "deployment/database/qt_runtime_role_contract.sql"))
    positions = {(entry.repository, entry.path): index for index, entry in enumerate(entries)}
    if any(item in positions for item in governed[:2]):
        if not all(item in positions for item in governed) or not positions[governed[0]] < positions[governed[1]] < positions[governed[2]]:
            raise ManifestError("governed configuration requires Trade031 then AlgoLens011 then role postlude")
        for earlier, later in zip(governed, governed[1:]):
            if entries[positions[earlier]].id not in entries[positions[later]].depends_on:
                raise ManifestError("governed configuration migrations require explicit dependency edges")
    return Manifest(value["schema_version"], value["profile"], value["target_database"], tuple(entries))


def _run_git(repo, args, *, binary=False):
    try:
        result = subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=not binary, timeout=30)
    except (OSError, subprocess.SubprocessError) as error:
        raise ManifestError(f"cannot verify repository Git identity: {error}") from error
    return result.stdout


def verify_manifest_sources(manifest, repositories):
    verified = []
    for entry in manifest.entries:
        if entry.repository not in repositories:
            raise ManifestError(f"repository root not supplied: {entry.repository}")
        repo = Path(repositories[entry.repository]).resolve(strict=True)
        if _run_git(repo, ["rev-parse", "HEAD"]).strip() != entry.git_sha:
            raise ManifestError(f"Git SHA mismatch for {entry.repository}")
        unresolved = repo / entry.path
        if unresolved.is_symlink():
            raise ManifestError("migration source must be a regular repository file")
        candidate = unresolved.resolve(strict=True)
        try:
            candidate.relative_to(repo)
        except ValueError as error:
            raise ManifestError("migration path attempted to escape its repository") from error
        if not candidate.is_file():
            raise ManifestError("migration source must be a regular repository file")
        working_bytes = candidate.read_bytes()
        committed_bytes = _run_git(repo, ["show", f"{entry.git_sha}:{entry.path}"], binary=True)
        digest = hashlib.sha256(working_bytes).hexdigest()
        committed_digest = hashlib.sha256(committed_bytes).hexdigest()
        if digest != entry.sha256 or committed_digest != entry.sha256:
            raise ManifestError(f"SHA-256 mismatch for migration {entry.id}")
        verified.append(entry)
    return tuple(verified)


_EVIDENCE_KEYS = {"schema_version", "run_id", "postgres_version", "root_fingerprint", "database_summaries", "role_results", "test_reports"}
_FORBIDDEN_EVIDENCE_KEY = re.compile(r"(?i)(password|secret|token|credential|dsn|uri|url|host|socket|path|raw)")
_FORBIDDEN_EVIDENCE_VALUE = re.compile(r"(?i)(postgres(?:ql)?://|/dev/shm/algolens-qt-rehearsal\.|BEGIN [A-Z ]+PRIVATE KEY)")


def _inspect_evidence(value, key=""):
    if _FORBIDDEN_EVIDENCE_KEY.search(key):
        raise EvidenceError(f"forbidden evidence field: {key}")
    if isinstance(value, dict):
        for child_key, child in value.items():
            if not isinstance(child_key, str):
                raise EvidenceError("evidence keys must be strings")
            _inspect_evidence(child, child_key)
    elif isinstance(value, list):
        for child in value:
            _inspect_evidence(child, key)
    elif isinstance(value, str) and _FORBIDDEN_EVIDENCE_VALUE.search(value):
        raise EvidenceError("evidence contains a DSN, private path, or credential material")
    elif value is not None and not isinstance(value, (str, int, float, bool)):
        raise EvidenceError("evidence contains a non-JSON value")


def sanitize_evidence(value):
    if not isinstance(value, dict) or value.get("schema_version") != "qt-rehearsal-evidence/v1":
        raise EvidenceError("unsupported evidence schema")
    if set(value) != _EVIDENCE_KEYS:
        raise EvidenceError("evidence contains missing or unknown top-level fields")
    if not isinstance(value["run_id"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value["run_id"]):
        raise EvidenceError("invalid evidence run id")
    if not isinstance(value["postgres_version"], str) or not value["postgres_version"].startswith("16."):
        raise EvidenceError("evidence must name PostgreSQL 16")
    if not isinstance(value["root_fingerprint"], str) or not _HEX_64.fullmatch(value["root_fingerprint"]):
        raise EvidenceError("invalid rehearsal root fingerprint")
    for key in ("database_summaries", "role_results", "test_reports"):
        if not isinstance(value[key], list):
            raise EvidenceError(f"{key} must be a list")
    _inspect_evidence(value)
    return value


def write_evidence(path, value):
    sanitized = sanitize_evidence(value)
    output = Path(path).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    data = (json.dumps(sanitized, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output)
        output.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)


def load_role_contract(path):
    value = _load_json(path, RoleContractError)
    _exact_keys(value, ("schema_version", "database", "roles", "probes"), label="role contract", error_type=RoleContractError)
    if value["schema_version"] != "qt-rehearsal-role-contract/v1":
        raise RoleContractError("unsupported role contract schema")
    try:
        database = validate_database_name(value["database"])
    except SafetyError as error:
        raise RoleContractError(str(error)) from error
    if database != "qt_rehearsal_migrated":
        raise RoleContractError("role contract is only valid for the migrated rehearsal database")
    if not isinstance(value["roles"], list):
        raise RoleContractError("roles must be a list")
    roles = []
    domains = set()
    names = set()
    for raw in value["roles"]:
        _exact_keys(raw, ("domain", "name"), label="role", error_type=RoleContractError)
        if raw["domain"] not in ROLE_DOMAINS or raw["domain"] in domains:
            raise RoleContractError("role domains must be unique and complete")
        if not isinstance(raw["name"], str) or not _IDENTIFIER.fullmatch(raw["name"]) or raw["name"] == "postgres":
            raise RoleContractError("role name must be a safe non-postgres identifier")
        if raw["name"] in names:
            raise RoleContractError("role names must be unique")
        roles.append(Role(raw["domain"], raw["name"]))
        domains.add(raw["domain"])
        names.add(raw["name"])
    if domains != set(ROLE_DOMAINS):
        raise RoleContractError("role domains must be unique and complete")
    if not isinstance(value["probes"], list):
        raise RoleContractError("role probes must be a list")
    probes = []
    probe_ids = set()
    outcomes = {domain: set() for domain in ROLE_DOMAINS}
    for raw in value["probes"]:
        _exact_keys(raw, ("id", "role_domain", "sql", "expect"), label="role probe", error_type=RoleContractError)
        if not isinstance(raw["id"], str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,79}", raw["id"]) or raw["id"] in probe_ids:
            raise RoleContractError("role probe ids must be unique safe identifiers")
        if raw["role_domain"] not in domains or raw["expect"] not in ("allowed", "denied"):
            raise RoleContractError("role probe domain or expectation is invalid")
        try:
            sql = validate_sql_payload(raw["sql"])
        except SafetyError as error:
            raise RoleContractError(str(error)) from error
        probes.append(RoleProbe(raw["id"], raw["role_domain"], sql, raw["expect"]))
        probe_ids.add(raw["id"])
        outcomes[raw["role_domain"]].add(raw["expect"])
    for domain in ROLE_DOMAINS:
        required = {"denied"} if domain == "schema_owner" else {"allowed", "denied"}
        if not required.issubset(outcomes[domain]):
            raise RoleContractError(f"role domain {domain} lacks required positive/negative probes")
    return RoleContract(database, tuple(roles), tuple(probes))


def load_input_lock(path):
    lock_path = Path(path)
    value = _load_json(lock_path, InputLockError)
    _exact_keys(value, ("schema_version", "entries"), label="input lock", error_type=InputLockError)
    if value["schema_version"] != "qt-rehearsal-input-lock/v1":
        raise InputLockError("unsupported input lock schema")
    required_kinds = {
        "migration_manifest",
        "artifact_manifest",
        "config_snapshot",
        "role_contract",
        "data_bundle",
    }
    if not isinstance(value["entries"], list):
        raise InputLockError("input lock entries must be a list")
    kinds = [entry.get("kind") for entry in value["entries"] if isinstance(entry, dict)]
    if len(value["entries"]) != len(required_kinds) or set(kinds) != required_kinds or len(set(kinds)) != len(kinds):
        raise InputLockError("input lock requires exactly one entry for every cross-lane input kind")
    base = lock_path.resolve(strict=True).parent
    entries = []
    for raw in value["entries"]:
        _exact_keys(raw, ("kind", "path", "sha256"), label="input lock entry", error_type=InputLockError)
        if not isinstance(raw["path"], str):
            raise InputLockError("input lock path must be relative")
        relative = PurePosixPath(raw["path"])
        if relative.is_absolute():
            raise InputLockError("input lock path must be relative")
        if not relative.parts or any(part in ("", ".", "..") for part in relative.parts):
            raise InputLockError("input lock path must not escape its directory")
        unresolved = base / raw["path"]
        if unresolved.is_symlink():
            raise InputLockError("input lock source must not be a symlink")
        try:
            source = unresolved.resolve(strict=True)
            source.relative_to(base)
        except (OSError, ValueError) as error:
            raise InputLockError("input lock path attempted to escape its directory") from error
        if not source.is_file():
            raise InputLockError("input lock source must be a regular file")
        if not isinstance(raw["sha256"], str) or not _HEX_64.fullmatch(raw["sha256"]):
            raise InputLockError("input lock SHA-256 must be exact lowercase 64-hex")
        if hashlib.sha256(source.read_bytes()).hexdigest() != raw["sha256"]:
            raise InputLockError(f"input lock SHA-256 mismatch for {raw['kind']}")
        if raw["kind"] == "config_snapshot":
            _validate_secret_stripped_config(source)
        entries.append(InputLockEntry(raw["kind"], raw["path"], raw["sha256"]))
    return InputLock(value["schema_version"], tuple(entries))


_SECRET_KEY = re.compile(r"(?i)(password|secret|token|credential|private.?key|api.?key)")
_SECRET_VALUE = re.compile(r"(?i)(postgres(?:ql)?://[^\s]+:[^\s]+@|BEGIN [A-Z ]+PRIVATE KEY)")


def _validate_secret_stripped_config(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise InputLockError(f"secret-stripped config snapshot must be JSON: {error}") from error

    def inspect(item, key=""):
        if _SECRET_KEY.search(key):
            raise InputLockError("config snapshot is not secret-stripped")
        if isinstance(item, dict):
            for child_key, child in item.items():
                if not isinstance(child_key, str):
                    raise InputLockError("config snapshot keys must be strings")
                inspect(child, child_key)
        elif isinstance(item, list):
            for child in item:
                inspect(child, key)
        elif isinstance(item, str) and _SECRET_VALUE.search(item):
            raise InputLockError("config snapshot is not secret-stripped")
        elif item is not None and not isinstance(item, (str, int, float, bool)):
            raise InputLockError("config snapshot contains a non-JSON value")

    inspect(value)
