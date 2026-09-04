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
| 7.27 | **The risk gate checked limits the engine never publishes.** It looked for `max_gross_notional`, `max_position_count` and `max_symbol_notional`. trade-ngin's `store_risk_limits` header states it deliberately publishes none of those, because it enforces leverage ratios and per-symbol CONTRACT caps instead. Against a real envelope the gate would find no key it understood, report no breaches and record **passed** — a green light derived from limits nobody set. It only looked functional because the demo seed invented the keys the code was looking for. | Checks `max_symbol_position_contracts`, `max_gross_leverage` and `max_net_leverage`; legacy dollar caps still honoured when present; an envelope with no recognised key is reported as not evaluated, never passed. The verdict now carries `checked`, naming which limits were actually compared. | Against the live demo: 8 contracts passes, 14 breaches its cap of 10, acknowledgement still required once |
| 7.28 | **Every futures exposure was understated by the contract size.** Notional was `quantity x entry price`, omitting the multiplier. Twelve ES read as $63,363 against a true $3,186,450. The same figure feeds the risk gate, so limits were compared against numbers ~50x too small. | `notional = quantity x market price x contract size`, the formula trade-ngin uses. Contract sizes read from `metadata.contract_metadata."Contract Size"`, the table its InstrumentRegistry reads. | Demo book totals $8,167,795 where it previously showed $173,809 |
| 7.29 | The column labelled **Market Price** displayed the average entry price. There was no market price anywhere in the app. | Latest close read from `futures_data.ohlcv_1d`, the table data-ngin writes and trade-ngin reads, using the engine's own `DISTINCT ON (symbol) ... ORDER BY symbol, time DESC` query. Unknown prices render as an em dash rather than falling back to cost basis. | Browser: ES shows 5,310.75 market against 5,280.25 entry |
| 7.30 | Symbols were upper-cased whole, turning `ES.v.0` into `ES.V.0`. Continuous-contract symbols pass from data-ngin through `trading.positions` verbatim with a lower-case roll marker, so an edit to a held position matched no row, was treated as opening a new one, and would have written a duplicate under a symbol the engine never uses. | Root upper-cased, roll suffix preserved. | `es.v.0`, `ES.V.0` and `ES.v.0` all normalise to `ES.v.0` |
| 7.31 | **The News tab was entirely fabricated.** Static markup claiming a 27.3% fund return, +8.1% alpha versus the S&P 500, per-strategy returns, Fed rates and CPI, shown to every logged-in member and formatted exactly like the real figures on the Portfolio tab. | Replaced with an honest empty state. There is no feed behind the tab and it now says so. | Screen carries no numbers |
| 7.32 | **Privacy settings claimed Two-Factor Authentication was ON for every account.** Component state seeded `true`, backed by no endpoint; a toggle the user flipped was forgotten on unmount. | All four controls show `not configured` until something real backs them. | No security state is asserted |
| 7.33 | Incubation showed a hardcoded `120 days` observation window although `window_days` is per strategy, and folded strategies with no mock capital into the headline total as $0. `formatMockCapital(null)` returned `$0`, stating an allocation of nothing where none was set. | Window derived from the data, shown as a range when strategies disagree; the total excludes unset figures and says how many; unknown capital renders as an em dash. | 89 frontend tests |
| 7.34 | The share column read 588% because it divided exposure by portfolio VALUE while its own footer totalled exposure. | Both use the same denominator. | Shares sum to 100% |
| 7.35 | The bell asserted **"Daily Trading Report Available"** on a clock: any weekday after 09:30 EST, weekends and holidays included, with an unread dot indistinguishable from a real alert. Nothing checked that a report existed. | Removed. No endpoint reports whether one was generated, so the bell no longer claims one was. | Dashboard shows no unread marker |
| 7.36 | **A built-in strategy served whenever the registry read failed or the table was empty.** `DEFAULT_REGISTRY` was one "Trend Following" with $500,000 of initial equity, managed by "AlgoLens System". A connection blip produced a fabricated strategy card with fabricated capital laid over whatever `live_results` happened to match, and nothing in the response said so. A test asserted this behaviour. It was a mock database wearing the real one's clothes. | Removed. An empty table is an empty list; a failed read raises and the route returns a database error. `initial_equity` NULL stays unknown instead of becoming $500,000, and a strategy with unknown starting equity reports `invested`, `return` and `returnPercent` as null. | 180 backend tests; the test that locked the fallback in now asserts the error |
| 7.37 | Eleven engine metrics passed through `float_or_default`, which turned a NULL from `live_results` into 0. The UI then showed "$0 margin posted", "0.00x leverage", "$0 cash" as measurements. | `float_or_none`; nulls reach the client as null and render as an em dash. `float_or_default` deleted so it cannot be reintroduced. | NULLed `margin_posted` and `cash_available` in the demo: API returns null, Financial Analysis tab shows — for both |
| 7.38 | `compute_return_stats` reported best day, worst day, win rate, average win/loss and profit factor as 0 when there was nothing to measure, and profit factor as 0 for a book with gains and no losses (which is undefined, not zero). `compute_sharpe` returned 0 when volatility was 0. | All undefined cases return null. | Unit tests |
| 7.39 | The Sharpe tile's tooltip stated the formula subtracts a risk-free rate. The computation never has: the engine publishes no Sharpe and no risk-free rate exists in any source, so it is return over volatility at 0%. The Win Rate tooltip said "winning trades"; it is winning DAYS on the equity curve. | Tooltips state what is actually computed. Sharpe tile in the builder says "0% risk-free". | — |
| 7.40 | Closed lots (`transform_finalized`) turned an unknown entry or exit price into $0.00 and an unknown realised P&L into 0, and used yesterday's entry price as today's "exit" price for a lot that was gone. | Unknown stays null. | Unit tests |
| 7.41 | **Strategy Builder combined volatility, Sharpe, drawdown and win rate were value-weighted averages of each strategy's own figure**, presented under the same labels as the real thing. The volatility of a combined book depends on how its parts co-move; two offsetting strategies would have shown high volatility where the book was flat. | Computed from the combined equity curve, the way Sortino and the information ratio already were; null when the curve is too short. | Test: two opposing curves combine to ~0 volatility and ~0 drawdown |
| 7.42 | Builder VaR was derived from that weighted-average volatility and rendered as a dollar figure regardless. | Null when combined volatility is unknown; otherwise from the curve-derived figure. | tsc |
| 7.43 | `StrategySummary` divided by a zero portfolio value and printed `NaN% of portfolio`. | Guarded; unknown share says so. | — |
| 7.44 | Account settings rendered five controls (change password, tax documents, bank accounts, deactivate, close) as live buttons with no handler. Same class as the fake 2FA toggle. | Disabled and captioned "Not available yet". | — |
| 7.45 | Tooltips asserted "above 1 is good, above 2 is excellent" and "a 60%+ win rate is generally considered good": rules of thumb the fund never set, shown as evaluative fact. | Removed; tooltips describe the metric, not a verdict on it. | — |
| 7.46 | Dead code carrying the same fabrications: `_notional` (unknown price → $0 exposure) in the risk module, `strategy_config_from_mapping` (NULL equity → $500,000), the unreachable `ReassignPortfolioModal`, a captured Microsoft OAuth URL with a real client id in `Header.tsx`, and a frontend default of 120 days that would have silently replaced a missing `window_days`. | All removed. The frontend never substitutes a window; the API is its only source. | tsc; grep |
| 7.47 | **The demo's engine results were hand-typed literals that contradicted the series they summarised.** `current_portfolio_value` sat $3,453 away from the equity curve's last point, and volatility claimed 12.6% where the curve's actual annualised volatility was 2.1%. The chart and the tiles beside it described different books. | `live_results` is now derived in the seed from the curve, the positions, the market prices and the executions. Fields with no basis in the data (margin posted, equity-to-margin, cushion, cash available) are NULL, which the app renders as unknown. | Every derived field reconciles to its source with a difference of exactly 0 |
| 7.48 | The equity curve was a smooth drift plus one sine wave, so derived volatility came out near 2% and the Sharpe ratio built on it exceeded 12. A demo that implies impossible statistics teaches the reader to disbelieve the tiles. | The curve is built from daily returns at a target annualised volatility per strategy, using deterministic shocks derived from md5 so the seed is reproducible. | Volatilities land within ~1pt of target; Sharpe ratios 4.6, 2.6, 0.05 |
| 7.49 | **Contract sizes were wrong for treasuries and grains.** Seeded from trade-ngin's fallback list, which holds underlying units, they were used as price multipliers: forty ZN read as $449,400,000 against a $264,000 book. ZN and ZB are quoted as a percentage of par on $100,000 face, so a point is $1,000; ZS is quoted in cents on 5,000 bushels, so a point is $50. | Point values seeded. Flagged for the engine team: anything using that fallback list as a price multiplier inherits the same 100x error. | Carry's exposure falls from $531M to $8.3M; leverage 31x |
| 7.50 | The curve's first point did not equal the registry's `initial_equity`, so a return measured against the curve differed from one measured against the registry: the card showed +11.67% where the list endpoint said +12.08%. | Day zero carries no return, so the first point IS the starting equity. | Difference exactly 0 for all four strategies |
| 7.51 | **Every period return on every chart was one bar short.** The cutoff carried the current clock time, so the oldest daily bar in the window fell just outside it: "1M" measured 29 days and reported +2.06% where the full month was +2.69%. | Cutoff set to midnight in all three components that slice by period. | 1M now reports +2.70%, matching the database |
| 7.52 | Execution notional was `quantity x price`, omitting the contract size: four ES at 5,276 read as $21,104 where the fill is worth $1,055,200. The same omission that understated position exposure. | Priced at contract value; unknown contract size renders as unknown and the total says how many fills it excluded. | ES fill now $1,055,200 |
| 7.53 | **Top Holdings weights reached 407%** under a column headed WEIGHT. Asset values are notional exposure; the denominator was portfolio equity. | Share of total exposure, so the column sums to 100. | Weights now 24.5%, 17.3%, 16.3% |
| 7.54 | **The information ratio read 37,874.** The benchmark stream differed from the book by a constant drift, so tracking error was floating-point dust and the ratio divided by it. | The ratio refuses a tracking error under a basis point. The seed gives the benchmark its own shocks, so it has real tracking error; qt and system stay identical, because nothing has edited qt. | Ratio now 1.73; qt and system verified identical |
| 7.55 | Max Drawdown rendered as **"+4.18%"**, prefixed and coloured as a gain, under a heading that means the worst peak-to-trough fall. Currency figures rendered with three decimals ($58,338.552) because the format set a minimum but no maximum. | Drawdown carries no gain styling; 18 currency formats pinned to cents. | Reads 4.18% and $58,338.55 |
| 7.56 | **"Today's Positions" showed every symbol the strategy had ever held.** The query took the latest row per symbol with no date predicate. `trading.positions` holds one row per open position per day, and the engine writes nothing at all for a position that closed -- not even a zero-quantity row -- so a closed lot stayed in the view forever, frozen at the last day it was open. The `quantity != 0` guard did nothing: there is no row to be zero. Total notional, every position weight, and the current book the risk gate checks an edit against all inherited it. | Both position queries read a dated snapshot: the latest `date` for that strategy and book, and for the comparison, the one before it. | Postgres integration tests; a lot closed yesterday leaves the view |
| 7.57 | The finalized-positions panel asked for `CURRENT_DATE - 1` literally, so it had nothing to compare against every Monday and after every holiday -- markets shut, the engine writes no rows, and the panel went blank with no explanation. | "The previous snapshot", which is the question the panel is actually asking. | Integration test across a weekend gap |
| 7.58 | **`FinalizedPosition` was typed with non-null prices while the API already sent null**, and three renders called `.toFixed` on them. The first lot to close without a published exit price would have thrown and taken the Trading tab down; the P&L total and the per-symbol chart would have gone `NaN` first. The demo never caught it because yesterday's positions were a verbatim copy of today's, so the panel was permanently empty -- "Total P&L $0.00" over no rows. | Types match the wire. Unknown renders as an em dash, the total counts only settled lots and says how many it left out. The seed now closes one lot and resizes another, so the path is exercised. | Frontend + backend tests; ZB renders "—" for its exit |
| 7.59 | **AlgoLens recomputed nine metrics the engine already publishes** -- Sharpe, Sortino, max drawdown, win rate, average win, average loss, profit factor, best day, worst day -- from a 90-point equity curve, and showed the results under the same names. The dashboard could disagree with the engine about the engine's own book with nothing on screen saying which number the reader had. | The published figure wins; the local computation is the fallback for a row written before the engine published that column. Sortino and downside deviation, which the engine publishes and AlgoLens never showed, are now available. | `published_or_computed` tests; tiles match `trading.live_results` row for row |
| 7.60 | `avg_win` and `avg_loss` are the engine's mean daily **percentage** return on winning and losing days. AlgoLens computed a mean daily **dollar** change and rendered it with a currency symbol -- a different quantity wearing the same label. | The engine's definition, rendered as a percentage. | Reads 0.78% / 0.55%, matching the row |
| 7.61 | **"Net P&L" was the return since inception**, sitting as the fourth card of a P&L Breakdown whose other three are unrealised P&L, realised P&L and commissions -- a layout that invites the reader to add them. On the demo book it read $92,405.72 next to three figures summing to $7,259.40. | Net P&L is those three. The return since inception keeps its home in the header beside the chart. | Reads $7,259.40 = $6,330.00 + $950.00 - $20.60 |
| 7.62 | "Total Trades" was a count of **today's fills**. `trading.live_results` carries no lifetime trade count; the engine removed `total_trades` pending closing-trade logic. The Strategy Builder also captioned a day-based win rate with it, inviting it to be read as a share of winning trades. | Renamed "Fills Today" everywhere. The win rate is captioned "of daily returns". | Reads "Fills Today 2" |
| 7.63 | **`trading.live_results` was a reconstruction** guessed at from AlgoLens's reads: the app's own columns and nothing else. It omitted `strategy_id`, which is a real column and part of the engine's `ON CONFLICT (portfolio_id, strategy_id, date)` key, along with twenty-odd figures the engine publishes every run. | The table is no longer a guess. Its shape is the union of the engine's two writers, and the schema contract cites them by file and line. | `check_schema.py` satisfied; seed derives every published metric with the engine's own formulas |
| 7.64 | The seed computed volatility with `stddev_samp` where the engine's `calculate_annualized_volatility` divides by n, and computed downside deviation over all days where the engine divides by the count of negative days. Different numbers under the same names. | Population standard deviation; downside deviation over negatives only. | Matches the engine's formulas |
| 7.65 | **The Strategy Builder reported the whole portfolio as profit** when any selected strategy had no starting equity on record: the invested total skipped it while the value total kept it, and the header rendered `returnPercent.toFixed(2)` with no null handling. The comment said the strategy was "left out"; arithmetically it was left in at zero. | A selection with any unknown basis has an unknown return, and says so. | Test: a null-basis strategy makes the combined return null |
| 7.66 | **The Strategy Builder invented 91 days of history when nothing was selected**: a flat 0% line across three months and 31 empty P&L bars, every point stamped with a real date and none of it in any table. Its metrics were zeros, not unknowns. | An empty selection has no series and no measurements. | Test asserts both series are empty |
| 7.67 | **"Others" was counted as an instrument.** The holdings table, the holdings count and the top-3 weight all read the grouped pie data, so the sub-3% bucket appeared as a row with a colour dot beside real contracts, and a book of nine instruments reported six holdings. | `holdings` (ungrouped) drives anything that counts or lists; `assetAllocation` stays the chart's. | Reads 9 holdings; "Others" absent from the table |
| 7.68 | A strategy the engine has published nothing for carried zeros in every metric, relying on every caller to check `dataAvailable` first; a zero that slips past that check reads as a measurement. | Nulls, which render as em dashes wherever they land. | tsc |
| 7.69 | The information ratio's caption read "vs system alone" while the computation uses the **benchmark** stream. A strategy summary printed `$592,405.719` -- three decimals on a dollar figure, from a format with a minimum and no maximum. | Caption names the series it uses; every remaining currency format pinned. | Reads "vs benchmark stream" and $592,406 |
| 7.70 | **The "Show All" holdings dialog footed $18,373,725 of notional exposure with $1,190,191.75** -- `metrics.totalValue`, the portfolio's equity, a different quantity fifteen times smaller presented as the sum of the rows above it. The weight column was correct and the footer read "100.00%" as a hardcoded string, so nothing on the page disagreed with itself. | Total and weight are both summed from the rows on screen. The weight can now fall short of 100 when a holding is missing rather than asserting completeness. | Nine rows sum to $18,373,725.00 under a footer saying $18,373,725.00 |
| 7.71 | **A price rounded to cents stopped its own row reconciling.** Natural gas closed at 2.958 and rendered "$2.96", so 30 contracts at $10,000 a point read as $888,000 against a Notional column correctly saying $887,400. Euro FX at 1.0915 the same. Futures are not all quoted in cents. | Two to four decimals, so the smallest tick in this universe survives and ES still reads $5,310.75. Applied to position prices, fill prices, closed-lot entry and exit, and the incubation table. | NG reads $2.958 against $887,400.00 |
| 7.72 | **A book header was a dollar short of its own rows**: $592,406 and $250,360 under a heading saying $842,765. Every figure correctly rounded from $592,405.72, $250,359.74 and their true sum $842,765.46 -- and still a column that does not add. | The header sums what is printed beneath it. | Reads $842,766 |
| 7.73 | **Chart axes collapsed small values to a single repeated tick.** The P&L-by-symbol axis divided by 1,000 and rounded, so a chart whose largest bar was $640 labelled its gridlines "$0k $0k $0k $1k $1k"; the cumulative-return axis rounded to whole percent, which reads 0% at every gridline for a book whose range is under a point. | Adaptive formatters: thousands only once there are thousands, decimals on a percentage once the range is small. | — |
| 7.74 | **A pie omitted the label for its largest slice.** Recharts places a label outside the arc at the slice's mid-angle; a slice big enough to straddle 12 o'clock has a mid-angle near 90 degrees, putting its label at y=12 in a 180px chart, centred on that point and so clipped by the top edge. Strategy Split showed 21% and 29% and nothing for the 49.8% slice. | Pies are 200px, which puts that label at y=22 -- level with the highest label the asset pie already drew cleanly. | Computed label positions for both pies |
| 7.75 | The discretionary-alpha axis pinned its top to an exact data value (`domain: dataMax + 500`), so it drew $287,080 / $307,080 / $327,080 and then $365,458: three even steps and a fourth of nearly double. A reader judging a move by how far the line rose was reading a ruler with an uneven last inch. | `domain: auto`, so recharts picks evenly spaced ticks. | — |

### Reviewed and deliberately left

- **Position edits on retired strategies are refused** (the live-only `get`). A retired strategy has no capital to edit; only its audit trail needs to stay readable, and now does.
- **Book and position writers let raw `psycopg2` errors propagate** to the route's generic 500, rather than wrapping them as the incubation writers do. The client never sees database text either way; unifying the pattern is a refactor, not a fix.
- **The HTTP adapter imports the dependency factory and two domain exception classes.** `test_domain_boundaries.py` permits both and they are the composition root's job. Tightening the rule is a team decision.
- **`services/` under `algolens-api` is dead code with passing tests**, present on `main` since the DDD split (#71). Out of scope here; worth deleting in its own PR.
- **No React component tests.** The state machines that make the acknowledge-once gate safe are tested; the component wiring is verified by driving the app. Adding React Testing Library is a dependency decision.

### Verified after the fixes

- 192 backend unit tests, 13 Postgres integration tests, 94 frontend tests, `tsc --noEmit` clean, production build clean.
- `check_schema.py` reports the contract satisfied against the rebuilt demo database.
- Tailwind is compiled at build time; the frozen stylesheet is gone. Dashboard, Books, strategy detail and the edit modal checked in the browser after the switch.
- Demo database rebuilt from the seed plus migration 009 and back at baseline.

Reconciled against SQL after the last pass:

| On screen | Source |
| --- | --- |
| Fund total $1,190,191.75 | Sum of the three live strategies' `current_portfolio_value`, exact |
| Top Holdings ZN 24.5% / ES 17.3% / 6E 16.3% | Share of total exposure; SQL gives 24.46 / 17.34 / 16.34 |
| HHI 1487, 9 holdings, top-3 weight 58% | Sum of squared exposure shares over the ungrouped list |
| Trend Following notional $8,167,795.00 | Equals `live_results.gross_notional`, and the four position rows sum to it exactly |
| Sharpe 4.67, drawdown 3.56%, win rate 56.18%, profit factor 1.79 | Read from `trading.live_results`, not recomputed |
| Avg win 0.78% / avg loss 0.55% | `live_results.avg_win` / `avg_loss`, the engine's percentages |
| Net P&L $7,259.40 | $6,330.00 unrealised + $950.00 realised - $20.60 commissions |
| Combined return +13.35% ($140.2k) | $1,190,191.75 against $1,050,000 of registry starting equity |
| VaR (95%) $9.8k | 1.645 x (7.94% x $1,190,191.75) / sqrt(252) |
| ES fill $1,055,200.00 | 4 x 5,276.00 x 50 |
| ZB closed lot, exit "—" | Held yesterday, no row today; nothing records the exit |

One thing the browser could not confirm: the two pie charts and the daily-P&L
bars render no geometry in the preview pane, because the pane reports
`document.visibilityState === "hidden"` and recharts drives its entry animation
from `requestAnimationFrame`. The axes and their domains come from the same
data, and that data reconciles above; the line chart, which animates by stroke
rather than geometry, draws normally. Worth a glance in a real browser.
