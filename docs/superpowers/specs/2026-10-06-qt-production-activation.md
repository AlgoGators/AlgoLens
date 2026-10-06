# QT Production Activation Specification

**Status:** User-confirmed design, 2026-10-06
**Production database:** `new_algo_data`
**Production activation scope:** lifecycle=`live` `trendfollowing` / `CONSERVATIVE_PORTFOLIO` only

## Goal

Make the reviewed AlgoLens and trade-ngin release work against the exact
production state of `new_algo_data`, prove the complete internal QT workflow on
an isolated production-shaped copy first, and fail closed when schema, data,
artifact, authorization, or runtime contracts do not match.

## Current production-readiness facts

- `new_algo_data` is real production data and must never be used as a
  destructive test database.
- The database currently has no `trading.qt_*` workflow tables, no compatible
  QT processor/runtime tables, no post-launch System positions, and several
  missing baseline columns.
- Production services currently connect as the `postgres` superuser.
- The AlgoLens production container does not mount the required evaluator
  bundle.
- trade-ngin has one-shot evaluator and desk-processing binaries but no
  committed service that discovers eligible confirmed decisions and processes
  them immediately.
- The October 2 backup contains only `auth` and `trading`; a real-data rehearsal
  also needs the relevant `futures_data.ohlcv_1d` history and
  `metadata.contract_metadata`.
- The currently scheduled production book is the conservative futures book:
  `LIVE_TREND_FOLLOWING` in `CONSERVATIVE_PORTFOLIO`.

## Product boundary

- The logged-in dashboard remains on the System / Model stream.
- QT is an explicitly selected internal exact-position workflow.
- The launch is internal-only. Investor/public publication remains disabled.
- Successful QT processing automatically exposes the internal report when its
  receipt is eligible; it does not create an investor/public snapshot.
- Email delivery is disabled.
- No broker order submission is included.
- No historical QT backfill is allowed.
- Production QT enablement is limited to lifecycle=`live` books. Incubating and
  investor books are excluded even when branch code can represent them.

## Human authorization

- John Riley is the initial QT submitter.
- Hemdutt Rao, Xander Robbins, and Dominick Dupuy form the approval pool.
- A risk breach requires two distinct active approvers.
- The submitter may not satisfy either approval slot.
- Hemdutt remains approval-only and gains no submit, edit, confirm, or publish
  authority.
- Eric remains retired except for immutable historical evidence and migration
  cleanup.
- The internal portions of issue #94 are required before launch: centralized
  capabilities, default-deny route classification, capability output from
  `/auth/verify`, and frontend capability gates. Investor/public scope remains
  deferred.

## Runtime architecture

- The System publisher continues its existing 09:30 ET schedule and requires
  an approved exact configuration/version before running.
- A separate QT worker runs beside trade-ngin with independent credentials and
  locking.
- A clean confirmation becomes eligible immediately.
- A risk-breach confirmation becomes eligible immediately after the second
  valid approval.
- The QT worker discovers eligible decisions, prepares first-day/continuation
  inputs, invokes the pinned desk artifacts, writes one immutable receipt, and
  safely retries idempotent work after interruption.
- Pending work should normally start within one minute; a five-minute queue age
  is an alert condition.
- AlgoLens mounts a read-only closed evaluator bundle and verifies its build,
  executable SHA-256, and canonical bundle SHA-256 against database policy.

## Artifact and deployment identity

- Dirty work is preserved, reviewed, committed, merged through each normal
  deployment branch, and verified by CI before production use.
- Deployments use exact reviewed AlgoLens and trade-ngin Git identities.
- The current trade-ngin deployment trigger is retained.
- The deployed trade-ngin short SHA and immutable image digest are recorded and
  checked before and after deployment.
- Model, evaluator, desk binaries, migration files, and configuration snapshots
  receive recorded cryptographic digests.
- The existing implementation is the candidate. Completed trade-ngin behavior
  is preserved; only evidence-backed gaps are changed.

## Database isolation and access

- The rehearsal database is an unprivileged PostgreSQL 16 socket-only cluster
  under a private, uniquely named temporary directory.
- It has no TCP listener, production credentials, service-name fallback, or
  network-host fallback.
- A restored baseline database, migrated production-shaped database, and
  destructive integration-test database are separate targets.
- `ALGOLENS_TEST_DB` may point only at the independently owned destructive-test
  database.
- The production configuration is copied into rehearsal with secrets removed;
  production behavior is not inferred from repository templates.
- The real-data extract includes the complete production universe needed by
  the conservative futures runner, the inclusive 730-day input window, and
  matching instrument metadata.
- Migration, AlgoLens API, System publisher, and QT worker use separate
  least-privilege database roles. Runtime services do not use `postgres`.

## Rehearsal requirements

- Rehearsal must be unable to write production, call a broker, send email,
  create public/investor publications, or fall back to a network database.
- The ordered cross-repository migration ledger is explicit and hash-pinned;
  filenames are never applied merely by numeric ordering.
- trade-ngin migration 002 (`backfill_qt_from_system`) is excluded.
- Conditional/staged migrations are admitted only when a selected production
  contract requires them and their tests pass.
- The migrated clone preserves all pre-existing System rows and produces zero
  historical QT rows.
- Full unit, native, PostgreSQL, artifact, authorization, clean-decision,
  risk-breach, restart, idempotency, and stale-evidence checks pass.
- Risk-breach and changed-quantity scenarios are proved on the isolated copy,
  not by changing the live production book.

## Rehearsal cleanup

- Capture only sanitized logs, manifests, checksums, row-count/digest
  comparisons, and test reports.
- Stop PostgreSQL, verify the temporary path prefix and current-user ownership,
  then delete the rehearsal cluster and copied market data.
- Prove the rehearsal socket and databases no longer exist.
- Before production start, verify every service configuration names
  `new_algo_data` and does not contain the rehearsal socket, port, database, or
  temporary path.

## Production rollout

- John Riley is the go/no-go owner. Codex may execute technical steps but must
  obtain fresh explicit approval immediately before the first production
  modification.
- Rollout occurs after the trading day in a reserved maintenance window with
  AlgoLens and trade-ngin writers stopped.
- Immediately before migration, create a fresh backup and prove it restores to
  a separate disposable database.
- Apply only the exact migration manifest already proved on the fresh clone.
- Deploy the exact tested artifacts and limited service credentials.
- Publish a fresh current-day System seed for `CONSERVATIVE_PORTFOLIO`.
- Enable QT only for the one live registry/book scope.
- Run one production model-matching/no-op decision through evaluation,
  confirmation, processing, receipt, discovery, and internal report readiness.
- Completion is declared after the immediate production no-op flow passes. The
  final report must state that the following scheduled 09:30 ET cycle was not
  observed and therefore is not part of the completion evidence.

## Rollback

- Disable QT capability for every enabled book.
- Stop the QT worker.
- Restore the prior verified application images/configuration.
- Preserve immutable drafts, previews, decisions, approvals, receipts, and
  audit evidence.
- Prefer forward-fixing additive schema migrations. Restore the fresh backup
  only for verified corruption or an explicitly approved disaster-recovery
  event.

## Parallel execution model

- This coordinator exclusively owns the dependency graph, shared plan,
  migration manifest integration, approvals, production commands, and final
  evidence ledger.
- Five first-wave tasks audit disjoint domains: AlgoLens authorization,
  AlgoLens production runtime, trade-ngin QT worker, trade-ngin Release
  artifacts, and database rehearsal/migrations.
- The first wave is read-only. No writer begins until the current dirty
  AlgoLens state is preserved as an auditable snapshot and each writer receives
  an isolated Git worktree with exclusive ownership.
- Later independent tasks review security, cross-repository integration, and
  full release evidence. Reviewers do not author the implementation they
  review.
- Worker tasks never modify production, push, deploy, merge, change grants, or
  contact external services.

## Acceptance statement

The release is production-compatible only when every gate above is satisfied
against the exact tested `new_algo_data` snapshot, configuration, migrations,
and artifacts. It is not a promise of compatibility with an arbitrary future
database. Readiness checks must refuse activation when production drifts from
the verified contract.
