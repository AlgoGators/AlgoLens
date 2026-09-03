# QT Platform — audit of the preview branch

**Date:** 2026-09-02 · **Branch:** `AlgoLens/qt-platform-preview` · **Method:** every feature driven in a browser and via curl against a production-shaped local Postgres, not inferred from reading code.

The short version: **the platform works, but it did not when this audit started.** Three of the bugs below would have made the core QT feature — a human editing a position through a risk gate — fail or silently pass on the first real use. None of them were visible to the unit suite, because the suite feeds the domain plain Python floats and a real database does not.

Everything in §1 is fixed and verified. §2 is what a demo environment needs that the first seed lacked. §3 was what remained open.

**Update, same day:** §3 has since been worked to completion. Every P0 and P1 item is fixed and verified, P2-a and P2-d are done, and P1-h turned out not to be a bug. What is left is §6 — two questions that are genuinely the team's to answer, not code.

---

## 1. Fixed in this audit — verified, not assumed

Each entry says what was wrong, why the tests missed it, and how it was verified. Ordered by severity.

### 1.1 Every real edit crashed: `Decimal + float` in the risk maths — **CRITICAL**
- **What:** `POST /portfolio/positions` returned 500 on every call. `evaluate_risk` summed the existing book (rows from NUMERIC columns arrive as `decimal.Decimal`) with the proposal (a `float`). Python refuses to add the two.
- **Why the suite missed it:** every test built the book from float literals. The mismatch only exists across a psycopg2 boundary.
- **Fix:** coerce at the repository boundary (`_plain_position`) in `fetch_qt_book` and `_fetch_existing_position`, and `float()` inside `_notional` so the domain is safe regardless of caller.
- **Verified:** curl 409 → 201; test `test_evaluate_risk_accepts_decimal_rows_from_the_database`.

### 1.2 The risk gate never fired for the normal edit — **CRITICAL**
- **What:** The UI sends no `average_price` on a quantity-only edit, meaning "keep it". The write path honoured that, but the **risk check was handed the raw proposal**, priced the position at zero notional, and passed everything. ES 12→20 against a $70k cap saved with `passed: true`.
- **Why the suite missed it:** the risk tests always supplied a price.
- **Fix:** `with_known_price()` — the proposal is priced from the existing row before evaluation. An explicit price is never overridden; a genuinely new symbol with no price stays unpriced.
- **Verified:** curl now returns 409 with `ES notional 105,605 exceeds its cap of 70,000`; three new tests.

### 1.3 Every quantity-only edit wiped the average price — **CRITICAL**
- **What:** the INSERT into `trading.positions` passed `normalized["average_price"]` (None) instead of the after-state, which had carried the existing price forward. The audit row recorded the correct price; the book lost it.
- **Consequence:** the next detail load crashed (1.4), and notional/VaR for that position became zero.
- **Fix:** INSERT writes `after["quantity"]` / `after.get("average_price")`.
- **Verified:** curl edit then `SELECT` shows `5280.25` retained; audit `before_px = after_px = 5280.25`.

### 1.4 A NULL price took the whole strategy detail page down — **HIGH**
- **What:** `transform_positions` did `float(None)`. One bad row → `GET /portfolio/strategy/<id>` 500 → dashboard error state.
- **Fix:** NULL price → `0.0` for the maths plus a `priceUnknown: true` flag on the position, so the row renders and the UI can say so. (Showing it properly is §3, item P1-e.)
- **Verified:** detail 200 before and after an edit; test `test_a_null_average_price_does_not_take_down_the_detail_view`.

### 1.5 Raw database errors leaked to clients as 400 — **HIGH (security hygiene)**
- **What:** incubation start/promote/retire wrapped psycopg2 errors as `IncubationError(f"Database error: {exc}")`, and the routes return `str(exc)`. Column names and SQL reached the browser, with a *client-error* status for a *server* fault. Same class as the CodeQL `py/stack-trace-exposure` alerts fixed in PR #80.
- **Fix:** `IncubationStorageError` → logged with traceback server-side, answered `500 {"error": "Incubation change could not be saved"}`.
- **Verified:** route test `test_storage_failure_is_a_500_with_a_fixed_message`.

### 1.6 Strategy Builder showed fabricated zeros for an unpublished strategy — **MEDIUM**
- **What:** a strategy the engine has not published for (the state right after a book move) reached the Builder maths with placeholder zeros: `VAL $0k · RET +0.0% · SR 0.00` and a `0.0% of portfolio` summary line — all reading as measurements.
- **Fix:** `computeCombinedMetrics` excludes `dataAvailable === false`; the selection card shows *awaiting engine data*.
- **Verified:** browser — "2 of 2 selected", Carry card shows the notice, summary excludes it.

### 1.7 Dev white-screen on every hot reload of the auth provider — **MEDIUM (dev only)**
- **What:** `AuthContext.tsx` exported both a component and the `useAuth` hook. React Fast Refresh cannot preserve such a module, so each hot update remounted the provider with a new context while consumers held the old hook → `useAuth must be used within an AuthProvider`, blank app until a full reload. This is why "I don't see it" happened twice today.
- **Fix:** hook moved to `useAuth.ts`; nine importers rewired.
- **Verified:** build clean, app reloads and logs in normally.

### 1.8 Fixed earlier today, listed for completeness
- Strategies with no engine row **vanished** from the dashboard and the fund headline silently shrank by their value — now listed as *awaiting engine data* with an explicit "Excludes N strategies…" notice.
- Sortino and information ratio were computed from hardcoded constants (`12.5`, `× 0.7`) and captioned "vs SPX" — now real, `null` when undefined.
- `$0` shown for a strategy the engine had not priced — now *awaiting engine data*.
- `portfolio_assignments.to_portfolio_id NOT NULL` made every book removal unrecordable → transaction rollback — now nullable.
- `RealDictCursor` rows accessed positionally — books listing 500'd.
- Move controls on the read-only Portfolio tab — removed; grouping collapsed by default.

---

## 2. Demo-environment gaps (not app bugs — but they hid the app bugs above)

The first local seed did not match the production `trading` schema closely enough for the write paths to run at all. Each of these produced a 500 that looked like an application failure:

| Missing from the first seed | What it broke |
|---|---|
| `positions.date` column + unique index on `(portfolio_id, strategy_id, strategy_name, date, symbol, portfolio_type)` | `write_qt_position` — Postgres rejects `ON CONFLICT` with no matching index |
| `strategy_registry.updated_at` | incubation start/promote/retire |
| `trading.strategy_lifecycle_log` | incubation audit insert |
| password on the seeded user | login |

All four are now in **`algolens-api/scripts/demo_seed.sql`**, with the schema the app creates lazily (books, memberships, assignment audit) declared in the same place so the shape is visible. The seed embeds the `admin@admin.com / admin` login; it exists only in that database.

**Lesson worth keeping:** unit tests with float fixtures gave 120+ green results while the feature was completely broken against Postgres. `tests/integration` now closes that gap, and the CI job fails if those tests *skip* rather than run — a missing service would otherwise drop the only coverage of the write path while the job stayed green.

---

## 3. Still open — ordered by when, then by speed

**How to read this:** bands are *when it must be done*. Inside a band, items are sorted fastest-first, so the top of each band is the best thing to pick up next. Effort: **S** < 1 h · **M** half a day · **L** multi-day · **D** = a decision someone has to make, not code.

### P0 — before the QT desk relies on this

| # | Item | Effort | Notes |
|---|---|---|---|
| ~~P0-a~~ | ~~Position response serialises numbers as strings~~ — **FIXED** | S | `jsonify` stringifies Decimal. Coerce in the serializer. Any client that parses these as numbers breaks. |
| ~~P0-b~~ | ~~Add `tsc --noEmit` to frontend CI~~ — **FIXED**, and it immediately caught that `Book`/`AssignmentRecord` were never declared | S | There is no `tsconfig.json` and no `typescript` dependency. Nothing typechecks. Today's `number \| null` widenings and placeholder shapes were verified by grep, not a compiler. |
| ~~P0-c~~ | ~~Integration test against Postgres~~ — **FIXED**: `tests/integration`, 4 cases driving the real write, plus a CI guard that fails if they silently skip | M | Would have caught 1.1, 1.2 and 1.3 outright. |
| ~~P0-d~~ | ~~Canonical migrations in trade-ngin~~ — **FIXED**: migration 009 + rollback; lazy DDL removed from the app | M | The app creates them lazily with `CREATE TABLE IF NOT EXISTS`. trade-ngin owns this schema (migrations 004/005). Lazy creation must not survive into production. |
| ~~P0-e~~ | ~~Portfolio tab grouping ignores multi-book membership~~ — **FIXED**, and it also stopped hiding incubating strategies (P1-i) | M | `ListPortfolios` buckets by `registry.portfolio_id` (primary only). A strategy in two books shows under one on the Portfolio tab and under both on Books. Same data, two answers. |

### P1 — this week

| # | Item | Effort | Notes |
|---|---|---|---|
| ~~P1-a~~ | ~~`IncubationDetail` shows `+0.00%` over an empty chart~~ — **FIXED**: "No trading days recorded yet" | S | |
| ~~P1-b~~ | ~~`priceUnknown` positions render `$0`~~ — **FIXED**: em dashes, excluded from the total, and the total says how many | S | |
| ~~P1-c~~ | ~~404 vs 400 decided by searching the message for "not found"~~ — **FIXED**: typed `StrategyNotInRegistry` | S | |
| ~~P1-d~~ | ~~`book_not_empty` is a bare `ValueError`~~ — **FIXED**: typed `BookNotEmpty` carrying the count | S | |
| ~~P1-e~~ | ~~"Add to book" records a hardcoded reason~~ — **FIXED**: required by the API, asked for by the form | S | |
| ~~P1-f~~ | ~~Override history rendered by nothing~~ — **FIXED**: on the positions tab, with a three-state risk column | M | |
| ~~P1-g~~ | ~~Incubation lifecycle is API-only~~ — **FIXED**: promote and retire on the detail view, with a partial-window warning | M | |
| ~~P1-h~~ | ~~`retired → incubating` vs membership freezing `retired`~~ — **NOT A BUG.** Different questions: a strategy may be retried; its *closed history* may never change books. Documented and pinned by a test so it is not "reconciled" later | D | |
| ~~P1-i~~ | ~~Fund headline silently excludes incubating strategies~~ — **FIXED** with P0-e: listed, marked, mock capital shown and excluded from totals | S | By design (mock capital), but there is no note. Same shape as the "Excludes N…" notice already added for unpublished ones. |

### P2 — later

| # | Item | Effort | Notes |
|---|---|---|---|
| ~~P2-a~~ | ~~Node 20 deprecation warnings~~ — **FIXED** in trade-ngin; versions read from the GitHub API, not guessed | S | |
| P2-b | The `history_discontinuity` warning names a real problem the feature does not solve | **L / D** | Attribution across a book move still spans two compositions. Options: forbid moves on live strategies, or snapshot-and-restart the curve at the move. |
| P2-c | `refactor/models-range-filter` deletes the three-stream read side (220 lines, all of `AlphaAttribution.tsx`) | **D** | Still on the remote. Merging it removes half of this feature. Nobody has confirmed whether the deletion was intended. |
| ~~P2-d~~ | ~~Demo seed is not part of any test run~~ — **SUPERSEDED**: `tests/integration` builds its own isolated schema per test, so it needs no seed and cannot be polluted by one | S | |

---

## 4. What was verified working, in the browser, today

| Feature | Evidence |
|---|---|
| Login, dashboard load, fund total | `$541,200`, notice "Excludes 1 strategy the engine has not published results for yet" |
| Portfolio tab grouping | collapsed by default, expands, **zero** move controls |
| Strategy detail | 200; 4 Adjust buttons; attribution chart present |
| **Position edit — breach path** | Adjust ES 12→20 → amber banner "ES notional 105,605 exceeds its cap of 70,000" → *Override and save* → row shows 20; audit `overrode_risk = t` |
| **Position edit — clean path** | ES 20→12 → saved with no banner; row shows 12 |
| Strategy Builder | "2 of 2 selected"; placeholder card reads *awaiting engine data*; excluded from value and summary |
| Books — create / add / remove / delete | created AUDIT_BOOK → added Trend Following (non-primary) → removal warned → *Remove anyway* → removed → deleted when empty |
| Books — last-book guard | removing Breakout from its only book: refused, **no override offered** |
| Books — primary badges | 3 (one per strategy) |
| Incubation — list & detail | Breakout: $250,000 mock capital, 0d/120d, detail renders (empty chart — P1-a) |
| Incubation — lifecycle via API | live→incubating→live→incubating→retired→incubating; five audit rows; domain errors clean, no SQL text |

Test counts after this audit: **126 backend** (was 107), **82 frontend** (was 81), production build clean.

---

## 5. Things I decided without asking, so you can reverse them

- **NULL price → `0.0` + `priceUnknown` flag** rather than hiding the row. Hiding positions is worse than a flagged zero; P1-b turns the flag into a visible "—".
- **Storage failures → 500 with a fixed message.** The detail is in the server log. If you want the message to carry a correlation id, that is a two-line change.
- **`retired → incubating` left as-is.** It is pre-existing behaviour; flagged as P1-h rather than changed unilaterally.
- **Demo seed committed to `algolens-api/scripts/`** with the `admin/admin` login. It is local-only and documented as such; delete the user block if you would rather it were not in the repo.

---

## 6. What is left, and why it is not code

Two items from §3 remain open. Neither is a defect, and neither should be closed by whoever picks this up next without the team actually deciding.

### P2-b — the history-discontinuity warning describes a problem the feature does not solve

Moving or removing a strategy from a book makes that book's history discontinuous: every number computed across the boundary — cumulative return, drawdown, and the qt/system/benchmark attribution this branch just fixed — spans two different compositions. The platform now *states* that cost, records an acknowledgement, and audits who accepted it. It does not repair the maths.

Three ways out, in rising order of cost:

1. **Forbid book changes on live strategies.** Simplest, and defensible: assign at creation, retire and re-create to move. Costs flexibility the desk may want.
2. **Snapshot and restart the curve at the boundary.** The book's history becomes explicitly segmented, and every chart has to learn about segments.
3. **Leave it as it is** — the cost is stated, acknowledged and audited, and readers are trusted to know a composition change happened.

Option 3 is what ships today. It is a reasonable answer, but it should be a chosen one rather than a default, because the moment there is a year of live history the cost of changing it rises sharply.

### P2-c — `refactor/models-range-filter` deletes the other half of this feature

That branch is still on the remote and removes 220 lines: the stream constants and the whole of `AlphaAttribution.tsx`. When the edit surface was going to live in another repo, losing AlgoLens's read side was survivable. It is not now — merging it would delete the three-stream comparison that the position edit path exists to make meaningful.

Nobody has confirmed whether the deletion was intended or fell out of an unrelated models refactor. That needs an answer from whoever wrote it before it goes near `main`.

---

## 7. Second pass — an independent review of everything §1–§5 built

Everything above was written by the same hands that wrote the code. This pass had four
separate reviewers read the branch cold against the stated design intent — domain and
application, infrastructure and HTTP, frontend, and docs/CI/migrations — and then every
finding was verified against the code before being fixed. Ranked by what it would have cost.

| # | Finding | Fixed by | Proof |
|---|---|---|---|
| 7.1 | **The integration suite drops the `trading` schema of whatever database it is pointed at, and its own docstring said to point it at the demo cluster.** It did exactly that mid-session and wiped the seeded demo. | Fixture marks the schema it builds and refuses to drop one it did not create; docstring now says to use a database of its own. | Pointed at `algolens_demo`: refused, 11 tables and 3 strategies intact. Pointed at `algolens_test`: 7 pass. |
| 7.2 | `delete_book` counted only primaries, so a book holding a strategy's **non-primary** membership could be deleted out from under its positions and limits. | Occupancy is the union of primaries and memberships. | `test_a_book_holding_a_non_primary_member_cannot_be_deleted` (Postgres) |
| 7.3 | `ChangeBookMembership` raised `AssignmentValidationError` for an unknown action **without importing it** — a `NameError` masked as a generic 500. No test had ever called the use case. | Import added; `tests/test_book_membership_use_case.py` drives the use case through every branch. | 8 new tests |
| 7.4 | The `409 ambiguous_book` reply was handled by nothing in the UI: the `books` list was discarded and the user saw a raw error with no way to answer. | `savePosition` returns `needs_book`; the editor gains a `needs_book` phase and a book picker, and resubmits with the choice. | State-machine tests; `tsc` clean |
| 7.5 | Strategy cards showed **+0.00% return, 0.00 Sharpe, 0.0% volatility** for a strategy the engine had not published, next to "awaiting engine data" for its value. | All four tiles honour `dataAvailable === false`. | `StrategyList.tsx` |
| 7.6 | Migration **`008` collides**: `feat/config-from-database` already reserved `008_strategy_config.sql`, and the trade-ngin README described that file rather than the one on this branch. | Renumbered to `009_books_and_membership.sql`; README lists both; every reference updated. | `git mv`; grep for `008` |
| 7.7 | `QT_PLATFORM_PREVIEW.md` still said there was no assignment UI, no override history view, and no typechecking — all false for six commits. | Rewritten to describe the branch as it is. | — |
| 7.8 | `resolve_target_book` with a blank primary and no memberships raised `AmbiguousBook` with **zero** candidates, telling the client to choose between nothing. | Distinct `strategy_has_no_book` validation error. | `TestBookResolutionEdges` |
| 7.9 | Book names were compared **case-sensitively** against rows nothing forces to upper case, so a hand-written `macro_book` row would be reported as not-a-member and then duplicated under `MACRO_BOOK`. | `match_book` compares without case and returns the stored spelling; every membership and edit path writes with that spelling. | Domain + use-case tests |
| 7.10 | `evaluate_risk` treated a **published envelope with no limits** (`{}`) as "not checked", the same as an outage. | `is None`, not falsiness. `{}` is a check that found nothing. | `TestEmptyEnvelope` |
| 7.11 | The demo seed and the integration fixture declared `position_overrides` with **every constraint stripped** (nullable `before_state`, untyped `user_id`, no `CHECK`s), so a write production would refuse passed here. | Both now carry migration 004's constraints verbatim. The write path passes against them. | 7 integration tests |
| 7.12 | Removing a strategy's primary book repointed the primary **silently**; the caller learned nothing. | `remove_membership` reports `primary_portfolio_id`; the use case and serialiser pass it through. | `test_removing_the_primary_book_repoints_it_and_says_so` |
| 7.13 | `StrategyRegistryPort` declared 4 methods; the use cases called 13. | Port now declares every method the application layer calls. | `ports.py` |
| 7.14 | The audit trail of a **retired** strategy was unreadable: `ListPositionOverrides` used the live-only lookup. | Uses `get_any`. Retirement must not lose the record of what was done. | `use_cases.py` |
| 7.15 | `computeCombinedMetrics` divided by `totalInvested` / `totalValue` unguarded; a zero-invested selection rendered `NaN%`. | `share()` helper, 0 when the denominator is 0. | New vitest case |
| 7.16 | A fund whose strategies were all still awaiting engine data was shown the **empty-portfolio screen**, so the "excludes N strategies" notice could never render. | The dashboard gate counts awaiting strategies as something to show. | `Dashboard.tsx` |
| 7.17 | `portfolioApi.ts` carried a byte-for-byte private copy of `httpClient.fetchWithAuth`. | Deleted; nine call sites use the shared one. | `tsc` |
| 7.18 | Cosmetic: unused `useContext` import; seed comment said pbkdf2 for a scrypt hash. | Fixed. | — |
| 7.19 | **Every blue button added since the DDD split was invisible.** `src/index.css` was a 39KB Tailwind 4.1.3 output committed at #71, and nothing compiled Tailwind at build time, so any utility a later component used that the snapshot lacked (`bg-blue-600`, `bg-amber-600`, `disabled:opacity-40`, `bg-black/50`, `normal-case`, ...) rendered as nothing. "Add", "Create book", "Promote to live", the modal Save buttons and the modal backdrop were white on white. Found when John asked how to add a strategy to a book and the form showed only Cancel. | Tailwind 4.3.3 + `@tailwindcss/vite` compile the sheet from source; `index.css` is now `@import "tailwindcss"` plus the existing `styles/globals.css` tokens. | Add / Create book render, computed `bg` is blue and disabled opacity 0.4; add and remove driven in the browser; build 92KB CSS |
| 7.20 | **A strategy in several books could only ever be looked at in one of them.** The detail endpoint read `strategy_registry.portfolio_id` unconditionally, so every book except the primary was unreachable: the banner said the strategy also traded elsewhere and offered no way to see it, and the editor could only ever write to the primary. The `ambiguous_book` picker added in 7.4 was therefore unreachable too. Found when John asked why the book could not be chosen in the Add position dialog. | `GET /portfolio/strategy/<id>` takes an optional `portfolio_id`, validated against membership and matched without case; the detail view has a book switcher that rescopes positions, the audit trail and the editor. | Driven in the browser: switching books swaps the universe, an edit made on the second book lands there and is audited there |
| 7.21 | Refreshing after an edit flipped the dashboard into its loading state, unmounting the strategy view and discarding which book was on screen. | The post-edit re-read is silent; only the first load shows the spinner. | Saved while on the second book; the view stays on it |
| 7.22 | **The manual position write could not have worked in production at all.** The INSERT omitted `daily_unrealized_pnl`, `daily_realized_pnl` and `last_update`, which are NOT NULL with no default in the schema trade-ngin ships. Every manual edit would have returned 500 on first use. Invisible locally because `demo_seed.sql` and the integration fixture each invented a looser `positions` table. | INSERT supplies all three (0, 0, now()); ON CONFLICT still leaves them alone, since they belong to the engine. Both fixtures now use the shipped shape. | Built a database from trade-ngin's own baseline plus migrations 001-009 and drove the real API against it: edit 201, engine PnL and last_update preserved |
| 7.23 | `average_price` is NOT NULL in production, but opening a new position with a blank price wrote NULL. | Refused in the domain with a message that explains it, instead of a constraint violation. | 400 `price_required_for_new_position` against the production-shaped database |
| 7.24 | **The three tables nothing defines were still unverified.** `strategy_registry`, `live_results` and `executions` are created by no migration and no test in either repository, so AlgoLens's model of them was a guess with nothing to check it against. | Declared the contract in `schema_contract.py`, sourced per table from the engine's own INSERT statements in `postgres_database.cpp` and from trade-ngin's migration test. `scripts/check_schema.py` checks any database against it; an integration test checks the demo seed against it on every run. `strategy_registry` is explicitly marked UNVERIFIED, and a test fails if that marker is removed without evidence. | Checker catches both a missing read column and an unsupplied NOT NULL column; 10 unit tests guard the checker itself |
| 7.25 | The UI's Gross Leverage read `live_results.gross_leverage`, a column the engine explicitly stopped writing; its value now goes to `portfolio_leverage`. The figure shown was whatever the column held on the day it was abandoned. | Falls back to `portfolio_leverage` when the dead column is null, with the engine's comment cited. | 170 backend tests |
| 7.26 | The new seed-contract fixture dropped schemas without the ownership guard added in 7.1, reintroducing the same footgun in a second place. | Guard moved to `tests/integration/conftest.py` and used by both fixtures. | Pointing ALGOLENS_TEST_DB at the demo fails both fixtures and leaves all 11 tables intact |

### Reviewed and deliberately left

- **Position edits on retired strategies are refused** (the live-only `get`). A retired strategy has no capital to edit; only its audit trail needs to stay readable, and now does.
- **Book and position writers let raw `psycopg2` errors propagate** to the route's generic 500, rather than wrapping them as the incubation writers do. The client never sees database text either way; unifying the pattern is a refactor, not a fix.
- **The HTTP adapter imports the dependency factory and two domain exception classes.** `test_domain_boundaries.py` permits both and they are the composition root's job. Tightening the rule is a team decision.
- **`services/` under `algolens-api` is dead code with passing tests**, present on `main` since the DDD split (#71). Out of scope here; worth deleting in its own PR.
- **No React component tests.** The state machines that make the acknowledge-once gate safe are tested; the component wiring is verified by driving the app. Adding React Testing Library is a dependency decision.

### Verified after the fixes

- 153 backend unit tests, 7 Postgres integration tests, 88 frontend tests, `tsc --noEmit` clean.
- Tailwind is compiled at build time; the frozen stylesheet is gone. Dashboard, Books, strategy detail and the edit modal checked in the browser after the switch.
- Demo database rebuilt from the seed plus migration 009 and back at baseline.
