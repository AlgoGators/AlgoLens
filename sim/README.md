# QT desk simulator

The real AlgoLens, the real engine (`engine-rpc` and the C++ binary it runs) and Postgres, all on
one clock you can move. Use it to see what the desk and the engine do at 09:29, 09:31 or 10:01
New York without waiting for that time.

Everything runs locally in Docker. Nothing here talks to production, except `snapshot.sh`, which
you run yourself to take a read-only copy of the data.

| What | Where |
|---|---|
| AlgoLens | http://localhost:8080 |
| Mailpit (every e-mail the engine sends) | http://localhost:8025 |
| Postgres | `localhost:55432`, user `postgres`, password `sim`, database `new_algo_data` |
| Users | `qt@sim.local` (desk), `vp@sim.local`, `president@sim.local`; password `sim` |

## How the clock works

`libfaketime` is preloaded in the postgres, engine-rpc and backend containers. All three read
`sim/clock/faketime.rc`, which holds one offset in seconds from real time (for example
`+63000`). `simctl clock` writes it, and every process sees the change within a second. The
clock keeps ticking from the time you set. `now()` in Postgres, `datetime.now()` in the backend,
the desk service's scheduler and the C++ engine all read the same time.

The sim day is in `sim/clock/day`. `simctl clock 09:29` means 09:29 New York on that day.

The offset is used instead of libfaketime's absolute `@YYYY-MM-DD HH:MM:SS` form because `@`
starts the clock at that time in every new process: each engine run the desk service spawns
would start at the same second again. With an offset, all processes agree.

AlgoLens shows an amber banner, "SIMULATION — clock ... New York", at the top of every page.
It appears only when the backend runs with `SIM_MODE=1`, which only this compose file sets.

## Prerequisites (Windows 11)

- Docker Desktop, running. If it hangs (`docker ps` does not answer), run
  `docker desktop restart`.
- Git Bash (comes with Git for Windows). Run `simctl` from Git Bash as `bash sim/simctl ...`,
  or from PowerShell as `.\sim\simctl.ps1 ...`. The examples below use Git Bash, from the
  repository root.
- The engine image built locally: `docker images trade-ngin` should list
  `trade-ngin:rpc-0b9dbf6e`. To use another tag, put `ENGINE_IMAGE=trade-ngin:rpc-<sha>` in
  `sim/.env` (or export it) and run `bash sim/simctl build`.
- Two browser profiles (or one normal window and one private window), so the desk and the VP
  can be logged in at the same time. Use `http://localhost:8080`, not `127.0.0.1`: the session
  cookie is marked Secure, which browsers accept on plain HTTP only for `localhost`.

## First run

1. Take a snapshot of production. You run this yourself. It only reads; nothing is written on
   the server, and the copy lands in `sim/data/`:

   ```bash
   bash sim/snapshot.sh
   ```

   It connects with `prod-deploy.pem`, reads the login from
   `~/.config/algogators/db-app-roles.env` on the host when that file sets `PGUSER` and
   `PGPASSWORD` (otherwise it asks you), and streams back over ssh:

   - the schema of `trading`, `metadata`, `futures_data`, `auth`, `ops`, `investor`;
   - all of `metadata.contract_metadata`, `futures_data.ohlcv_1d` (the engine's market data),
     `ops.data_ready` and `trading.strategy_registry`;
   - the rows of `QT_CONSERVATIVE_PORTFOLIO` and `QT_CONSERVATIVE_MODEL_PORTFOLIO` in
     `trading.positions`, `executions`, `live_results`, `live_run_metadata`, `equity_curve`,
     `position_overrides`, `strategy_config` and `signals`.

   No user rows are taken. The result is `sim/data/snapshot-<timestamp>/` (git-ignored).

2. Build the images and load the snapshot:

   ```bash
   bash sim/simctl build
   bash sim/simctl load sim/data/snapshot-<timestamp>
   ```

   `load` restores the snapshot, adds the three sim users, and picks the sim day: the newest
   QT day in the data. It removes that day's QT rows so the real engine can build the day
   again. Use `--day YYYY-MM-DD` for another day, or `--keep` to keep the newest day as it was.
   It sets the clock to 08:00 on the sim day and saves everything as a template, so
   `simctl reset` can return to this point in seconds.

   If the snapshot came from a newer Postgres major version than 16, `load` warns; set
   `PG_IMAGE=postgres:<major>` in `sim/.env` and run `bash sim/simctl build` first.

3. Start everything:

   ```bash
   bash sim/simctl up
   ```

4. Build the sim day's books with the real engine (the same command the scheduler runs):

   ```bash
   bash sim/simctl model-run
   ```

   The scheduler would also do it on its own on the next pass (it runs every 5 minutes
   between 06:30 and 10:30 sim time, or now with `bash sim/simctl pass`).

5. Save this state as the template, so each `reset` starts from a built, unapproved day:

   ```bash
   bash sim/simctl save
   ```

6. Open http://localhost:8080. Log in as `qt@sim.local` / `sim` in one browser profile and as
   `vp@sim.local` / `sim` in the other. Open http://localhost:8025 for the mail.

## Everyday commands

```bash
bash sim/simctl clock 09:29      # 09:29 New York on the sim day
bash sim/simctl clock +5m        # forward 5 minutes (also -2m, +1h, +30s)
bash sim/simctl day 2026-10-16   # another sim day, same time of day
bash sim/simctl status           # time in each container, the day's publish state, desk commands
bash sim/simctl pass             # one scheduler pass now, instead of waiting for its 1-minute tick
bash sim/simctl reset            # back to the template; clock 08:00; Mailpit emptied
bash sim/simctl logs             # follow engine-rpc and backend logs
bash sim/simctl psql             # psql on the sim database
bash sim/simctl down             # stop (data kept); `destroy` also deletes the volumes
```

After a `reset` (or any move of the clock backwards) log in again: a session issued at 10:01
is "not yet valid" at 08:00.

After `git checkout <another AlgoLens branch>`, run `bash sim/simctl build` and
`bash sim/simctl up` to run that branch's backend and frontend. The images are always built
from the working tree.

## Test script

Which flow you can test depends on the code you run. The "approve B" flow below (approve the
model's book unchanged, auto-approval, approve C after the dynamic optimisation) ships in
AlgoLens PR `qt/desk-pipeline` and trade-ngin PR #208. Until both are merged, check out
`qt/desk-pipeline` here (and build an engine image from #208, then set `ENGINE_IMAGE`), or
run today's flow: Save, then Approve.

Start each scenario with `bash sim/simctl reset`, then log in again in both browsers.

1. **Approve before 09:30, sent at 09:30.**
   `clock 09:00`. As the desk, approve B unchanged: it is approved at once (auto-approved).
   `status` shows the publish command done and `sent_at` empty. `clock 09:30`, then `pass`
   (or wait a minute). Mailpit shows the day's e-mail, and `status` shows `sent_ny` 09:30.

2. **A change that moves the dynamic optimisation.**
   `reset`, `clock 09:10`. As the desk, set ZT to 8 and approve. The engine's dynamic
   optimisation changes the book; the desk sees C. Approve C. Mailpit gets it at 09:30.

3. **Override approved by the VP.**
   `reset`, `clock 09:05`. As the desk, request an override for B. Mailpit shows the override
   request e-mail to `vp@sim.local` and `president@sim.local`. Open its link in the VP's browser
   (log in as `vp@sim.local`), approve. B is published; at 09:30 it is sent.

4. **Approve between 09:30 and 10:00: sent at once.**
   `reset`, `clock 09:45`. As the desk, approve. The e-mail goes out at once (Mailpit), and
   `status` shows `sent_ny` about 09:45.

5. **Nothing approved: the 10:00 fallback.**
   `reset`, `clock 10:01`, then `pass`. The engine publishes the model's book A
   (`publish_source` fallback, `published_by` `system:fallback-10am`) and e-mails it. The
   President gets an alert.

6. **Too late.**
   Right after scenario 5 (or `reset`, `clock 10:02`), try to approve as the desk. AlgoLens
   refuses: "Approval of the <day> book closed at 10:00 New York".

## Without a snapshot: the synthetic fixture

`bash sim/simctl load synthetic` restores `sim/seed/synthetic.sql`: trade-ngin's QT schema
(migrations 021 to 029 read from the engine image) and one seeded QT day, 2026-10-15, with
three books of five symbols. The desk panel renders and the clock rules apply, but it is not
market data: every engine run (model run, approval, fallback) fails on it, and the scheduler
mails the President an alert. Use it to check the stack, not the engine. Rebuild it with
`bash sim/seed/build-synthetic.sh` after an engine change.

## Files

| File | What |
|---|---|
| `docker-compose.sim.yml` | postgres, mailpit, engine-rpc, backend, frontend, edge |
| `simctl`, `simctl.ps1` | the driver, and its PowerShell wrapper |
| `snapshot.sh` | the read-only production snapshot (you run it) |
| `postgres/Dockerfile` | postgres:16 with libfaketime |
| `engine/Dockerfile`, `engine/sim_config.py` | the engine image with libfaketime and `/app/config` (database: sim postgres; e-mail: Mailpit) |
| `backend/Dockerfile` | the AlgoLens backend image with libfaketime |
| `edge/edge.conf` | plain-HTTP edge with `deployment/edge-routes.conf` |
| `seed/users.sql` | the three sim users and their screens |
| `seed/synthetic*.sql`, `seed/build-synthetic.sh` | the synthetic fixture |
| `clock/` | `faketime.rc` (the offset) and `day` (the sim day), both git-ignored |
| `data/` | snapshots, git-ignored |

## Notes

- **Settings.** The backend runs with `FLASK_ENV=production` (CORS allow-list, JWT secret
  required, Secure cookies), `QT_DESK_ENABLED=1`, `QT_APPROVERS=vp=vp@sim.local,president=president@sim.local`
  and `SIM_MODE=1`. If a browser refuses the cookie, set `SIM_FLASK_ENV=development` in
  `sim/.env` and `bash sim/simctl up`. The engine runs with `QT_CATCHUP_ENABLED=1`,
  `QT_CATCHUP_PORTFOLIOS=qt_conservative` (the config directory of `QT_CONSERVATIVE_PORTFOLIO`;
  add `qt_conservative_model` for the twin) and `QT_EVENING_RUN=0` (the 06:45 schedule, no
  `ops.data_ready`); each can be overridden in `sim/.env`.
- **E-mail.** Both the C++ mailer and the desk service's Python mailer log in, and the C++
  mailer always asks for STARTTLS. Mailpit therefore runs with a throwaway self-signed
  certificate and accepts any login (`sim`/`sim` in every `email.json`). All mail is caught;
  nothing leaves your machine.
- **libfaketime.** `FAKETIME_DISABLE_SHM=1` is required: without it postgres hangs at start
  (gosu's child blocks on a semaphore). The engine image gets libfaketime built from source:
  Ubuntu 24.04's package breaks Python's `time.sleep()` under an offset.
- **Database login.** The apps connect as `postgres` (superuser) in the simulator. Production
  grants (for example 025's revokes on `position_overrides`) are therefore not enforced here.
- **Restore errors.** `load` does not stop on an error in the schema (an extension the sim
  lacks, for example). It reports the count and writes them to `sim/data/<snapshot>.load.log`.
