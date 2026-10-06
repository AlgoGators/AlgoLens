# AlgoLens QT Exact-Choice Continuation — Detailed Handoff

Last updated: 2026-10-06 (America/New_York)

## Start here

This document is the continuity record for work on AlgoLens branch
`codex/qt-exact-choice-continuation`. A new chat should read this entire file,
then inspect the working tree before changing anything.

The most important facts are:

1. The local visual demo works at
   `http://127.0.0.1:3002/?demo=position-edit` and does not require the API or
   PostgreSQL.
2. The signed-in portfolio dashboard is intentionally pinned to the
   **System / Model** stream. QT is a separate, explicitly selected edit and
   review stream.
3. The desired QT user flow is now two steps: **Evaluate selections**, then
   **Confirm positions**. Evaluation automatically saves the draft first.
4. A successful confirmation is stored as an immutable server decision. Clean
   decisions can process immediately; a risk breach waits for two distinct
   authorized approvers. Publication is automatic after successful processing.
5. The configured PostgreSQL database has **not** been migrated or modified for
   this QT workflow. A restore rehearsal succeeded on a disposable copy, but
   production activation still requires coordinated migrations, runtime
   services, permissions, and fresh System data.
6. The worktree is dirty. Preserve all existing changes. Do not reset, discard,
   or broadly rewrite them.

## Repository and branch

- Repository: `AlgoGators/AlgoLens`
- Worktree:
  `/home/john-riley/projects/Algo/.worktrees/AlgoLens/codex-qt-exact-choice-continuation`
- Branch: `codex/qt-exact-choice-continuation`
- Current local HEAD at handoff time: `9c2e41ff`
- Remote tracking branch at handoff time:
  `origin/codex/qt-exact-choice-continuation` at `a044ab36`
- The local branch is three commits ahead of the remote.
- There are also substantial uncommitted changes. Do not claim they are pushed
  or committed.

Recent local commits:

| Commit | Purpose |
| --- | --- |
| `9c2e41ff` | Records the QT database migration restore rehearsal. |
| `1f03081e` | Makes the local QT demo retain and rediscover a processed decision. |
| `83d95f09` | Keeps the logged-in dashboard on the System / Model stream. |
| `a044ab36` | Simplifies the position-edit review UI; this is the current remote tip. |
| `10b615a1` | Adds the loopback-only position-edit visual demo. |
| `b07ed016` | Gates investor reads on successful publications. |
| `b4accb57` | Keeps a newly launched, empty strategy detail page clean. |
| `123d07e6` | Starts public portfolio history at the feature launch boundary. |

Untracked directories at handoff time include `graphify-out/` and `logs/`.
They are local artifacts and should not be committed.

## The user's product decisions

Treat these as settled requirements unless the user explicitly changes them:

- The main dashboard shown after login is the **System / Model** view, not the
  QT view.
- System publication is automatic.
- QT publication is also automatic after a confirmed decision finishes
  processing and passes the publication gates.
- QT is for governed human changes to exact position quantities. It does not
  replace the System / Model recommendation.
- Editing must collect:
  - the exact requested quantity;
  - who is making the request, derived from the authenticated session rather
    than entered or trusted from the browser;
  - a required explanation/rationale;
  - the exact numerical difference from the model quantity;
  - evaluator-produced post-change risk, optimizer, and transaction-cost
    evidence before confirmation.
- The operator must evaluate before confirming. There should not be a separate
  confusing Save button in the ordinary path; **Evaluate selections** saves the
  draft and evaluates it as one understandable action.
- If an evaluated choice breaches a risk limit, confirmation creates a
  **Pending approval** decision. Exactly two different authorized people must
  approve it before processing continues.
- Hemdutt Rao should be an approval-only person. He must not gain permission to
  edit, submit, confirm, or publish QT positions.
- Eric must not be an active or displayed approver. The only remaining Eric
  reference should be a migration cleanup/tombstone needed to deactivate any
  previously deployed authority without deleting historical evidence.
- Public portfolio history begins at the feature launch boundary and contains
  no pre-launch history. The current code constant is `2026-10-01`.
- A strategy page can show one strategy's position while the book-level QT
  editor contains rows for multiple component owners. This is valid only when
  the dialog clearly says it is editing the entire book and distinguishes
  editable rows from locked holdings belonging to other strategies.

## Simple mental model

There are two related but distinct position views:

1. **System / Model**: what the algorithm recommends. This is the default and
   public dashboard view.
2. **QT**: the governed human-selected quantities for the same book/day. This
   is reached deliberately through the position editor.

The intended flow is:

```text
System publishes model seed
        |
        v
User opens Edit positions
        |
        v
User changes exact quantities and writes a rationale
        |
        v
Evaluate selections
  - automatically saves immutable draft evidence
  - runs the authoritative evaluator
  - returns post-change risk/cost evidence
        |
        v
Confirm positions
        |
        +--> no risk breach: confirmed -> processed -> receipt -> automatic report
        |
        +--> risk breach: pending approval -> two distinct approvers
                              -> processed -> receipt -> automatic report
```

The dashboard remains on System / Model throughout. A completed QT decision is
visible through its explicit decision/review surfaces and QT stream, not by
silently changing the default dashboard stream.

## What was analyzed from GitHub issues

### AlgoLens issue #83

Issue #83 concerns position-stream correctness and isolation. System and QT
rows must never be blended when they share the same symbol, strategy, book, and
date. The continuation branch already had the stronger implementation:

- System positions are the public/default stream.
- System versus QT selection is explicit.
- Portfolio result and position reads are scoped.
- Stale UI responses are rejected.
- PostgreSQL coverage exercises same-symbol/same-date separation.
- Legacy rows without valid stream metadata are presented as
  `Legacy / Unscoped positions` rather than silently treated as one of the
  governed streams.

### AlgoLens issue #84

Issue #84 concerns registry-to-portfolio mapping. A strategy registry entry
must resolve to the correct book, and every position/configuration read must
retain that book scope. It was treated as completed on the continuation branch.
The published-configuration disclosure exists to show the engine-recorded
configuration for the exact `(registry_id, portfolio_id)` pair.

### AlgoLens issue #94 and related issues

Issue #94 is the authorization/capability foundation. It defines server-side
permissions and scope rather than allowing each page to hard-code roles.
Related work forms this chain:

- #93: parent audience policy.
- #94: capabilities and server-enforced scope.
- #95: investor portal, which depends on investor scope from #94.
- #96: public page, which depends on #94's open allowlist and route checks.
- #92 and #97 are secondary consumers that should use shared capabilities
  instead of inventing independent role checks.

Issues #83 and #84 are data-isolation prerequisites, not substitutes for #94.

## What has been built

### 1. System-first dashboard and launch boundary

- The main portfolio dashboard requests the `system` position stream by
  default.
- Public result, equity, position, and held-position reads are scoped to the
  launch boundary.
- `PORTFOLIO_LAUNCH_DATE` is currently fixed to `2026-10-01` in
  `algolens-api/algolens/domain/portfolio/streams.py`.
- Before current System publications exist, the UI shows an honest empty state
  rather than backfilling old records or inventing activity.
- Investor-book reads are gated on successful publication.

### 2. Informed QT position editing

- `Edit positions` opens a book-scoped QT dialog.
- The authenticated actor is displayed from the signed-in user. The browser
  does not submit an editable actor claim.
- The rationale is required, trimmed, and limited to 1–1000 UTF-8 bytes.
- The rationale is saved in `qt_drafts.selection_payload` with the selection
  rows, so it participates in the request and immutable draft digests.
- Exact quantities remain decimal strings. Futures require whole contracts;
  fractional assets may remain fractional. The UI does not silently round.
- The selection table shows model, current, proposed, and numerical delta
  values.
- Evaluation evidence comes only from the backend evaluator. The React client
  does not calculate authoritative risk locally.

### 3. Simplified two-step workflow

The current uncommitted UI intentionally exposes:

1. **Evaluate selections** — automatically saves any changed quantities and
   rationale, then creates a preview/evaluation.
2. **Confirm positions** — appears/enables only after a valid evaluation.

For a risk-breach preview, the second button reads
**Confirm positions and request approvals**.

This replaced the older visible sequence of Save draft -> Evaluate -> Confirm,
which was confusing because the user could not tell where to save after
evaluation.

### 4. Immutable decisions, recovery, and receipts

- Confirmation sends the preview ID, exact payload digest, idempotency key, and
  risk-warning acknowledgement.
- Browser `sessionStorage` retains an intent only long enough to recover an
  uncertain mutation outcome safely.
- The server remains authoritative. `Refresh discovered decision` retrieves
  the immutable decision, preview evidence, approval status, and receipt.
- A completed decision remains locked on the screen where it was submitted.
- On a later reload, a stale browser recovery record no longer blocks a fresh
  evaluation when the server already proves that the decision reached a
  terminal `processed` or `failed` receipt.
- The recovery record is cleared only when terminal evidence is verified
  against the active preview or the discovered immutable preview. Pending,
  processing, mismatched, or unverified states remain recoverable.
- Successful processing stores a receipt and automatically exposes the report
  when `report_ready` is true.

The latest bug fixed here was the page appearing stuck with both
`Recover confirmation` and a server-side `Report ready` decision. The root
cause was a stale browser recovery marker. The fix is in
`algolens-frontend/src/components/QtProposalWorkspace.tsx`, primarily
`applyDecision()` and `settleResolvedConfirmation()`.

### 5. Risk-breach approvals

- A breach creates a `pending_override` decision and an override request.
- The database requires exactly two approvals.
- Uniqueness constraints prevent the same `person_id` or `user_id` from
  satisfying both slots.
- Approval evidence is append-only and records person, user, mapping version,
  grant version, and timestamp.
- Approval does not itself allow the approver to edit or submit positions.

### 6. Hemdutt Rao approval-only authorization

The uncommitted additive migration
`algolens-api/migrations/009_hemdutt_qt_approver.sql`:

- resolves exactly one active `auth.users` row whose trimmed case-insensitive
  name is `Hemdutt Rao`;
- fails closed when no unique account exists;
- requires that account to have role `exec_board`;
- grants active `qt_approve` capability;
- maps it to canonical `person_id = 'hemdutt_rao'`;
- does not grant `qt_submit`;
- deactivates/revokes legacy Eric approval authority if it ever existed;
- preserves old immutable rows rather than deleting audit history.

HTTP decision-read and approval routes allow the appropriate executive-board
reader/approver path. Proposal, draft, preview, confirmation, and publication
remain restricted to submit-capable roles and still require explicit
`qt_submit`.

### 7. Published configuration disclosure

The `Published configuration` panel was redesigned in place:

- starts collapsed;
- opens with the chevron beside the title;
- visually matches the rest of the site;
- shows Registry and Book scope as small badges;
- is read-only;
- fetches engine-recorded configuration only when rendered and can be manually
  refreshed.

`No published configuration for this book` means no matching engine-published
record exists for that registry/book pair. It does not mean the browser should
invent one. The local demo supplies a contract-shaped mock record to illustrate
the populated state.

## Local mock demo

URL:

`http://127.0.0.1:3002/?demo=position-edit`

Important properties:

- It is enabled only on `localhost`, `127.0.0.1`, or `::1` and only when
  `demo=position-edit` is present.
- It intercepts the normal frontend transport and returns production-contract-
  shaped fixture responses.
- It does not contact or mutate the configured database.
- Demo actor ID is the production-shaped numeric string `9000001`.
- Demo book is `synthetic-book-A`.
- Demo strategy/registry is `component-1` / Synthetic Alpha.
- Demo source day is `2026-09-25`.
- The System view shows model quantity 4; the QT view starts with quantity 5.
- The book preview contains two component-owner rows even though the strategy
  page focuses on one strategy. This demonstrates book-level editing.
- Confirmation stores only a demo marker in `window.sessionStorage` under
  `algolens.demo.position-edit.decision.v1`.
- A later GET of the book decision returns the immutable processed fixture, so
  reload/refresh visibly retains `Report ready`.

Primary mock file:

`algolens-frontend/src/infrastructure/demo/positionEditDemo.ts`

To start the frontend if port 3002 is not already serving:

```bash
cd /home/john-riley/projects/Algo/.worktrees/AlgoLens/codex-qt-exact-choice-continuation/algolens-frontend
npm run dev -- --host 127.0.0.1 --port 3002
```

The demo needs no API server. The non-demo site does.

## Configured database: actual state

Do not tell the user the real database is ready. It is not.

A read-only audit on 2026-10-02 found:

- PostgreSQL 16.14 database `new_algo_data` was reachable.
- The configured login was the `postgres` superuser; production services still
  need least-privilege roles.
- No `trading.qt_*` relation existed in the configured database.
- `trading.positions` had 3,878 System rows and zero QT/QT-proposal rows.
- The newest System position date was `2026-08-05`, too old for a fresh October
  launch.
- `trading.portfolios` was empty even though strategy-book membership records
  existed.
- Several prerequisite engine/runtime tables and columns were absent.
- No grants, roles, migrations, positions, publications, or receipts were
  written to the configured database during the audit.

A backup of the affected schemas was created and restore-tested:

- Path:
  `/home/john-riley/projects/Algo/.database-backups/new_algo_data-trading-auth-pre-qt-20261002.dump`
- Permissions at audit time: mode `0600`
- SHA-256:
  `a8dc0ab4ac8cc322cd6ffb9495a000af2270d20b93176d49b9ff0124ffbca532`

A disposable restored database accepted the reviewed no-history-backfill
migration sequence and retained exactly 3,878 System rows with zero QT rows.
The disposable database was then dropped. This proves migration compatibility
on that copy, not production activation.

Full audit:

`docs/audits/2026-10-02-qt-workflow-database-readiness.md`

## Database schema map

AlgoLens migration `003_qt_decision_workflow.sql` defines the core workflow:

| Table | Plain-language purpose |
| --- | --- |
| `trading.qt_workflow_capabilities` | Enables/disables QT per book and versions that decision. |
| `trading.qt_action_grants` | Gives a user `qt_submit` or `qt_approve`; every grant is explicitly active/versioned. |
| `trading.qt_approver_allowlist` | Maps one authenticated user to one canonical human approver identity. |
| `trading.qt_drafts` | Immutable versions of exact selections and rationale, bound to System source/provenance digests. |
| `trading.qt_draft_heads` | Points to the current draft version for each book/day. |
| `trading.qt_previews` | Immutable evaluator output: selected-book digest, read-set digest, risk/cost payload, evaluator build, and policy version. |
| `trading.qt_decisions` | The immutable confirmed choice, tied to one preview and the submitter's capability version. |
| `trading.qt_override_requests` | Records that a risk breach requires exactly two approvals. |
| `trading.qt_override_approvals` | Append-only approval evidence with distinct-person and distinct-user constraints. |
| `trading.qt_desk_receipts` | Processing outcome (`pending`, `processed`, or `failed`), publication digest/payload, and report eligibility. |
| `trading.qt_idempotency` | Stores mutation request/response evidence so retries cannot create a different result. |

Database triggers make draft evidence, decisions, requests, approvals, and
idempotency rows immutable. Preview state may advance only through allowed
transitions. A decision may advance only from `pending_override` to
`confirmed_decision` without changing its evidence.

Other AlgoLens migrations add governed source policies, evaluator bundle
metadata, investor publication support, registry asset class, System investor
book access, and Hemdutt's approval-only enrollment. Matching trade-ngin
migrations provide the System seed publisher, proposal/precision/runtime
tables, exact accounting, desk processing, and finalization data. The two
repositories must be deployed as a compatible set.

The reviewed no-backfill rehearsal sequence is documented in the database
audit. Do not run migration `002_backfill_qt_from_system.sql` for this requested
clean launch merely because its number is lower.

## What is still missing for real data

The application code and mock UI are not enough. Real activation requires all
of the following:

1. Reconfirm the backup, maintenance window, named operator, and rollback
   owner.
2. Review and apply the compatible prerequisite and QT migrations from both
   AlgoLens and trade-ngin, using the no-history-backfill path.
3. Deploy matching AlgoLens API/frontend and trade-ngin System publisher,
   evaluator, desk processor, accounting, and finalization binaries.
4. Create least-privilege service roles instead of running production services
   as the PostgreSQL superuser.
5. Explicitly enable each intended book in
   `qt_workflow_capabilities`.
6. Explicitly assign submitters and two-person approvers. Do not infer people
   or user IDs.
7. Install and verify evaluator/processor artifact hashes and policy versions.
8. Choose the real evaluator and QT desk processor host/schedule/service.
9. Publish a fresh current-day System / Model seed for each enabled book.
10. Exercise the authenticated end-to-end path on a restored disposable copy:
    draft -> preview -> decision -> approvals if needed -> processor receipt ->
    immutable decision discovery -> automatic report publication.
11. Only then repeat the reviewed rollout in the actual target environment.

No new chat should apply production migrations, change real grants, or enroll
real people without explicit user authorization and a clearly identified
target database.

## Current uncommitted change set

At handoff time, `git status --short` shows edits in these areas:

### Backend

- QT HTTP role/capability enforcement.
- QT decision-read service behavior.
- Draft/rationale workflow behavior and models.
- QT authorization/approver mapping.
- Migration 003 canonical allowlist update.
- New migration 009 for Hemdutt approval-only enrollment and Eric retirement.
- Unit and PostgreSQL integration tests for all of the above.

### Frontend

- Collapsed, redesigned Published configuration panel.
- Simplified Evaluate -> Confirm flow.
- Button/copy updates across normal, empty-owner, and acceptance tests.
- Terminal confirmation recovery cleanup.
- Hemdutt approval fixtures replacing Eric display fixtures.
- Strict preview/domain and recovery tests.

Use `git status --short` and `git diff --stat` again because this list may become
stale after the handoff.

## Important files

### Product/UI

- `algolens-frontend/src/components/StrategyDetail.tsx`
- `algolens-frontend/src/components/EditPositionModal.tsx`
- `algolens-frontend/src/components/QtProposalWorkspace.tsx`
- `algolens-frontend/src/components/qt-proposal/QtSelectionTable.tsx`
- `algolens-frontend/src/components/qt-proposal/QtPreviewEvidence.tsx`
- `algolens-frontend/src/components/qt-proposal/QtDecisionStatus.tsx`
- `algolens-frontend/src/components/ConfigurationInspectionPanel.tsx`
- `algolens-frontend/src/domain/portfolio/qtPreview.ts`
- `algolens-frontend/src/infrastructure/api/qtPreviewApi.ts`
- `algolens-frontend/src/infrastructure/api/qtRecovery.ts`
- `algolens-frontend/src/infrastructure/demo/positionEditDemo.ts`

### Backend/API

- `algolens-api/algolens/adapters/http/qt_workflow.py`
- `algolens-api/algolens/application/portfolio/qt_workflow.py`
- `algolens-api/algolens/application/portfolio/qt_decision_read.py`
- `algolens-api/algolens/domain/portfolio/qt_workflow_models.py`
- `algolens-api/algolens/infrastructure/portfolio/qt_authorization.py`
- `algolens-api/algolens/domain/portfolio/streams.py`
- `algolens-api/algolens/infrastructure/portfolio/repositories.py`

### Migrations and audit

- `algolens-api/migrations/003_qt_decision_workflow.sql`
- `algolens-api/migrations/004_qt_governed_sources.sql`
- `algolens-api/migrations/005_qt_evaluator_bundle.sql`
- `algolens-api/migrations/006_qt_investor_publication.sql`
- `algolens-api/migrations/007_strategy_registry_asset_class.sql`
- `algolens-api/migrations/008_system_investor_book_access.sql`
- `algolens-api/migrations/009_hemdutt_qt_approver.sql`
- `docs/audits/2026-10-02-qt-workflow-database-readiness.md`
- `docs/superpowers/plans/2026-09-30-informed-position-edit-dialog.md`

## Verification already completed

For the most recent stale-recovery/page-stuck fix:

- Focused frontend recovery/workspace tests: 75/75 passed.
- Full frontend suite: 80 files, 1,375 tests passed.
- `npm run typecheck`: passed.
- `npm run build`: passed.
- `git diff --check`: passed before this handoff file was added.
- Live browser reproduction passed:
  - stale `Recover confirmation` disappeared after verified terminal recovery;
  - **Evaluate selections** became enabled;
  - evaluation exposed enabled **Confirm positions**;
  - confirmation produced `Report ready`;
  - no stale recovery button remained;
  - no browser console errors were present.

Earlier checkpoints recorded full frontend suites of 1,372–1,419 tests and
2,121+ non-integration backend tests, depending on that checkpoint's code.
Those numbers are historical evidence, not a substitute for rerunning the
current dirty tree.

PostgreSQL migration integration tests exist, but the configured live database
was intentionally not used as a disposable test database.

## Recommended commands for the next chat

Run from the worktree root unless noted:

```bash
git status --short --branch
git log -8 --oneline --decorate
git diff --stat
git diff --check
```

Frontend verification:

```bash
cd algolens-frontend
npm test
npm run typecheck
npm run build
```

Focused recovery verification:

```bash
cd algolens-frontend
npx vitest run \
  src/components/QtProposalWorkspace.test.tsx \
  src/components/QtEmptyOwnerWorkspace.test.tsx \
  src/infrastructure/api/qtRecovery.test.ts
```

Backend test commands should be selected from the repository README/current
environment. Do not point integration tests at the configured non-disposable
database.

## Known UX behavior and terminology

- **Evaluate selections**: saves the current exact selection/rationale if
  needed, then asks the server evaluator for preview evidence.
- **Confirm positions**: locks the exact evaluated quantities into an immutable
  decision.
- **Pending approval**: the decision breached a configured risk rule and needs
  two distinct authorized approvals.
- **Report ready**: processing produced an eligible receipt and the report can
  be shown/published.
- **Refresh discovered decision**: re-reads the server's authoritative decision,
  approvals, receipt, and immutable preview; it is not a second submission.
- **Recover confirmation**: safely retries or discovers a confirmation whose
  network outcome was uncertain. It should not remain after a verified terminal
  decision.
- **Published configuration**: engine-recorded read-only settings for the exact
  registry/book scope, not the user's editable QT draft.

## Do not accidentally regress these invariants

- Never let the browser claim the authenticated actor.
- Never calculate authoritative risk in React.
- Never confirm without an evaluator preview tied to the saved draft and source
  digests.
- Never mix System and QT rows.
- Never allow one person/account to count as two approvers.
- Never clear uncertain recovery state using unverified or mismatched evidence.
- Never make QT the default logged-in dashboard stream.
- Never publish a report before the processing receipt says it is eligible.
- Never imply the mock demo writes the real database.
- Never backfill historical QT records for this clean launch unless the user
  explicitly reverses that decision.
- Never commit `graphify-out/`, `logs/`, secrets, database dumps, or local
  runtime artifacts.

## Recommended next steps

1. Read this file and the database readiness audit.
2. Inspect the complete dirty diff without discarding anything.
3. Rerun the focused and full verification suites on the current tree.
4. Manually verify the local demo flow from a fresh browser session.
5. Review the uncommitted backend authorization/Hemdutt migration changes for
   least privilege and migration idempotency.
6. Decide with the user whether to commit and push the current work. No commit
   or push was performed for the uncommitted changes described above.
7. Keep real database rollout as a separately authorized operation with an
   explicit target, migration plan, named humans, runtime services, and rollback
   procedure.

## Suggested opening prompt for the next chat

> Continue the AlgoLens work in
> `/home/john-riley/projects/Algo/.worktrees/AlgoLens/codex-qt-exact-choice-continuation`.
> Read `handoff.md` and
> `docs/audits/2026-10-02-qt-workflow-database-readiness.md` completely before
> making changes. Preserve the dirty worktree. Verify the current branch and
> diff, then continue from the Recommended next steps. The local mock demo is
> `http://127.0.0.1:3002/?demo=position-edit`; it is not proof that PostgreSQL is
> deployed. Keep the main dashboard on System / Model, preserve automatic
> publication, and do not modify the real database without explicit approval.
