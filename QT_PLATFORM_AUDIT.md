# QT Platform — audit of the preview branch

**Date:** 2026-09-02 · **Branch:** `AlgoLens/qt-platform-preview` · **Method:** every feature driven in a browser and via curl against a production-shaped local Postgres, not inferred from reading code.

The short version: **the platform works, but it did not when this audit started.** Three of the bugs below would have made the core QT feature — a human editing a position through a risk gate — fail or silently pass on the first real use. None of them were visible to the unit suite, because the suite feeds the domain plain Python floats and a real database does not.

Everything in §1 is fixed and verified. §2 is what a demo environment needs that the first seed lacked. §3 is what is still open, ordered by **when it has to be done**, and within each band by **how fast it is to do**.

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

**Lesson worth keeping:** unit tests with float fixtures gave 120+ green results while the feature was completely broken against Postgres. There is no integration test that runs the write path against a real database. That is §3 item P0-c.

---

## 3. Still open — ordered by when, then by speed

**How to read this:** bands are *when it must be done*. Inside a band, items are sorted fastest-first, so the top of each band is the best thing to pick up next. Effort: **S** < 1 h · **M** half a day · **L** multi-day · **D** = a decision someone has to make, not code.

### P0 — before the QT desk relies on this

| # | Item | Effort | Notes |
|---|---|---|---|
| ~~P0-a~~ | ~~Position response serialises numbers as strings~~ — **FIXED** | S | `jsonify` stringifies Decimal. Coerce in the serializer. Any client that parses these as numbers breaks. |
| ~~P0-b~~ | ~~Add `tsc --noEmit` to frontend CI~~ — **FIXED**, and it immediately caught that `Book`/`AssignmentRecord` were never declared | S | There is no `tsconfig.json` and no `typescript` dependency. Nothing typechecks. Today's `number \| null` widenings and placeholder shapes were verified by grep, not a compiler. |
| P0-c | One integration test that runs `write_qt_position` against Postgres | **M** | Would have caught 1.1, 1.2 and 1.3 outright. A `testcontainers`-style throwaway DB or the demo seed in CI. |
| ~~P0-d~~ | ~~Canonical migrations in trade-ngin~~ — **FIXED**: migration 008 + rollback; lazy DDL removed from the app | M | The app creates them lazily with `CREATE TABLE IF NOT EXISTS`. trade-ngin owns this schema (migrations 004/005). Lazy creation must not survive into production. |
| ~~P0-e~~ | ~~Portfolio tab grouping ignores multi-book membership~~ — **FIXED**, and it also stopped hiding incubating strategies (P1-i) | M | `ListPortfolios` buckets by `registry.portfolio_id` (primary only). A strategy in two books shows under one on the Portfolio tab and under both on Books. Same data, two answers. |

### P1 — this week

| # | Item | Effort | Notes |
|---|---|---|---|
| P1-a | `IncubationDetail` shows `+0.00%` and an empty chart when there is no performance yet | **S** | Fabricated zero. Needs an empty state: "No trading days recorded yet". |
| P1-b | Positions flagged `priceUnknown` still render `$0` notional / `$0.00` price | **S** | Backend now flags them (1.4); `Position` type and `PositionBreakdown` need to show "—". |
| P1-c | `_incubation_error_status` decides 404 vs 400 by searching the message for "not found" | **S** | Typed exceptions. Fragile: a reason containing the words "not found" would change the status. |
| P1-d | `book_not_empty` is a bare `ValueError` rendered with `str(exc)` | **S** | Controlled message today, but it is the same anti-pattern as 1.5. Typed exception. |
| P1-e | "Add to book" records a hardcoded reason (`Added from the Books tab`) | **S** | Removal asks for a reason; adding does not. Asymmetric audit trail. |
| P1-f | Override history endpoint exists (`GET /portfolio/overrides/<id>`); nothing renders it | **M** | The desk cannot see what has been overridden without SQL. |
| P1-g | Incubation lifecycle has no UI — start / promote / retire are API-only | **M** | Pre-existing. The Incubation tab is read-only; verified the API transitions and audit log work. |
| P1-h | `retired → incubating` is permitted by the incubation path, but membership treats `retired` as frozen | **D** | Two subsystems disagree about whether a retired strategy is a closed record. Decide once. |
| ~~P1-i~~ | ~~Fund headline silently excludes incubating strategies~~ — **FIXED** with P0-e: listed, marked, mock capital shown and excluded from totals | S | By design (mock capital), but there is no note. Same shape as the "Excludes N…" notice already added for unpublished ones. |

### P2 — later

| # | Item | Effort | Notes |
|---|---|---|---|
| P2-a | Node 20 deprecation warnings on `actions/checkout@v4`, `upload-artifact@v4` in CI | **S** | Bump to v5/v6 before the runners drop Node 20. |
| P2-b | The `history_discontinuity` warning names a real problem the feature does not solve | **L / D** | Attribution across a book move still spans two compositions. Options: forbid moves on live strategies, or snapshot-and-restart the curve at the move. |
| P2-c | `refactor/models-range-filter` deletes the three-stream read side (220 lines, all of `AlphaAttribution.tsx`) | **D** | Still on the remote. Merging it removes half of this feature. Nobody has confirmed whether the deletion was intended. |
| P2-d | Demo seed is a repo script, not part of any test run | **S** | Wire into P0-c once that exists. |

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
