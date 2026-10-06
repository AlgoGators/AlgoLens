# Readiness lane final report — 2026-10-06

Base: `0f636c24ca5c7b6763f16bfb04f15bfebe7ac8a4`. The four interrupted
readiness edits were preserved and finished. Integration compatibility was
checked against role/database commit `7f4831e6` (successor of `b849e4a8`).
No production connection, remote write, deployment, registry promotion, or
production credentials were used by this lane.

## Completed behavior

- `evaluate_runtime_readiness` now supplies actual schema, role, capability and
  worker callbacks to both `/ready` and the CLI. All database callbacks execute
  in the existing read-only transaction and retain rollback/close cleanup.
- Role attestation covers roles/memberships, database/schema/relation/column/type
  and default ACLs, RLS, function ownership/security/search paths and triggers.
  Schema attestation uses role-independent PostgreSQL catalogs and appends the
  role-policy digest, matching the integrated rehearsal harness wire format.
  Query text parity was independently checked after normalization of the
  result-column alias and whitespace.
- Capability readiness requires installed, fully classified route policy plus
  the exact four approved launch identities, four active grants, three active
  approver mappings and the retired-personal-account replacement mapping.
- Worker readiness requires the dispatch schema/functions, a visible session
  for `qt_worker` / `qt_desk_worker`, no unfinished job older than five minutes,
  no expired running lease, and the pinned release worker contract digest.
- CLI `--rehearsal-root` explicitly selects only `qt_rehearsal_migrated` using
  the private `/dev/shm/algolens-qt-rehearsal.*` socket and `qt_algolens_api`.
  Root/socket ownership and private modes are checked at connection time;
  service/password-file/network fallback is excluded. Rehearsal composition
  retains production JWT/CORS/capability controls. Production remains fixed
  to `new_algo_data`; setting `FLASK_ENV=rehearsal` alone cannot select rehearsal.
- Added a non-deploying exact-commit CI job and synthetic Compose smoke under
  `deployment/qt_container_smoke/`. The driver uses `git archive` at the exact
  HEAD SHA, builds the production backend Dockerfile, verifies its revision
  label and executed image ID, mounts a synthetic closed ELF bundle read-only,
  and exercises real sealed evaluator transport with no container network.
  There is no privileged mode or seccomp/AppArmor bypass. Host isolation
  incompatibility is a hard failure. The synthetic fixture is explicitly not
  financial-evaluator or production-readiness proof.

## Verification

- System Python 3.12 isolated environment, final backend run:
  `python -m pytest tests --ignore=tests/integration -q` — **2,231 passed**.
  Existing JWT test-key length and SQLite adapter deprecation warnings remain.
- Final deployment run:
  `python -m unittest deployment.test_release deployment.test_runtime_compose deployment.qt_container_smoke.test_fixture deployment.qt_container_smoke.test_contract -q`
  — **20 passed**.
- The native fixture test compiled a real ELF engine/evaluator, staged and
  verified the closed dynamic dependency bundle, executed through the actual
  sealed-memory/user-network-namespace transport, and rejected library-byte
  tampering. It used synthetic data only.
- `git diff --check` passed.
- Docker is not installed on this host. **Actual Docker image/Compose/mount
  execution was not performed locally.** The new CI job is the remaining gate.
- The coordinator reported PostgreSQL 16 runtime/admin digest parity verified
  in integration commit `7f4831e6`. A redundant synthetic cluster check in this
  lane did not execute because automatic permission review timed out; no
  PostgreSQL execution from that attempt is claimed.

## Integration dependencies and limits

- Consume the integrated role postlude's narrow API column SELECT grant on
  dispatch-job `state`, `first_seen_at`, `lease_expires_at` (in `7f4831e6`).
- Consume the worker lane's agreed session `application_name=qt_desk_worker`
  fix before running the combined readiness gate. An active visible session
  proves presence, not independent executable-byte identity; exact worker
  installation remains a release/worker-host evidence requirement.
- Runtime identity verifies database, role and server address. It does not
  independently query privileged `data_directory`. The unchanged rehearsal
  mutation harness verifies that setting, and the reviewed manifest remains
  hash-bound. No broad settings/statistics role was granted for readiness.
- Real pinned trade-ngin evaluator financial semantics, actual worker session,
  production-shaped migrated database readiness and Docker runtime behavior
  remain coordinator/CI acceptance checks. This report is not a production
  activation claim.

## Independent-review repair — follow-up to integration `62281057`

Both reviewed gaps were reproduced before implementation using the TDD skill
and real PostgreSQL16 synthetic data. The first red run produced seven failures
across five cases: duplicate active normalized email with a different role,
authority transferred to a retired lookalike, duplicate grant replacing a
missing expected grant, login requiring DB_PASSWORD, and three hostile libpq
environment cases. No production database or external network target was used.

The launch authority query now resolves active normalized email uniqueness
independently of role, then binds role/grant/mapping checks to the resolved
user IDs. Exact grant/mapping counts plus existence of every expected ID-bound
entry reject extras, missing entries and compensating duplicates. Retired
same-email history without active authority remains allowed, matching login.

`algolens/infrastructure/db/rehearsal.py` provides an immutable
`RehearsalDatabase(root)` connection boundary. The explicit app factory argument
binds it in the application's extensions; the existing shared
`get_db_connection()` dispatches to it for every authenticated HTTP and default
repository call. The readiness wrapper uses the same implementation. No global
connection factory or process-environment mutation is used. Unbound rehearsal
contexts fail closed. Production connection arguments remain unchanged.

Connections validate the private root/socket ownership and modes, reject
nonempty inherited `PG*` environment configuration before libpq invocation,
select the exact socket/database/API role, and verify the connected database,
role and null server address before handing back a connection. No password or
password-file lookup is needed (`passfile=/dev/null`). Explicit `service=''`
was removed: the real PostgreSQL regression showed libpq treats it as an empty
named service and refuses the connection. Omitting it is safe only alongside
the explicit rejection of inherited PGSERVICE and related libpq environment.

Final repair verification:

- **9 synthetic PostgreSQL16 tests passed**, covering actual login/session
  verification without DB_PASSWORD, default QT repository connection under
  hostile DB_* values, exact identity/grant/mapping cases, and pre-connect
  refusal of PGHOSTADDR, PGSERVICE, PGOPTIONS for the shared boundary.
  The private cluster was stopped and removed by the fixture cleanup; absence
  was asserted. libpq emits its harmless `/dev/null is not a plain file`
  warning; no credentials were loaded.
- **20 deployment/native bundle tests passed**.
- Full unfiltered `python -m pytest -q`: **2,231 passed, 312 skipped,
  36 setup errors**. All 36 are pre-existing missing-ALGOLENS_TEST_DB setup
  errors in `tests/integration/test_configuration_inspection_read.py` and
  `tests/integration/test_configuration_inspection_v2_read.py`. A full synthetic
  backend run belongs to the coordinator and was not substituted with a green
  unit-only claim. Existing test-key and SQLite deprecation warnings remain.
- `git diff --check` passed. Docker remains absent and untested locally.

The 36 setup errors cover these test names (parameterized variants included):
`test_actual_sql_reads_valid_system_publication_not_newer_qt_or_parent`,
`test_newest_invalid_metadata_is_not_replaced_by_older_valid`,
`test_membership_fallback_is_only_for_successful_empty_query`,
`test_controlled_attempt_and_intent_are_required`,
`test_missing_stream_or_runtime_schema_is_storage_unavailable`,
`test_date_mismatch_and_changed_registry_revision`,
`test_system_result_date_column_is_timezone_independent`,
`test_large_reserved_child_is_rejected_without_returning_its_text`,
`test_producer_unavailable_keeps_bound_envelope_and_null_stages`,
`test_absent_publication_stays_unavailable_without_book_fallback`,
`test_malformed_unavailable_reason_is_200_through_sql_and_http`,
`test_repeatable_read_keeps_the_first_database_snapshot`,
`test_v2_independent_early_capture_and_consumption_survive_sql_http`,
`test_malformed_newest_v2_child_refuses_without_older_fallback`,
`test_v1_v2_consumption_contamination_refuses_through_http`,
`test_controlled_sidecar_mismatch_refuses_v2_through_http`,
`test_decimal8_strings_and_large_finite_number_survive_jsonb_http`,
`test_jsonb_child_text_cap_refuses_legal_compact_fit`, and
`test_v2_publication_requires_authentication_and_current_internal_role`.

### Production attestation is still an independent hard gate

The current schema/role digest intentionally includes all non-system schemas,
all qt_* roles, ownership, ACLs and security settings. Clone omissions and
owner/administrator normalization can therefore change it. Inspection of
`deployment/release.py` confirms the release compares directly against the
operator-supplied expected manifest; it does not derive a production expectation
from a clone. `deployment/ROLLOUT.md` now explicitly requires separate
environment-specific manifests and an independently reviewed production final
catalog expectation from a faithful rehearsal or audited baseline/ledger
transformation. Copying a clone digest into a renamed production manifest,
ignoring mismatches or accepting an unreviewed observed digest is prohibited.
That production expectation remains unresolved; these repairs do not satisfy
or weaken that gate and do not add runtime privileges.
