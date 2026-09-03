# QT Platform — preview branch

**This branch is for feedback, not for merging.** It exists so the QT desk can use the
manual position path end to end and tell us what is wrong with it before we finalise the
individual pull requests.

It will be deleted and rebuilt from the PRs after review. Do not branch off it, and do not
merge it into `main` — the real work lands through the PRs listed below.

This file exists only on this branch.

---

## What is in it

`AlgoLens/qt-platform-preview` = `main` + these two, merged, plus the work listed under
"Built on the branch" below:

| PR | Branch | What it adds |
|---|---|---|
| [#80](https://github.com/AlgoGators/AlgoLens/pull/80) | `port/qt-position-edit` | The position edit path — the write side, the risk check, the audit trail, and the editor UI |
| [#81](https://github.com/AlgoGators/AlgoLens/pull/81) | `fix/information-ratio-real-benchmark` | Sortino and information ratio computed from real data instead of hardcoded constants |

The engine half is a **separate branch in a separate repo**, because the platform spans both:

`trade-ngin/qt-platform-preview` = `main` + [#56](https://github.com/AlgoGators/trade-ngin/pull/56) (which already contains [#55](https://github.com/AlgoGators/trade-ngin/pull/55)) + migration `009_books_and_membership.sql`.

That is what publishes the risk limits this app checks edits against, writes the three
portfolio streams, and owns the schema behind the Books tab.

### Built on the branch

These were built directly on the preview after the PRs merged, driven by what the demo
exposed. Each will be cut into its own PR after review.

- **Books tab.** Define a book, put strategies in it, take them out. Every change takes a
  reason and lands in an append-only audit table.
- **A strategy can be in several books.** `strategy_registry.portfolio_id` is now the
  *primary* book; membership is additive on top of it.
- **Portfolio grouping** on the Portfolio tab, collapsible and read-only. It marks
  incubating strategies, strategies that are "also here" from another book, and mock
  capital that is deliberately excluded from fund totals.
- **Book-aware position edits.** The editor names the book it writes to. A strategy in
  several books with no book named gets `409 ambiguous_book` and a picker, never a guess.
- **Incubation promote / retire** from the UI, with a warning when the observation window
  is not complete.
- **Override history** rendered on the strategy detail view, with a three-state risk
  column: passed / overridden / not checked.
- **Honest nulls.** A strategy the engine has not published yet shows "awaiting engine
  data", not zeros, and is excluded from every aggregate.

## Audit and local database

**Read [`QT_PLATFORM_AUDIT.md`](QT_PLATFORM_AUDIT.md) before relying on this branch.** It
records two passes: the first found seven bugs by driving every feature against a real
Postgres, three of which would have broken or silently bypassed the risk gate on first
use. The second, an independent review of everything the first pass built, found another
set — including one that would have wiped the demo database from the test suite. All are
fixed; the two decisions that are genuinely the team's are listed at the end of that file.

To run against a local database with realistic data, use
`algolens-api/scripts/demo_seed.sql`, then apply trade-ngin migration 009. Login is
`admin@admin.com` / `admin`, local only.

**Do not point `ALGOLENS_TEST_DB` at the demo database.** The integration tests drop and
recreate the `trading` schema. They now refuse to run against a schema they did not create,
but give them a database of their own regardless.

## Verified on this branch

- 153 backend unit tests pass
- 7 integration tests pass against a real Postgres, and CI fails if they are skipped
- 88 frontend tests pass
- `tsc --noEmit` is clean and runs in CI before the build

---

## Running it

You need the trade-ngin migrations applied to whatever database you point at. In order:

```
001_add_portfolio_type.sql
002_backfill_qt_from_system.sql
003_add_benchmark_stream.sql
004_position_overrides_audit.sql
005_risk_limits.sql
006_run_inputs_and_rebench_stream.sql
007_benchmark_frozen_shadow_stream.sql
009_books_and_membership.sql
```

`008` is `008_strategy_config.sql` on trade-ngin PR #60's branch, which is why the books
migration is `009`. Neither depends on the other.

Then:

```bash
make install
make dev
```

The API needs `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` and `JWT_SECRET_KEY`.

**To get the edit controls without setting up real auth**, run the API with:

```bash
DEV_MODE=1 DEV_USER_ROLE=admin FLASK_ENV=development
```

then `POST /auth/dev-login`. This bypasses authentication entirely — it refuses to run when
`FLASK_ENV=production`, but never point it at anything real regardless.

The edit controls only appear for roles `admin` or `general_member`. Subscriber-facing views
pass no `strategyId` and stay read-only, which is deliberate — the backend enforces the same
rule with `@internal_only`, so the UI check is only there to avoid offering a button that
would come back 403.

---

## Two things that will look broken and are not

**1. Every risk check will say "not checked" until `trading.risk_limits` has rows in it.**

Migration `005` creates the table. It does not fill it — the engine fills it, and that is
trade-ngin #56, which is not merged. Until then `evaluate_risk` returns
`{"evaluated": false}` and the audit row records that the check did not run.

That is the intended behaviour: an unreachable risk envelope must be visible in the audit
trail as "not checked", never as "checked and fine". A *published* envelope with no limits
in it is different: that is a check that found nothing to breach, and reads as "passed".

To see the gate work, seed a row by hand:

```sql
INSERT INTO trading.risk_limits (strategy_id, portfolio_id, limits) VALUES
  ('trendfollowing', 'CONSERVATIVE_PORTFOLIO',
   '{"max_gross_notional": 750000, "max_position_count": 40,
     "max_symbol_notional": {"ES": 200000}}'::jsonb);
```

Then edit ES to something over $200k and you should get the amber breach banner.

**2. The Sortino and info-ratio tiles will show an em dash, and the attribution chart will
draw three lines on top of each other.**

Both are correct. All three portfolio streams currently hold identical numbers because
nothing has ever written an edit into `qt` — so there is no tracking error to divide by, and
nothing to attribute. The moment someone makes the first edit through this branch, they
diverge. Reporting `0.00` instead would read as "the desk added nothing", which is a
different and false claim.

---

## How strategies map to books now

`portfolio_id` scopes **every** query in the portfolio repositories — equity curves,
positions, executions, risk limits. Two strategies with different books genuinely have
separate ledgers, and one strategy in two books has two.

- **Primary book.** `strategy_registry.portfolio_id`. The single answer wherever one is
  needed, and what the engine reads. It must always name a book the strategy is actually
  in; the platform repoints it when the primary book is removed and tells you where it went.
- **Membership.** `trading.strategy_book_memberships`, additive over the primary. Adding a
  strategy to a book takes nothing away and needs only a reason. Removing it from a book
  makes that book's history discontinuous from today, so it asks for an acknowledgement
  first, and it refuses to remove the last book outright.
- **Retired strategies are frozen for book changes.** Their books are closed; moving them
  would rewrite history already reported. Their audit trail stays readable.
- **Deleting a book** is refused while any strategy is in it, primary or not.
- **Editing a position** names the book. The positions table says which book it is showing
  and warns when the strategy also trades elsewhere. An edit that cannot be resolved to one
  book is refused with the list of candidates, and the editor asks.

Book ids are upper-cased on the way in. Rows that predate that convention are matched
without regard to case, and written back with the spelling the database already holds.

---

## What we most want feedback on

1. **The breach flow.** A breaching edit returns 409 and the UI stops and waits — you have to
   click "Override and save" a second time. Is one extra click the right amount of friction,
   or too much / too little?
2. **Is "reason" doing its job?** It is mandatory and free-text, on position edits and on
   every book change. Read a few back and see whether they will still mean anything in six
   months, or whether this should be a structured dropdown.
3. **The diff panel** shows quantity and average price before/after. Is anything missing that
   you would want to see before committing a change?
4. **Blank average price means "leave it alone", not "clear it".** Is that what you expect?
5. **One strategy, several books.** Is the primary-book model right, or should a strategy
   in two books be two registry rows? The per-book positions and limits already work either
   way; the question is what the desk finds natural.
6. **Anything the audit trail should record that it does not.** Right now:
   who, when, strategy, symbol, before, after, reason, risk verdict, and whether the verdict
   was acknowledged; and for book changes, from, to, lifecycle at the time, and consequences.

Open a PR comment on #80, or just tell John.

---

## Known gaps, already understood

- The gate is advisory. Per DECISION-1 a breach never hard-blocks — it forces an
  acknowledgement and records it. That decision is still formally open.
- Attribution across a book change is stated and acknowledged, not repaired. The options
  are in `QT_PLATFORM_AUDIT.md` §6.
- The `refactor/models-range-filter` branch deletes the three-stream read side (220 lines,
  including all of `AlphaAttribution.tsx`). If that lands, it removes the other half of this
  feature. Nobody has confirmed whether that deletion is intended — it needs an answer before
  it goes anywhere near `main`.
- Component-level React tests do not exist; the pure state machines are tested, the wiring
  is verified by driving the app. Adding React Testing Library is a separate decision.
