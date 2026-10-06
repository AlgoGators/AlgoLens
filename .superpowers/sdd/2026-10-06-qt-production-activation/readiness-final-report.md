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
