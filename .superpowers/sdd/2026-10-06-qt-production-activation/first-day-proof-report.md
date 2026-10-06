# AlgoLens first-day proof reader repair

Scope: read-only first-day accounting/receipt/report proof and the immediate
continuation predecessor. No production access, deployment, remote write,
credential use, or schema/role mutation. Worktree: `qt-prod-readiness-final`.

## Implemented

- The accounting loader no longer drops first-day results through an inner
  predecessor join. It loads the exact anchor, decision, preview, MODEL,
  evaluation snapshot, policy, run-input configuration, storage capabilities,
  admitted market and original processing context from SQL. An immediate
  predecessor may be first-day; history traversal remains bounded to one.
- `qt_first_day_proof.py` accepts only the complete first-day contract, not a
  schema-version string alone. Anchor/input identities and canonical digests,
  same-day System-to-QT opening translation, MODEL seed/proposal identities,
  preview/read-set identity, policy revisions and evaluator pins, snapshot,
  config/storage hashes, market identity/instruments/currency/timestamps and
  copied admission lease must all agree. Invented predecessor fields refuse.
- Original processing and current physical rows preserve inherited realized,
  unrealized, daily/cumulative P&L and daily/cumulative transaction costs. Exact
  owner execution deltas and persisted cash totals reconcile with fills; only
  incremental QT cash is charged. Price-unit implicit impact is not added as
  cash. The native independently rounded commission/slippage/total contract
  permits one Decimal8 atom between rounded component sum and total, while
  fill, persisted total and balance adjustments must match exactly.
- First-day finalization proves its anchor rather than an invented predecessor,
  adds settlement gross to inherited realized/daily/cumulative P&L and equity,
  retains unrealized P&L and already-charged costs, and preserves continuation
  v1/v2 shapes and zero-opening-day semantics.
- New real-PostgreSQL tests import native fixtures through explicit source,
  build and artifact paths, refuse an unowned existing schema before its
  disposable native fixture runs, and exercise actual native processing plus
  API SQL/publication/report/receipt proof. No proof implementation is mocked.
  A settlement-only case stops the native test before its separate continuation
  callback; a distinct case exercises the full continuation callback.

## Verification so far

- TDD: real native changed-choice/no-op processing succeeded while the original
  API loader returned no first-day evidence (two expected red failures).
- Eight synthetic PostgreSQL16 bridge cases passed in UTC and America/New_York:
  changed choice, no-op, actual next-day settlement, and tamper refusal. This
  includes 16 rehashed anchor/input/financial mutations and seven rehashed
  finalization provenance/financial mutations per relevant timezone case.
- Final fresh non-integration backend suite on commit `1d949df5`: **2,252
  passed**. Focused pure proof tests: 161 passed before one additional passing
  new-component test; the final first-day arithmetic subset has 17 passes.
- Isolated socket-only clusters verified database/user/data-directory/null
  server address and were stopped and removed with absence asserted.
- The bridge first passed on native `d3f5a508862bab17139ea77dfd6869887638a625`.
  The final fresh rerun on diagnostic build `48d4ff5` again passed all eight
  first-day/settlement cases; its two ordinary full-continuation cases reach
  the same native admission failure below.
- Rationale-bound confirmation prerequisite `3b3ad5af` was independently
  cherry-picked as `a0b3ec39`; the coordinator already owns that dependency.

## Explicit remaining gates / limits

- Full actual second-day confirmation succeeds, but native continuation
  currently refuses `qt_desk_unavailable:current_facts:qt_desk_source_unavailable:admit`
  in both UTC and America/New_York before reader assertions. These two cases
  remain ordinary failing tests, not skipped/xfail or silently waived. Native
  owner is diagnosing; full continuation proof is not yet claimed.
- Anchor bindings retain hashes, not full immutable archives of policy,
  configuration and storage-capability rows. This reader deliberately refuses
  when current witnesses no longer match the captured revisions/hashes. A
  later rotation can therefore make historical first-day proof unavailable;
  durable immutable witness archives would be needed to remove that limit.
- Bridge SQL runs as an owned synthetic administrator; API runtime-role grants
  were separately confirmed in the integrated role postlude, not executed in
  this new native bridge. API service/proof calls are real, but these tests are
  not an authenticated HTTP end-to-end browser test.
- No Docker execution, real market data, production readiness or activation is
  claimed. Existing environment-specific production attestation gates remain.
