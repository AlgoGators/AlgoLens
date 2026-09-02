# QT Platform — preview branch

**This branch is for feedback, not for merging.** It exists so the QT desk can use the
manual position path end to end and tell us what is wrong with it before we finalise the
individual pull requests.

It will be deleted and rebuilt from the PRs after review. Do not branch off it, and do not
merge it into `main` — the real work lands through the PRs listed below.

This file exists only on this branch.

---

## What is in it

`AlgoLens/qt-platform-preview` = `main` + these two, merged:

| PR | Branch | What it adds |
|---|---|---|
| [#80](https://github.com/AlgoGators/AlgoLens/pull/80) | `port/qt-position-edit` | The position edit path — the write side, the risk check, the audit trail, and the editor UI |
| [#81](https://github.com/AlgoGators/AlgoLens/pull/81) | `fix/information-ratio-real-benchmark` | Sortino and information ratio computed from real data instead of hardcoded constants |

The engine half is a **separate branch in a separate repo**, because the platform spans both:

`trade-ngin/qt-platform-preview` = `main` + [#56](https://github.com/AlgoGators/trade-ngin/pull/56) (which already contains [#55](https://github.com/AlgoGators/trade-ngin/pull/55)).

That is what publishes the risk limits this app checks edits against, and what writes the
three portfolio streams.

## Verified on this branch

- 81 backend tests pass
- 63 frontend tests pass
- Production frontend build clean

Note that `npm run build` does **not** typecheck — there is no `tsconfig.json` and no
`typescript` dependency in `algolens-frontend`, so nothing in CI typechecks this project.
That is pre-existing and worth fixing separately.

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
```

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
trail as "not checked", never as "checked and fine". But it does mean **the gate is not
actually gating anything yet.** To see the gate work, seed a row by hand:

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

## What we most want feedback on

1. **The breach flow.** A breaching edit returns 409 and the UI stops and waits — you have to
   click "Override and save" a second time. Is one extra click the right amount of friction,
   or too much / too little?
2. **Is "reason" doing its job?** It is mandatory and free-text. Read a few back and see
   whether they will still mean anything in six months, or whether this should be a
   structured dropdown.
3. **The diff panel** shows quantity and average price before/after. Is anything missing that
   you would want to see before committing a change?
4. **Blank average price means "leave it alone", not "clear it".** Is that what you expect?
5. **Anything the audit trail should record that it does not.** Right now:
   who, when, strategy, symbol, before, after, reason, risk verdict, and whether the verdict
   was acknowledged.

Open a PR comment on #80, or just tell John.

---

## Known gaps, already understood

- The gate is advisory. Per DECISION-1 a breach never hard-blocks — it forces an
  acknowledgement and records it. That decision is still formally open.
- No override *history* view in the UI yet. `GET /portfolio/overrides/<strategy_id>` returns
  it; nothing renders it.
- The `refactor/models-range-filter` branch deletes the three-stream read side (220 lines,
  including all of `AlphaAttribution.tsx`). If that lands, it removes the other half of this
  feature. Nobody has confirmed whether that deletion is intended — it needs an answer before
  it goes anywhere near `main`.
