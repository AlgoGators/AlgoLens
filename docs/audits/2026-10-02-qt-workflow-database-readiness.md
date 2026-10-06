# QT workflow database readiness — 2026-10-02

This is a sanitized, read-only checkpoint of the database configured by the
local AlgoLens checkout. No migration, grant, policy, position, receipt, or
publication was written while collecting it.

## Outcome

The database is **not ready to activate the QT position-decision workflow**.
Applying only the AlgoLens workflow tables would store a decision but would
leave it with no compatible model-seed publisher or desk processor. A partial
rollout must not be presented as a working launch.

## Observed facts

- PostgreSQL 16.14 was reached through an explicitly read-only transaction.
- The configured login is the `postgres` superuser. Runtime services need
  separate least-privilege roles before rollout.
- No `trading.qt_*` relation exists.
- `trading.positions` contains 3,878 `system` rows, zero QT rows, and its newest
  date is 2026-08-05. This cannot support an October 3 current-source launch.
- The live `trendfollowing` registry row is correctly scoped to
  `CONSERVATIVE_PORTFOLIO`. The equity mean-reversion registry row is scoped to
  `EQUITY_MR_PORTFOLIO`.
- `trading.portfolios` is empty even though strategy-book membership rows exist.
- The ordinary AlgoLens schema checker reports three gaps: migration 007's
  `strategy_registry.asset_class`, and trade-ngin migration 012's
  `position_overrides.portfolio_id` plus
  `position_override_legacy_scopes`.
- The engine foundation is older than the QT workflow line: `run_inputs`,
  runtime intent/attempt tables, execution/result `portfolio_type` columns,
  proposal/seed storage, accounting inputs, market/finalization sources, and
  desk results are absent. The positions stream constraint admits only
  `system` and `qt`.

## Restore and no-backfill rehearsal

On 2026-10-02, the complete affected `trading` and `auth` schemas were exported
with PostgreSQL 16 `pg_dump` in custom format and restored successfully into a
disposable database on the same PostgreSQL server. The restored copy then
accepted this exact, no-history-backfill sequence:

1. trade-ngin 003, 006, 007, 011, 010, 012;
2. AlgoLens 007;
3. trade-ngin 013, 014, 015, 016;
4. AlgoLens 003, 004, 005;
5. trade-ngin 020, 017, 018.

Migration 002 was deliberately excluded. Migration 010 was exercised only on
the disposable copy; it is unrelated to QT activation and should be omitted
from the configured-database rollout to avoid rewriting historical metric
sentinels. Post-migration verification found all
core workflow, governed-source, model-publication, exact-position, accounting,
receipt, and finalization relations present; `positions` retained exactly 3,878
`system` rows and contained zero `qt` or `qt_proposal` rows. The disposable
database was dropped after verification. The affected-schema backup is retained
outside the repositories at
`<OFFLINE_BACKUP_DIR>/new_algo_data-trading-auth-pre-qt-20261002.dump`
with SHA-256
`a8dc0ab4ac8cc322cd6ffb9495a000af2270d20b93176d49b9ff0124ffbca532`.

The configured database was not migrated. Activation still requires explicit
submitter and two-person approver assignments, a production evaluator bundle
and desk-processor host/schedule, and a fresh launch-day model publication.

## Required rollout sequence

1. Verify a recoverable database backup with a restore drill, a maintenance
   window, a named operator, and a rollback owner. A file existing is not restore
   evidence.
2. Reconcile the skipped/partial trade-ngin baseline before QT migrations. In
   particular, the user requested a clean launch with no historical QT data, so
   `002_backfill_qt_from_system.sql` must not be run by habit; the compatible
   no-backfill path needs explicit review while the structural prerequisites
   from 003/006/007/012 are brought current.
3. Apply the reviewed AlgoLens workflow sequence: 003, 004, 005, and 007.
4. Apply the compatible trade-ngin runtime/proposal/precision/desk sequence
   after its prerequisites: 013 through 018, plus the reviewed exact-accounting
   and asset-class extensions required by each enabled book. Do not apply staged
   proposal migrations merely because their numbers are higher.
5. Deploy the matching AlgoLens API/frontend and the matching trade-ngin
   publisher/desk binaries. A schema by itself does not run the processor.
6. Configure, with named human approval rather than inferred values:
   `qt_workflow_capabilities`, submit/approve grants, the approver identity
   mapping, evaluation/execution source policies, evaluator artifact hashes, and
   the processor schedule/service.
7. Publish a fresh current-day MODEL seed and governed evaluation snapshot, then
   exercise the authenticated flow: draft -> preview -> decision -> approvals if
   required -> receipt -> immutable decision discovery. Keep the main dashboard
   on the `system` stream; QT remains an explicitly selected position stream.

## Release gate

Do not claim production readiness until a fresh current-day system publication
exists, the exact migrations and binaries have been tested together on a
restored disposable copy, and the decision receipt/discovery flow succeeds for
the intended book without publishing historical QT data.
