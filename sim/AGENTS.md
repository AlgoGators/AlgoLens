# QT desk simulator: instructions for AI agents

Read this file when you help someone use the QT desk simulator in this directory (Claude Code
reads it through `sim/CLAUDE.md`; Codex and other agents read `AGENTS.md`). It contains the
desk's rules, so you can answer "what happens if…" questions, and the commands that drive the
simulator, so you can set up a scenario for the person.

Start the agent in `sim/` (`cd sim && claude`, or `cd sim && codex`) so it picks this file up.
`README.md` next to it is the human setup guide; read it for anything about installing.

## How to behave

- **Answer from the rules below.** The binding text is trade-ngin's
  [`docs/design/qt-contract.md`](https://github.com/AlgoGators/trade-ngin/blob/main/docs/design/qt-contract.md)
  (sections C1 to C11). Cite the section (for example "C7") when you state a rule. If this file
  and the contract disagree, the contract wins; say so.
- **Don't invent a rule.** If the rules here don't settle a question, say that, and suggest a
  scenario in the simulator that would show what actually happens.
- **Show, don't only tell.** When someone asks what happens at a given time, offer to set the
  clock and run it (`bash simctl clock 09:45`). Then tell them what to click and where to look:
  the desk at http://localhost:8080, the mail at http://localhost:8025, and `bash simctl status`.
- **Run commands from `sim/`** as `bash simctl <command>`. From PowerShell, use
  `.\simctl.ps1 <command>`.
- **Everything is local.** Nothing in the simulator reaches production or sends real e-mail.
  Mailpit catches all mail. Never run `snapshot.sh` for someone: it reads the production
  database with the maintainer's server key, and only the maintainer runs it.
- **Never commit a snapshot** (`data/`) or paste its contents anywhere. It holds the fund's
  trading data, and this repository is public.
- **After moving the clock backwards** (`reset`, or `clock` to an earlier time), tell the
  person to log in again. A session issued "later" is not valid yet.

## The cast (simulator logins, password `sim`)

| Login | Role | Can |
|---|---|---|
| `qt@sim.local` | QT desk | edit the day's book, approve, rescind its own approval, request an override |
| `vp@sim.local` | VP (approver) | approve or reject an override request (from the e-mailed link) |
| `president@sim.local` | President (approver) | the same as the VP; also gets the alerts |

An override needs **either** the VP **or** the President, not both. Nobody may decide their own
request. Use two browser profiles (or a normal and a private window) to be the QT and an
approver at the same time.

Admins (role `exec_board` or `admin`) see every screen: Member, QT desk, Investor and Admin.
Only admins see the Admin tab. The role is read from the database on every request, so a
promotion or a demotion takes effect on the next click.

## The day (C7). All times are New York, every calendar day, weekends included

| Time | What happens |
|---|---|
| from 06:45 | The **model run** builds the day's book: the model's book **A**. It is retried every 15 min until done. If there is no model book by 08:30, the President gets an alert. |
| until 09:30 | The QT edits, saves, requests overrides and **approves**. An approval freezes the day and sends nothing yet. |
| **09:30** | **Send.** Every approved day is e-mailed (the daily report and CSV). An approval made between 09:30 and 10:00 is sent at once. |
| **10:00** | **Fallback.** If the day is not approved, the model's book A is published and sent, any unapproved desk edits are thrown away, and the President is alerted: "QT did not approve … the model's book was sent at 10:00". |
| after 10:00 | Approving is refused: "Approval of the <day> book closed at 10:00 New York…". Saving, override requests and decisions are refused because the day is published. |

The moment that counts for an approval is **when Approve was pressed** (the row's `created_at`),
not when the engine finishes. Approve at 09:59:50 and it counts, even if the engine is still
working at 10:00.

## Books A, B and C (C10)

- **A**: the model's book, from the morning model run.
- **B**: the QT's edit of A (`qt_proposal`). The QT may change quantities only, and must give a
  reason. Zero means flatten.
- **C**: what the engine returns after running B through **dynamic optimisation and the risk
  system** (the same pass the model uses). C is stored as the day's `qt` book.

Pressing **Approve** on B starts the pipeline A → B → C:

1. **C equals B and is within the caps:** the day is **auto-approved**. Before 09:30 it
   waits for the 09:30 send; from 09:30 it is sent at once.
2. **C differs from B** (any symbol, even when only a trading rule moved it) **or is outside a
   limit:** nothing is approved. The desk shows B next to C, the symbols that moved and what
   moved them. The QT then chooses one of two things:
   - **Approve C.** The QT ticks "I approve C knowing it differs". This works only while C is
     still the latest saved book, and only if C itself is over no **cap** (decision 5, below). A
     limit that **bound** (C was cut to fit it) is fine.
   - **Insist on B: request an override.** The request e-mails the VP and the President a link
     (it works once and expires after 48 hours). Either one approves, and then the engine books
     **B exactly as asked** and publishes it. A rejection publishes nothing; the QT can still
     approve C until 10:00.

**Check without approving** runs the same pass (B → C) and shows the result, but approves
nothing.

### What moves a position, and which moves are breaches (C9)

- **Risk limits (a breach):** `cap` (the per-name cap), `overlay` (the risk overlay cut the
  book), `clip`, `trim`.
- **Trading rules (not a breach, but still a difference from B):** `sign_close` (no flip from
  long to short in one day), `rounding`, `buffer`, `search`, `hold`.

### What blocks an approval: the caps (decision 5, 2026-10-16)

Only the final book over a **cap** blocks: gross leverage (L_g), net leverage (L_n), the
per-name cap (CAP) and the fund's margin cap (MARGIN). A desk book whose caps were not measured,
or whose overlay refused, is blocked too, and so is an **incomplete** book (a desk or override
run did not finish writing it, for example an override the margin cap refused): save again.
Everything else (a limit that bound, R, R_jump, R_shock, the trim, every trading rule) is shown
and never blocks. The VP or the President may approve a book past gross, net and per-name; **no
one can approve a book past the margin cap**. The engine decides this (`GetDeskRisk`'s
`blocks_publish` and `blockers`) and AlgoLens shows it; every approval path applies it.

### The risk checks the desk sees (C9, C11)

Each check shows the book's reading against its max, with a status: within, bound, over, or not
measured. trade-ngin supplies the labels, units and maxes; AlgoLens hardcodes none of them.

- **R, R_jump, R_shock:** portfolio risk, its jump term and its shock term, against the risk
  target.
- **L_g, L_n:** gross and net leverage.
- **The per-name cap and the trim.**
- **MARGIN, the fund's hard cap (C11):** initial margin may be at most **100% of the fund's
  equity after today's transaction costs**. The engine refuses a desk or override book over the
  cap outright, even one the VP or the President approved. The day stays unapproved, and at
  10:00 the model's book goes out.
- **Multipliers (shown, not limits):** the overlay's m, the risk scale, and each strategy's IDM
  and FDM. The IDM and FDM are configured settings, not estimated per run.

**Transaction costs** are charged on every fill, buys and sells alike: a per-contract fee plus
spread and market impact. They are stored with each execution and reduce the day's P&L and
equity.

## Taking an approval back: Rescind (C8)

The QT who approved can rescind the approval **before 09:30**, if it hasn't been sent yet. The
day is then open again: edit, then approve again. A rescind is refused from 09:30 on, and
refused by anyone other than the approver. A fallback, a sent day and a past day cannot be
rescinded.

## Settings the desk may change

- **Editable from the desk:** risk limits and capital, and signal parameters.
- **Locked** (not shown, and refused by the server): backtest settings, platform and ops
  switches (database, e-mail, live, execution, the qt block, optimisation), and model structure
  (strategy type, enabled, default allocation, strategy defaults).

## Driving the simulator

```bash
bash simctl status            # sim time, the day's publish state, recent desk commands
bash simctl clock 09:29       # set New York time on the sim day (the clock keeps ticking)
bash simctl clock +5m         # move forward (also -2m, +1h, +30s)
bash simctl pass              # run the scheduler now (the 09:30 send / 10:00 fallback) instead of waiting
bash simctl reset             # back to the start of the day: 08:00, model book built, nothing approved, mail cleared
bash simctl day 2026-10-14    # another sim day (needs data for it in the snapshot)
bash simctl logs              # follow the engine and backend logs
```

After `clock`, give the scheduler a minute or run `pass`, so the 09:30 send or the 10:00
fallback happens.

### Ready-made scenarios (start each with `bash simctl reset`, then log in again)

| # | Set up | Do | Expect |
|---|---|---|---|
| 1 | `clock 09:00` | QT: approve A unchanged | auto-approved; `clock 09:30` + `pass` → the e-mail arrives in Mailpit |
| 2 | `clock 09:10` | QT: change a quantity a rule or limit will move (for example a large ZT long, or a long-to-short flip), approve | "the engine changed your positions"; B vs C shown; Approve C → sent at 09:30 |
| 3 | `clock 09:05` | QT: same edit, request an override; VP: open the link in Mailpit, approve | B is booked exactly and published; sent at 09:30 |
| 4 | `clock 09:45` | QT: approve | sent at once (Mailpit, `status` shows sent about 09:45) |
| 5 | `clock 10:01`, `pass` | nothing | fallback: A is published and sent; the President's alert is in Mailpit |
| 6 | after 5, or `clock 10:02` | QT: approve | refused: approval closed at 10:00 |
| 7 | `clock 09:10` | QT: approve, then rescind before 09:30 | the day is open again; rescind at 09:31 is refused |
| 8 | `clock 09:10` | QT: set quantities far beyond the fund's money (thousands of contracts), approve; VP approves the override | refused by the fund cap (MARGIN), even with the VP's approval; the fallback sends A at 10:00 |

## When something looks wrong

- **"The risk check is unavailable" or "has not caught up":** the engine is still working. Wait
  a few seconds and try again (`bash simctl status` shows the running command).
- **The page says I'm logged out after a reset:** expected; log in again.
- **No e-mail at 09:30:** run `bash simctl pass`, then check `bash simctl status` (`sent_ny`)
  and `bash simctl logs engine-rpc`.
- **Every engine run fails:** the synthetic fixture (`load synthetic`) has no market data, so
  engine runs fail on it by design. Load a real snapshot from the maintainer (see README).
- **Anything else:** read `bash simctl logs` and report what you find. Don't change code to
  make a scenario pass; the simulator runs the real engine and the real AlgoLens on purpose.
