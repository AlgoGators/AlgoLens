# QT Production Activation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the internal QT exact-position workflow production-compatible with the verified state of PostgreSQL database `new_algo_data`, prove it first on an isolated production-shaped copy, and activate only the lifecycle=`live` `trendfollowing` / `CONSERVATIVE_PORTFOLIO` book after a fresh human approval.

**Architecture:** Preserve the existing AlgoLens workflow and trade-ngin transactional processor. Add a centralized capability boundary, a separate immediate QT dispatcher with durable leases and first-day bootstrap, a closed immutable evaluator/release artifact chain, fail-closed production readiness checks, and a hash-pinned cross-repository migration/rehearsal harness. The System publisher remains a separate 09:30 ET service. No broker, email, public, or investor side effect is allowed.

**Tech Stack:** Flask/Python/PostgreSQL, React/TypeScript/Vitest, C++20/CMake/CTest, PostgreSQL 16, Docker Compose, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-06-qt-production-activation.md`

---

## Current verdict

The branch cannot safely be pointed at `new_algo_data` today. The production database has no QT workflow tables, runtime services use a superuser, AlgoLens does not mount the evaluator bundle, and trade-ngin has no resident worker that discovers and processes confirmed decisions. This plan closes those gaps without rewriting the already implemented processor.

## Global constraints

- `new_algo_data` is production. No test, migration rehearsal, role experiment, or destructive check may run against it.
- No production database mutation, deploy, credential/grant change, branch push, or merge to a shared remote occurs without fresh explicit approval from John Riley.
- Rehearsal databases are never named `new_algo_data`; every mutating rehearsal command first proves database name, socket, and private data directory.
- Production activation includes only the active lifecycle=`live` registry/book scope `trendfollowing` / `LIVE_TREND_FOLLOWING` / `CONSERVATIVE_PORTFOLIO`.
- `trade-ngin` migration `002_backfill_qt_from_system.sql` is never applied. There is no historical QT backfill.
- The dashboard remains System/Model by default. QT is an explicitly selected internal workflow.
- Investor/public publication, email, broker orders, and external delivery are disabled and tested as absent.
- A clean decision becomes eligible immediately after confirmation. A breached decision becomes eligible only after two distinct authorized approvers, neither of whom is the submitter.
- John Riley is the submitter. Hemdutt Rao, Xander Robbins, and Dominick Dupuy are the approval pool. Hemdutt remains approval-only. Eric stays retired except for immutable historical evidence.
- The System publisher retains its current trigger and 09:30 ET schedule. The QT worker is a separate process, credential, lock, and health boundary.
- Current AlgoLens dirty work must be preserved before any parallel writer begins. `graphify-out/`, logs, cache files, secrets, database dumps, and copied production data are never committed.
- The coordinator alone owns the shared plan, task state, cross-repository migration manifest, worktree integration, production commands, and final evidence ledger.

## Stable cross-lane contracts

### Artifact contract

The release lane produces an immutable `release-artifacts/v1` manifest containing:

- full and short trade-ngin Git SHA;
- compiler/toolchain and canonical Release-build inputs;
- immutable image digest;
- `evaluator_build`, evaluator executable SHA-256, and canonical evaluator bundle SHA-256;
- SHA-256 for `libtrade_ngin.so`, the three System publisher binaries, `qt_desk_prepare_sources`, `qt_desk_run`, and the new `qt_desk_worker`.

AlgoLens and the database policy consume these exact values. Unknown, local, synthetic, or mutable `latest` identities fail closed.

### Database identity contract

Every mutating database tool requires expected values and verifies them in the same session:

```sql
SELECT current_database(),
       COALESCE(inet_server_addr()::text, 'socket'),
       current_setting('data_directory'),
       current_user;
```

The rehearsal expects its unique database, private socket, private data directory, and rehearsal role. Production expects database `new_algo_data`, the approved production endpoint, and the named least-privilege role. A mismatch stops before mutation.

### Worker contract

The worker consumes immutable `confirmed_decision` rows and a durable dispatcher job record. It reuses stable attempt/input/market/finalization identifiers across retries, invokes the existing one-shot source/processor tools, and treats `qt_desk_receipts` as processor-owned immutable evidence. Dispatcher retries and dead letters live in separate tables; they never pre-create a failed processor receipt.

### Authorization contract

Roles grant only broad application visibility. QT actions additionally require current database grants and one canonical active person mapping. Unknown identities and resolver failures have no authority. Backend enforcement is authoritative; frontend capability checks only control presentation.

## Dependency graph and scheduling

| Phase | Ready work | Unlocks |
|---|---|---|
| 0 | T0 baseline freeze | all isolated writer lanes |
| 1 | T1 authorization, T2 release artifacts, T3 rehearsal harness, T4 dispatcher/worker | T5 runtime completion and T6 integration |
| 2 | T5 AlgoLens runtime, T6 coordinator integration | T7 isolated rehearsal |
| 3 | T7 rehearsal | T8 security, T9 integration, T10 release reviews |
| 4 | T8–T10 independent reviews | T11 remote merge/deploy approval gate |
| 5 | T11 approved normal-branch/CI gate | T12 production activation |
| 6 | T12 production activation | T13 completion evidence |

T1–T4 use isolated Git worktrees and disjoint ownership. T5 may start its non-dependent portions in parallel, but it cannot be accepted until it consumes the final artifact and database contracts. T7 and all production work are intentionally serialized.

---

### T0: Freeze the reviewed baseline and provision isolated worktrees

- depends_on: []
- owns: current AlgoLens continuation worktree, coordinator ledger, local worktree creation
- non_goals: remote push, shared-branch merge, production access, implementation changes
- consumes: current dirty AlgoLens worktree and trade-ngin continuation branch
- produces: auditable local AlgoLens baseline commit, exact source SHAs, clean isolated worktrees/branches for every writer
- acceptance: relevant source/tests/migrations/spec/plan are preserved; caches/logs/dumps/secrets are excluded; focused/full baseline verification is recorded; every writer gets an absolute path and exclusive ownership
- verification: `git status --short`, `git diff --check`, recorded test outputs, and `git worktree list --porcelain`
- estimate: M
- coordination_risk: moderate
- status: complete

**Files:**

- Include: existing modified AlgoLens source, tests, migrations 003/009, this specification, this plan, and the reviewed handoff.
- Exclude: `graphify-out/`, `logs/`, `__pycache__/`, build trees, database dumps/extracts, `.env*`, and credentials.

- [x] Inventory every modified/untracked path and classify it as source evidence, generated output, secret, or unrelated user work.
- [x] Run `git diff --check` and the focused QT/auth tests before snapshotting.
- [x] Run AlgoLens baseline verification:

```bash
cd algolens-api && python -m pytest tests -q
cd ../algolens-frontend && npm test && npm run typecheck && npm run build
```

- [x] Create one local-only baseline commit containing only the reviewed relevant paths. Recorded SHA: `98a16eb72a79f3fcafa2ba223e6ba2b6bfe52157`. Nothing was pushed.
- [x] Record trade-ngin candidate full SHA (`a982e429aa33ba97f8c7ec9c462ed962f1233729`) and confirm its worktree is clean except known generated caches.
- [x] Create isolated branches/worktrees for `qt-prod-auth`, `qt-prod-runtime`, `qt-prod-rehearsal`, `qt-prod-worker`, and `qt-prod-release` from the recorded baselines.
- [x] Give each task its absolute worktree path, branch, owned paths, acceptance checks, prohibited side effects, and structured return format.

### T1: Implement internal capability authorization and self-approval prevention

- depends_on: [T0]
- owns: AlgoLens capability domain/decorators, route classifications, `/auth/verify` capability response, frontend capability gates, migration 009 identity enrollment, migration 010 self-approval guard, corresponding tests
- non_goals: investor/public routes, portfolio scope for external users, deployment/readiness code, database application, production grants
- consumes: approved identity predicates for John Riley, Hemdutt Rao, Xander Robbins, Dominick Dupuy; current QT action grants
- produces: default-deny internal capability system and database-enforced submitter exclusion
- acceptance: all 42 current Flask routes are explicitly open, disabled, or capability-protected; `/auth/verify` returns resolved role/capabilities; frontend uses `can(capability)`; unknown identities fail closed; submitter cannot approve through HTTP, service, or direct SQL
- verification: focused backend/frontend tests plus scratch-PostgreSQL migration tests and route-walk matrix
- estimate: L
- coordination_risk: moderate
- status: running

**Owned files:**

- Create: `algolens-api/algolens/domain/identity/capabilities.py`
- Create: `algolens-api/algolens/adapters/http/capability_guard.py`
- Modify: `algolens-api/algolens/adapters/http/auth.py`
- Modify: `algolens-api/algolens/adapters/http/portfolio.py`
- Modify: `algolens-api/algolens/adapters/http/qt_workflow.py`
- Modify: other final route modules only to declare a policy
- Modify: `algolens-api/algolens/application/portfolio/qt_workflow.py`
- Modify: `algolens-api/algolens/application/portfolio/qt_decision_read.py`
- Modify: `algolens-api/algolens/infrastructure/portfolio/qt_authorization.py`
- Modify: `algolens-api/migrations/009_hemdutt_qt_approver.sql`
- Create: `algolens-api/migrations/010_qt_submitter_approval_guard.sql`
- Modify/Create: focused unit, HTTP, route-walk, and PostgreSQL migration tests
- Modify: `algolens-frontend/src/domain/identity/user.ts` and capability-consuming components/tests

- [ ] First add tests proving unknown routes/roles fail closed, the route map has no unclassified rule, and UI visibility is derived from returned capabilities.
- [ ] Define the internal vocabulary: `view_internal`, `view_qt_platform`, `edit_qt_book`, `approve_qt_override`, `manage_incubation`, `manage_books`, `request_runtime_control`, `approve_runtime_control`, and `publish_qt_book`. Reserve `save_analysis` and `view_investor_book` without enabling deferred external scope.
- [ ] Resolve role bundles independently of Flask, then intersect QT action capabilities with active `qt_action_grants` and exactly one active canonical person mapping.
- [ ] Return sorted capabilities from `/auth/verify`; never trust client-claimed role/capabilities.
- [ ] Replace role literals and `isInternalRole` checks on in-scope internal routes/components with capability checks.
- [ ] Correct `dominick_dupuoy`/`dupuoy` to the approved Dominick Dupuy identity through an additive, history-preserving mapping rule. Resolve production users by a unique verified identity predicate, never remembered numeric IDs.
- [ ] Enroll John as the sole initial submitter and Hemdutt/Xander/Dominick as approval-only identities; revoke unintended active mappings/grants without deleting immutable history.
- [ ] Reject `decision.created_by` in read-model `can_approve`, service `approve_override`, and a PostgreSQL `BEFORE INSERT` trigger.
- [ ] Run:

```bash
cd algolens-api
python -m pytest tests/test_qt_a7_approval.py tests/test_qt_http.py tests/test_qt_read_service.py -q
ALGOLENS_TEST_DB="$REHEARSAL_DESTRUCTIVE_DSN" python -m pytest tests/integration/test_migration_009_hemdutt_approver.py tests/integration/test_qt_a7_approval_postgres.py -q
cd ../algolens-frontend
npm test -- src/domain/identity src/components/QtProposalWorkspace.test.tsx
npm run typecheck
```

### T2: Produce one immutable trade-ngin Release artifact chain

- depends_on: [T0]
- owns: trade-ngin build identity, portable test artifact paths, evaluator bundle packaging, artifact manifest, relevant CI/image/deploy identity checks
- non_goals: QT worker behavior, migrations/grants, lifecycle selection, email/broker behavior, changing the existing production trigger
- consumes: exact approved trade-ngin source SHA
- produces: canonical Release build and closed `release-artifacts/v1` manifest used by T4/T5/T7
- acceptance: no absolute developer build paths; one tested build feeds packaging; unknown/local identities fail; timestamp/short-SHA/latest tags resolve to one digest; installed bytes re-hash to the manifest
- verification: bundle admission tests, clean Release build, CTest, manifest schema/hash validation, image smoke and digest assertions
- estimate: L
- coordination_risk: moderate
- status: running

**Owned files:**

- Modify: `CMakeLists.txt`, `apps/tools/CMakeLists.txt`
- Modify: `apps/tools/qt_evaluator_bundle.py`, `apps/tools/qt_evaluator_manifest.json`
- Modify: `tests/contracts/qt_native_bundle_fixture.py` and affected QT contract tests
- Modify: `.github/workflows/ci-cd-pipeline.yml`, `Dockerfile`
- Create: focused artifact-manifest generator/schema/tests under `apps/tools/` and `tests/contracts/`
- Do not edit: QT processor/worker logic, migrations, live portfolio schedule

- [ ] Replace fixed `/home/devcontainers/qt-validation-20260921/bin/Debug` references with `TRADE_NGIN_TEST_BUILD_DIR` and `TRADE_NGIN_TEST_ARTIFACT_DIR`.
- [ ] Make `evaluator_build` derive from the exact reviewed source/build and reject `unknown`, `local-*`, and dirty/synthetic identities for release mode.
- [ ] Build once from the exact SHA and package/test those same bytes; remove source mutation from the image build.
- [ ] Pin mutable build inputs or record immutable digests sufficient to reproduce/audit them.
- [ ] Generate the artifact manifest defined above and validate every file by size and SHA-256.
- [ ] Preserve the existing push-to-`prod` trigger, but fail before deploy unless all image tags have the same digest and fail after deploy unless the running container uses that digest.
- [ ] Run:

```bash
cmake -S . -B build/qt-prod -DCMAKE_BUILD_TYPE=Release -DNLopt_DIR=/usr/lib/x86_64-linux-gnu/cmake/nlopt
cmake --build build/qt-prod --parallel
ctest --test-dir build/qt-prod --output-on-failure
cd tests/contracts
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest -v test_qt_evaluator_bundle.py test_qt_built_bundle.py
```

### T3: Build the isolated database rehearsal and migration ledger harness

- depends_on: [T0]
- owns: rehearsal orchestration, restore/extract/cleanup checks, migration ledger generation/verification, least-privilege role test harness, sanitized evidence format
- non_goals: editing feature migrations owned by T1/T4, touching production, storing secrets/data in Git, deploying services
- consumes: production schema-only facts, fresh authorized read-only extract at rehearsal time, exact migration bytes from T1/T4, exact config with secrets removed
- produces: repeatable private PostgreSQL 16 rehearsal and hash-pinned candidate manifest
- acceptance: socket-only private cluster; separate baseline/migrated/destructive databases; identity check before every mutation; no network fallback; role positive/negative tests; cleanup proves all copied data and sockets are gone
- verification: unit tests for refusal/cleanup plus a full scratch run using the bundled PostgreSQL 16 toolchain
- estimate: L
- coordination_risk: high
- status: complete

**Owned files:**

- Create: `deployment/qt_rehearsal/` Python/shell tooling and tests
- Create: `docs/operations/qt-production-rehearsal.md`
- Create: generated-but-not-secret manifest/evidence schema under `deployment/qt_rehearsal/schemas/`
- Do not edit: feature migration SQL, application source, production Compose, credentials

- [ ] Create a mode-0700 cluster under `/dev/shm/algolens-qt-rehearsal.XXXXXX` with `listen_addresses=''` and host connections rejected.
- [ ] Create only `qt_rehearsal_baseline`, `qt_rehearsal_migrated`, and `qt_rehearsal_destructive_tests`.
- [ ] Restore a fresh full `auth` + `trading` backup and a read-only extract of `futures_data.ohlcv_1d` for the exact inclusive `T-730` through `T-1` window plus all matching `metadata.contract_metadata` rows.
- [ ] Never use `--create`, `--clean`, or `-C`; restore only into the identity-verified target.
- [ ] Generate an ordered manifest with path, repository, full Git SHA, SHA-256, dependency, apply predicate, rollback policy, and expected schema digest. Do not infer order from filenames.
- [ ] Begin from verified prerequisites, then admit only migrations required by the one live futures book. Explicitly exclude trade migration 002, investor/public paths, and unneeded equity/incubating paths from the production manifest; exercise all supported migration files only in the destructive fixture matrix.
- [ ] Define four access domains: schema owner plus ephemeral migrator, AlgoLens API, System publisher, and QT worker. Test allowed operations and cross-role denials with `SET ROLE`.
- [ ] Capture sanitized evidence only: versions, digests, row counts, schema fingerprints, role matrix, and test reports.
- [ ] Stop the cluster, reject active sessions, validate realpath/owner/mode, delete the exact rehearsal root, and prove no socket, dump, extract, database, or temporary path remains.

### T4: Add durable immediate QT dispatch, first-day bootstrap, and separate worker

- depends_on: [T0]
- owns: trade-ngin migrations 029–030, dispatcher library/executable, first-day bootstrap, worker service command/health, focused tests
- non_goals: rewriting the transactional processor, modifying System publisher scheduling, AlgoLens UI/API, public/investor publication, email, broker orders, production activation
- consumes: existing `qt_desk_prepare_sources`, `qt_desk_run`, processor receipts, fixed live book scope, T2 artifact interface
- produces: resident least-privilege worker with claim/lease/retry/restart semantics and audited first-day anchor
- acceptance: two workers cannot claim one decision; stable IDs survive every crash boundary; first day is one-time/replay-identical; wrong scope never claims; success creates one processed receipt; failures use dispatcher ledger; service is isolated from System publisher
- verification: native/unit child-process tests, two-connection PostgreSQL races, first-day/continuation/restart matrix, image health smoke
- estimate: L
- coordination_risk: high
- status: running

**Owned files:**

- Create: `migrations/029_qt_desk_dispatch_jobs.sql` and rollback/test files
- Create: `migrations/030_qt_first_day_bootstrap.sql` only if the reviewed bootstrap contract requires schema; otherwise keep bootstrap in focused source/tooling
- Create: `include/trade_ngin/.../qt_desk_dispatcher.hpp`, `src/.../qt_desk_dispatcher.cpp`
- Create: `apps/tools/qt_desk_worker.cpp` and a focused worker start script
- Create: `apps/tools/qt_desk_worker.cmake` containing the worker target definition; T6 alone adds the one-line include to the T2-owned central `apps/tools/CMakeLists.txt`
- Create: focused unit/integration tests and fixtures
- Do not edit: `live_portfolio.cron`, `scripts/run_live_portfolio.sh`, existing processor semantics

- [ ] Add a durable job table unique per decision and append-only attempt table. Store stable attempt/input/market/finalization IDs, state, owner token, lease, next-attempt time, and secret-free error code.
- [ ] Claim with `FOR UPDATE SKIP LOCKED`; allow only expired leases to be reclaimed; make succeeded/dead-letter terminal.
- [ ] Discover only active lifecycle=`live`, registry `trendfollowing`, strategy `LIVE_TREND_FOLLOWING`, book `CONSERVATIVE_PORTFOLIO`, status `confirmed_decision`.
- [ ] Design the first-day futures anchor as a narrow one-time operation from a fresh approved System publication. Refuse existing conflicting/partial QT facts; never bulk backfill history.
- [ ] Reuse stable IDs when preparation partially commits, when the worker dies before/after processor commit, and on exact replay.
- [ ] Use default poll interval 1 second; alert evidence begins at queue age 5 minutes. Adopt reviewed bounded retry defaults before merge (candidate: 8 attempts with 1/2/5/10/30/60/120/300-second delays).
- [ ] Classify deterministic refusals as dead letter and transient database/process failures as retryable. Never insert a failed `qt_desk_receipts` row.
- [ ] Accept the local-socket DSN only through a bounded regular-file descriptor; use absolute pinned tool paths; log no credentials.
- [ ] Add `--healthcheck`; package the worker as a separate service with its own restart/health policy and no broker/email/public environment.
- [ ] Prove `live_portfolio.cron` and `scripts/run_live_portfolio.sh` are byte-unchanged.

### T5: Wire AlgoLens production runtime to pinned artifacts and exact database identity

- depends_on: [T0, T1, T2, T3]
- owns: AlgoLens Docker/Compose/runtime configuration, production readiness checks, release evidence, rollout documentation/tests
- non_goals: migration SQL, authorization semantics, worker scheduling, production writes, changing trade-ngin trigger
- consumes: T2 artifact manifest and bundle; T3 schema/role/database identity manifest; capability hook supplied by T1
- produces: candidate-container preflight and installed-readiness proof that refuse wrong DB/schema/role/book/artifact/config
- acceptance: evaluator bundle mounted read-only with `create_host_path:false`; production flags fail closed; readiness proves exact database, limited role, schema digest, live-book policy, bundle pins, and no-side-effect evaluator launch; release evidence binds built and running image IDs
- verification: container/config unit tests, candidate-container preflight, post-start endpoint/identity tests
- estimate: L
- coordination_risk: moderate
- status: running

**Owned files:**

- Modify: `docker-compose.prod.yml`
- Modify: `algolens-api/Dockerfile`
- Modify: `algolens-api/algolens/infrastructure/config/app_factory.py`
- Create: focused production-readiness module/CLI and tests
- Modify: `deployment/release.py`, `.github/workflows/deploy.yml`, `deployment/ROLLOUT.md`
- Do not edit: migration SQL, QT authorization/service semantics, trade-ngin source

- [ ] Add required production configuration: `FLASK_ENV=production`, `FLASK_DEBUG=false`, `DEV_MODE=0`, exact 40-hex `APP_RELEASE_SHA`, prohibited email, exact DB identity, expected schema digest, expected role, supported live-book manifest, and artifact pins.
- [ ] Mount the immutable evaluator bundle at a fixed read-only path; install/prove the Linux isolation primitives required by the evaluator.
- [ ] Separate liveness from readiness. Liveness may be process-only; readiness must verify exact DB/schema/role/book/config/artifact identity without mutating data.
- [ ] Add a no-side-effect evaluator isolation handshake using a deterministic fixture.
- [ ] Before start, inspect the candidate container. After start, verify built image IDs equal running container image IDs and query `/version`, `/release.json`, loopback readiness, and public readiness/release endpoints.
- [ ] Emit a secret-free signed/hashed evidence record with source SHA, image IDs, evaluator pins, schema digest, database identity, role, supported books, and UTC time.

### T6: Integrate lanes and freeze the exact candidate

- depends_on: [T1, T2, T3, T4, T5]
- owns: integration branches, shared `app_factory.py`/CMake conflict resolution, final migration manifest, combined test ledger
- non_goals: remote push/merge, production mutation/deploy
- consumes: reviewed worker commits and receipts
- produces: one clean AlgoLens candidate SHA, one clean trade-ngin candidate SHA, one exact migration/config/artifact manifest
- acceptance: no unresolved worker concern; no unintended behavior loss; normal-main changes reconciled; full local suites green; every manifest digest matches integrated bytes
- verification: combined diff review, full tests in both repositories, schema/manifest validation
- estimate: L
- coordination_risk: high
- status: pending

- [ ] Inspect every worker diff and verification receipt; reject status-only or unevidenced returns.
- [ ] Reconcile each candidate with the current normal deployment branch without dropping continuation behavior.
- [ ] Resolve only coordinator-owned overlaps: `app_factory.py`, `apps/tools/CMakeLists.txt`, shared manifests, and documentation.
- [ ] Recompute all migration, artifact, configuration, and source digests after integration.
- [ ] Run full AlgoLens suites and clean Release trade-ngin build/CTest plus Python contract/integration suites.
- [ ] Confirm no secret, copied production row, dump, socket path, mutable image tag, or developer absolute path is committed.

### T7: Execute the isolated production-shaped rehearsal

- depends_on: [T6]
- owns: ephemeral rehearsal state and sanitized evidence; no repository feature edits
- non_goals: production writes, external calls, remote push/deploy
- consumes: exact integrated candidates, fresh authorized production backup/extract, secret-stripped production config
- produces: complete go/no-go evidence for schema, data, auth, runtime, clean/breach flows, restart/idempotency, cleanup, and repoint checks
- acceptance: every scenario passes on the clone; before/after System data digests match except approved fresh rehearsal publications; no historical QT rows; all external side effects absent; rehearsal fully deleted afterward
- verification: automated evidence manifest plus independent row/schema/catalog comparisons
- estimate: L
- coordination_risk: high
- status: pending

- [ ] Create the private cluster and all three targets through T3 tooling.
- [ ] Restore the fresh production-shaped data and prove baseline row counts/digests.
- [ ] Apply the exact ordered manifest to `qt_rehearsal_migrated`; run all destructive integration tests only against `qt_rehearsal_destructive_tests`.
- [ ] Run the System publisher for only the approved live conservative book using the exact secret-stripped production config and candidate artifact.
- [ ] Prove zero historical QT rows, then create the first fresh System seed/bootstrap.
- [ ] Exercise authenticated clean confirmation through immediate worker processing, receipt discovery, and internal report readiness.
- [ ] Exercise changed-quantity risk breach with two distinct non-submitter approvals; prove one approval, duplicate approval, submitter approval, stale preview, revoked grant, and wrong scope all refuse.
- [ ] Kill/restart the worker at claim, after source capture, before processor commit, and after commit; prove one receipt and stable IDs.
- [ ] Start two workers and prove one owner. Exercise transient retry, bounded dead letter, and recovery.
- [ ] Prove no broker request, email, investor/public row, external DNS/network DB connection, or production write occurred.
- [ ] Capture sanitized evidence, stop services, and delete the rehearsal cluster/extract/dumps as specified.
- [ ] After cleanup, inspect every candidate service configuration and assert it names `new_algo_data` and contains no rehearsal database/socket/path. Do not connect or start production yet.

### T8: Independent security review

- depends_on: [T7]
- owns: read-only security findings and acceptance decision
- non_goals: authoring fixes, production access
- consumes: integrated diffs, rehearsal evidence, route matrix, role matrix
- produces: severity-ranked review of authorization, secrets, command execution, isolation, SQL, and side-effect boundaries
- acceptance: no unresolved critical/high finding; medium findings explicitly accepted or repaired/retested
- verification: reviewer cites exact files/tests/evidence and attempts negative cases
- estimate: M
- coordination_risk: low
- status: pending

### T9: Independent cross-repository integration review

- depends_on: [T7]
- owns: read-only end-to-end contract review
- non_goals: authoring fixes, production access
- consumes: both candidate SHAs, manifests, rehearsal evidence
- produces: verification that AlgoLens, migrations, evaluator, System publisher, worker, receipts, and report discovery agree on identifiers/digests/state transitions
- acceptance: no orphan interface, mismatched digest, silent fallback, or unsupported live book
- verification: replay evidence and cross-repository contract matrix
- estimate: M
- coordination_risk: low
- status: pending

### T10: Independent release/operations review

- depends_on: [T7]
- owns: read-only rollout/rollback/evidence review
- non_goals: deploy, database changes, remote push
- consumes: runbook, artifact manifest, backup/restore and cleanup evidence
- produces: step-by-step go/no-go checklist with abort and rollback triggers
- acceptance: every production command has exact target/identity precheck, expected output, abort condition, and recovery action
- verification: dry-run against rehearsal evidence with no production access
- estimate: M
- coordination_risk: low
- status: pending

### T11: Normal-branch, CI, and production approval gate

- depends_on: [T8, T9, T10]
- owns: approval request and evidence summary
- non_goals: acting before approval
- consumes: reviewed candidate SHAs and all green evidence
- produces: explicit human decision for remote merges/pushes and, later, a separate explicit decision immediately before production mutation
- acceptance: normal deployment branches contain reviewed commits; exact-SHA CI is green; no branch drift; John Riley has approved the maintenance window and exact production manifest
- verification: remote branch SHAs, CI URLs/status, artifact/image digests, signed checklist
- estimate: S plus CI time
- coordination_risk: high
- status: pending

- [ ] Stop and request approval before pushes/merges that affect shared remotes.
- [ ] After approved merge/push, wait for exact-SHA CI and rebuild/reconcile any artifact digest changed by CI.
- [ ] Stop again immediately before the first production database/service modification and request explicit approval with the exact manifest and rollback plan.

### T12: Activate the one live book in production

- depends_on: [T11]
- owns: approved maintenance-window execution and immutable evidence
- non_goals: any other book, public/investor enablement, broker/email, historical QT backfill
- consumes: exact approved candidates, migration manifest, least-privilege credentials, rollout checklist
- produces: migrated `new_algo_data`, verified services, one immediate model-matching QT smoke receipt/report, rollback-ready evidence
- acceptance: fresh backup restores; exact migrations/roles/artifacts/configs are installed; only the approved live book is enabled; no-op smoke passes end to end; no rehearsal reference remains
- verification: pre/post database/artifact/service identities, no-op decision receipt/digests, side-effect absence, readiness and logs
- estimate: M
- coordination_risk: critical
- status: pending

- [ ] Enter the reserved after-hours window; stop AlgoLens/trade-ngin writers and confirm no active mutating sessions.
- [ ] Create a fresh full production backup immediately before migration, hash it, restore it into a separate disposable database, and prove the restore.
- [ ] Re-assert `new_algo_data`, approved endpoint, data directory, current role, branch SHAs, image digests, schema baseline, and no rehearsal paths before the first mutation.
- [ ] Apply only the approved manifest through the ephemeral migrator; create/grant the limited API, System publisher, and QT worker roles; remove runtime superuser use.
- [ ] Deploy the exact AlgoLens and trade-ngin images using the existing triggers and verify running image/artifact bytes.
- [ ] Install the exact approved production config/version. Start the System publisher and QT worker as separate services.
- [ ] Publish a fresh current-day System seed for `CONSERVATIVE_PORTFOLIO`; verify its model/artifact/config digests.
- [ ] Enable QT only for the one lifecycle=`live` scope.
- [ ] As John Riley, evaluate and confirm a model-matching/no-op quantity decision. Prove immediate processing, one immutable receipt, discovery, and internal report readiness.
- [ ] Verify no broker, email, investor/public publication, unexpected book, or historical QT write occurred.
- [ ] If any gate fails, disable QT, stop the worker, restore prior application images/config, preserve audit rows, and forward-fix additive schema. Restore the backup only for verified corruption or an explicitly approved disaster-recovery event.

### T13: Close out with honest production evidence

- depends_on: [T12]
- owns: final report and sanitized retained evidence
- non_goals: claiming unobserved recurring behavior
- consumes: production no-op evidence and reviewer checklists
- produces: final production-compatibility report tied to exact database/config/source/artifact identities
- acceptance: report distinguishes proven, deferred, and unobserved behavior; no secrets/data copies remain; rollback instructions and monitoring ownership are current
- verification: final checklist signed by coordinator and John Riley
- estimate: S
- coordination_risk: low
- status: pending

- [ ] Retain only sanitized manifests, checksums, row-count/digest comparisons, test/CI reports, and immutable database audit rows.
- [ ] State explicitly that completion is based on the immediate production no-op flow and that the following scheduled 09:30 ET cycle was not observed or proven.
- [ ] State that compatibility is with the exact tested `new_algo_data` state/config/artifacts, not an arbitrary future database state; readiness will refuse drift.

---

## Review focus

- Identity: unique production identities, corrected Dominick spelling, Hemdutt approval-only, Eric retired, submitter excluded at every layer.
- Default deny: every route classified; unknown roles/routes/config/schema/artifacts refuse rather than fall back.
- Replay: stable IDs across all worker crash boundaries; dispatcher failures never corrupt processor receipts.
- First day: one fresh System anchor, no historical backfill, conflicting partial state refuses.
- Artifacts: tested Release bytes equal packaged, deployed, and running bytes.
- Database: no superuser runtime, migration ownership works, cross-role denials are demonstrated.
- Isolation: rehearsal cannot reach production/external services and is completely deleted afterward.
- Scope: only the one lifecycle=`live` conservative futures book; no incubating/investor/public path.
- Rollback: disable worker/capability and restore prior images while preserving immutable workflow/audit rows.
- Honesty: do not call the 09:30 recurring schedule proven when only the immediate smoke was observed.

## Coordinator completion checklist

- [ ] All task dependencies are acyclic and every requested outcome maps to a task.
- [ ] Concurrent writers have disjoint worktrees and exclusive ownership.
- [ ] Every produced interface has one owner and a consumer test.
- [ ] All worker concerns are resolved or explicitly deferred outside launch scope.
- [ ] Security, integration, and release reviewers are independent from authors.
- [ ] Full combined verification runs after final integration.
- [ ] Fresh approval is obtained at both remote-merge and production-mutation gates.
- [ ] `new_algo_data` is untouched until T12.
