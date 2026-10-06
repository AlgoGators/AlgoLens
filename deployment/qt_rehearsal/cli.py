"""CLI for the private, socket-only QT database rehearsal harness."""

import argparse
import json
from pathlib import Path
import sys

from .cluster import RehearsalCluster
from .harness import (
    EvidenceError,
    InputLockError,
    ManifestError,
    RoleContractError,
    SafetyError,
    load_manifest,
    load_input_lock,
    load_role_contract,
    verify_manifest_sources,
    write_evidence,
)


def _cluster_arguments(parser):
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--pg-bin", required=True, type=Path)


def _repository(value):
    if "=" not in value:
        raise argparse.ArgumentTypeError("repository must be NAME=/absolute/path")
    name, path = value.split("=", 1)
    if name not in ("algolens", "trade-ngin") or not Path(path).is_absolute():
        raise argparse.ArgumentTypeError("repository must be algolens=PATH or trade-ngin=PATH")
    return name, Path(path)


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init", help="initialize and start the private PostgreSQL 16 cluster")
    _cluster_arguments(init)

    restore = commands.add_parser("restore", help="identity-guard and restore one hash-pinned custom archive")
    _cluster_arguments(restore)
    restore.add_argument("--database", required=True, choices=("qt_rehearsal_baseline", "qt_rehearsal_migrated"))
    restore.add_argument("--archive", required=True, type=Path)
    restore.add_argument("--archive-sha256", required=True)

    apply = commands.add_parser("apply-manifest", help="verify and apply the ordered live-futures manifest")
    _cluster_arguments(apply)
    apply.add_argument("--manifest", required=True, type=Path)
    apply.add_argument("--repo", action="append", required=True, type=_repository)

    roles = commands.add_parser("verify-roles", help="run positive and negative role probes with rollback")
    _cluster_arguments(roles)
    roles.add_argument("--contract", required=True, type=Path)

    cleanup = commands.add_parser("cleanup", help="reject active sessions, stop PostgreSQL, and delete the exact root")
    _cluster_arguments(cleanup)

    verify = commands.add_parser("validate-manifest", help="validate ordering, source SHAs, and file hashes without a database")
    verify.add_argument("--manifest", required=True, type=Path)
    verify.add_argument("--repo", action="append", required=True, type=_repository)

    evidence = commands.add_parser("write-evidence", help="validate and write canonical secret-free evidence")
    evidence.add_argument("--input", required=True, type=Path)
    evidence.add_argument("--output", required=True, type=Path)

    input_lock = commands.add_parser(
        "validate-input-lock",
        help="verify every later-lane input by exact path and SHA-256",
    )
    input_lock.add_argument("--input-lock", required=True, type=Path)
    return parser


def _repositories(items):
    repositories = dict(items)
    if len(repositories) != len(items):
        raise SafetyError("each repository may be supplied only once")
    return repositories


def execute(options):
    if options.command == "validate-manifest":
        manifest = load_manifest(options.manifest)
        entries = verify_manifest_sources(manifest, _repositories(options.repo))
        return {"manifest": manifest.schema_version, "entries_verified": len(entries)}
    if options.command == "write-evidence":
        try:
            value = json.loads(options.input.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise EvidenceError(f"cannot load evidence input: {error}") from error
        write_evidence(options.output, value)
        return {"evidence": "written"}
    if options.command == "validate-input-lock":
        input_lock = load_input_lock(options.input_lock)
        return {
            "input_lock": input_lock.schema_version,
            "entries_verified": len(input_lock.entries),
            "kinds": sorted(entry.kind for entry in input_lock.entries),
        }

    cluster = RehearsalCluster(options.root, options.pg_bin)
    if options.command == "init":
        cluster.initialize()
        return {
            "cluster": "initialized",
            "root_fingerprint": cluster.root_fingerprint(),
            "databases": cluster.database_names(),
        }
    if options.command == "restore":
        cluster.restore_archive(options.database, options.archive, options.archive_sha256)
        return {"database": options.database, "archive_sha256": options.archive_sha256, "outcome": "restored"}
    if options.command == "apply-manifest":
        manifest = load_manifest(options.manifest)
        return {"migration_results": cluster.apply_manifest(manifest, _repositories(options.repo))}
    if options.command == "verify-roles":
        return {"role_results": cluster.verify_role_contract(load_role_contract(options.contract))}
    if options.command == "cleanup":
        fingerprint = cluster.root_fingerprint()
        cluster.cleanup()
        return {"root_fingerprint": fingerprint, "outcome": "deleted"}
    raise SafetyError("unknown rehearsal command")


def main(argv=None):
    parser = build_parser()
    try:
        result = execute(parser.parse_args(argv))
    except (SafetyError, ManifestError, RoleContractError, EvidenceError, InputLockError) as error:
        parser.exit(2, f"refused: {error}\n")
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
