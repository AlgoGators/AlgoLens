# QT production database rehearsal

This runbook proves a production candidate against a disposable PostgreSQL 16 cluster without connecting the candidate tooling to production. The current automated proof uses synthetic local data only. A later authorized lane may create a fresh, read-only production extract; it must pass the same hashes and identity checks before it is admitted.

## Safety boundary

The rehearsal cluster is a mode-`0700` directory whose exact name matches `/dev/shm/algolens-qt-rehearsal.XXXXXX`. PostgreSQL listens only on its private Unix socket (`listen_addresses=''`); host authentication is rejected. The harness uses an explicit non-`postgres` administrator and a minimal environment, so ambient `PGHOST`, `PGDATABASE`, credentials, and TCP fallback cannot choose a target.

Only these databases are permitted:

- `qt_rehearsal_baseline`
- `qt_rehearsal_migrated`
- `qt_rehearsal_destructive_tests`

Every mutation is bracketed by a database identity guard that checks the database name, Unix-socket connection, exact `data_directory`, and exact administrator role. SQL that can create/drop databases, alter the server, execute programs, use external-access extensions, or name `new_algo_data` is refused. Restore is rendered by `pg_restore` and piped into an identity-guarded transaction; `--create`, `--clean`, `-C`, ownership, and archive privileges are not accepted.

This harness never reads production, creates production credentials, deploys services, or changes production configuration. A successful synthetic run proves the harness and candidate mechanics—not that live data has already passed the later rehearsal.

## Synthetic scratch proof

Use the bundled PostgreSQL 16 `bin` directory as `PG_BIN`. The integration test creates its own exact private root, exercises dump/restore, ordered migrations, schema digests, role grants and denials, active-session cleanup refusal, then deletes the root:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest \
  deployment.qt_rehearsal.tests.test_postgres_integration -v
```

Some managed sandboxes forbid Unix-socket creation under `/dev/shm`; in that case run the same local-only test with permission to bind an AF_UNIX socket. The test does not use the network or external services.

For a manual run:

```sh
ROOT="$(mktemp -d /dev/shm/algolens-qt-rehearsal.XXXXXXXX)"
chmod 0700 "$ROOT"
python3 -m deployment.qt_rehearsal init --root "$ROOT" --pg-bin "$PG_BIN"
```

Do not rename or reuse the root. Initialization refuses pre-existing database state and creates exactly the three databases above.

## Locked inputs

The later data-backed lane must first validate an input lock:

```sh
python3 -m deployment.qt_rehearsal validate-input-lock --input-lock /approved/run/input-lock.json
```

The `qt-rehearsal-input-lock/v1` document contains exactly one relative, non-symlink file and SHA-256 for each kind: `migration_manifest`, `artifact_manifest`, `config_snapshot`, `role_contract`, and `data_bundle`. The config snapshot is secret-scanned. No path is inferred and no filename glob determines what runs.

The coordinator-created data bundle must describe a fresh authorized, read-only copy of the full `auth` and `trading` schemas, plus only `futures_data.ohlcv_1d` rows in the inclusive UTC window `T-730` through `T-1` and every matching `metadata.contract_metadata` row. It must record the extraction date, inclusive bounds, artifact hashes, and row counts. No extract or dump belongs in Git. This repository intentionally does not contain production access code; the later authorized coordinator supplies the already-created, hash-pinned artifacts.

Restore each approved custom archive by exact hash:

```sh
python3 -m deployment.qt_rehearsal restore \
  --root "$ROOT" --pg-bin "$PG_BIN" \
  --database qt_rehearsal_baseline \
  --archive /approved/run/baseline.dump \
  --archive-sha256 SHA256
```

Repeat for `qt_rehearsal_migrated`. Archives containing database creation metadata are refused.

## Migration manifest

`qt-rehearsal-migration-manifest/v1` is an explicit ordered list. Every entry pins:

- stable ID, repository (`algolens` or `trade-ngin`), full 40-hex Git commit, relative SQL path, and file SHA-256;
- dependencies that must appear earlier in the list;
- a structured `always`, `table_absent`, or `column_absent` predicate;
- rollback policy and the expected post-entry schema digest.

The worktree bytes and committed bytes must both equal the pinned hash. Symlinks, dirty migration bytes, guessed filename order, missing repositories, and commit drift are refused. The `live-futures` profile targets only `qt_rehearsal_migrated` and excludes migration 002 and investor, equity, and incubating paths. The `destructive-fixture` profile targets only `qt_rehearsal_destructive_tests`, where the broader supported-migration matrix can be exercised safely.

Validate, then apply:

```sh
python3 -m deployment.qt_rehearsal validate-manifest \
  --manifest /approved/run/migrations.json \
  --repo algolens=/exact/algolens \
  --repo trade-ngin=/exact/trade-ngin

python3 -m deployment.qt_rehearsal apply-manifest \
  --root "$ROOT" --pg-bin "$PG_BIN" \
  --manifest /approved/run/migrations.json \
  --repo algolens=/exact/algolens \
  --repo trade-ngin=/exact/trade-ngin
```

## Least-privilege proof and evidence

The role contract defines `schema_owner`, `migrator`, `algolens_api`, `system_publisher`, and `qt_worker`. It must include allowed probes and SQLSTATE-`42501` denial probes for each runtime role; owner access is denied by default. Each probe uses `SET LOCAL ROLE` inside a transaction that is rolled back.

```sh
python3 -m deployment.qt_rehearsal verify-roles \
  --root "$ROOT" --pg-bin "$PG_BIN" \
  --contract /approved/run/roles.json
```

Evidence uses `qt-rehearsal-evidence/v1` and permits only versions, digests, counts, schema fingerprints, role results, and test reports. Keys or values resembling secrets, credentials, DSNs, hosts, sockets, raw SQL/data, or private temporary paths are refused. Canonical output is written mode `0600`:

```sh
python3 -m deployment.qt_rehearsal write-evidence \
  --input /approved/run/evidence-input.json \
  --output /approved/run/evidence.json
```

## Mandatory cleanup

Cleanup refuses to continue while any session is active in a rehearsal database. After all clients exit, it stops PostgreSQL, proves the socket is gone, revalidates realpath/owner/mode, removes only the exact root, and verifies that root no longer exists:

```sh
python3 -m deployment.qt_rehearsal cleanup --root "$ROOT" --pg-bin "$PG_BIN"
test ! -e "$ROOT"
```

If cleanup refuses, do not bypass the guard. Identify and close the listed local client, then rerun the same command. Never manually point this tooling at a production directory or database.
