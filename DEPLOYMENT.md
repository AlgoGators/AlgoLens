# AlgoLens Deployment Guide

## Overview

Pushing to `main` automatically deploys via GitHub Actions. The workflow SSHes into EC2, pulls the latest code, builds the frontend, and restarts services.

For manual deploys or hotfixes, follow the steps below.

---

## Prerequisites

### SSH Key
You need `dominick-pem.pem` to access the EC2 instance. It is **not in the repo** — get it from a current team member.

**Windows** — restrict permissions before first use:
```powershell
icacls "C:\path\to\dominick-pem.pem" /inheritance:r /grant:r "$($env:USERNAME):R"
```

**Mac/Linux:**
```bash
chmod 400 ~/path/to/dominick-pem.pem
```

### Node.js v18+
```bash
node -v
```

---

## Port Reference

| Service | Port | Notes |
|---|---|---|
| Frontend | 3000 | `algolens.service` via `npx serve ./algolens-frontend/build` |
| Backend API | **5000** | Docker container — authoritative backend with DB credentials |
| Legacy backend | ~~5001~~ | `algolens-backend.service` — no DB env vars, do not route to this |
| Nginx (public) | 80 / 443 | `/` → 3000 · `/auth` → 5000 · `/portfolio` → 5000 |

All new API routes added to `deployment/algolens.conf` must proxy to port **5000**.

---

## Automatic Deploy (GitHub Actions)

Push to `main`. The workflow (`.github/workflows/deploy.yml`) will:

1. SSH into EC2
2. `git pull origin main`
3. `cd algolens-frontend && npm ci && npm run build` — builds frontend with `VITE_API_URL` from `/home/ec2-user/AlgoLens/algolens-frontend/.env`
4. Copy `deployment/algolens-backend.service`, `deployment/algolens.service`, `deployment/algolens.conf` into system paths
5. Reload nginx, restart `algolens` and `algolens-backend` systemd services

> The backend Docker container is **not** restarted by CI/CD. Restart it manually when needed (see below).

---

## Manual Deploy Steps

### 1. SSH into EC2
```bash
ssh -i "/path/to/dominick-pem.pem" ec2-user@ec2-18-226-98-126.us-east-2.compute.amazonaws.com
```

### 2. Pull latest code
```bash
cd /home/ec2-user/AlgoLens
git pull origin main
```

### 3. Build frontend
```bash
cd algolens-frontend
npm ci
npm run build
cd ..
```

### 4. Restart frontend service
```bash
sudo systemctl restart algolens
```

### 5. Reload nginx (if config changed)
```bash
sudo nginx -t && sudo systemctl reload nginx
```

---

## Backend Changes

The backend runs as a Docker container using `/home/ec2-user/algolens-docker/.env` for all secrets.

**Restart the backend container:**
```bash
docker restart algolens-docker-backend-1
```

**View backend logs:**
```bash
docker logs algolens-docker-backend-1 --tail 50
```

**If you change DB credentials or DB name:**
1. Edit `/home/ec2-user/algolens-docker/.env`
2. Restart the container: `docker restart algolens-docker-backend-1`
3. Verify: `docker logs algolens-docker-backend-1 --tail 10`

---

## Environment Files (not in git)

| Path on EC2 | Contents |
|---|---|
| `/home/ec2-user/AlgoLens/algolens-frontend/.env` | `VITE_API_URL=https://algolens.algogators.com` |
| `/home/ec2-user/algolens-docker/.env` | `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`, `JWT_SECRET_KEY` |

These files are gitignored. Do not commit them. Share via password manager or private message only.

---

## Adding New API Endpoints

1. Add the route to the Flask backend (`algolens-api/algolens/adapters/http/`)
2. Register the blueprint in `algolens-api/algolens/infrastructure/config/app_factory.py`
3. Add a `location` block to `deployment/algolens.conf`:
```nginx
location /your-route {
    proxy_pass http://localhost:5000/your-route;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```
4. Push to `main` — CI/CD deploys the updated nginx config automatically.

---

## Server Info

| | |
|---|---|
| **URL** | https://algolens.algogators.com |
| **EC2 host** | ec2-18-226-98-126.us-east-2.compute.amazonaws.com |
| **EC2 user** | `ec2-user` |
| **Database** | PostgreSQL · `13.58.153.216:5432` · db: `new_algo_data` |
| **Swap** | 2 GB `/swapfile` (required for frontend builds — do not remove) |

---

## Before Any Deploy: Check the Schema

AlgoLens reads tables it does not own. `trading.*` belongs to trade-ngin,
`futures_data.ohlcv_1d` and `metadata.contract_metadata` to data-ngin. Nothing
in this repository can guarantee their shape, and no test here can either — the
demo seed proves only that the seed matches what this application says it needs.

`scripts/check_schema.py` is what closes that gap. It compares a real database
against the declared contract in
`algolens-api/algolens/infrastructure/db/schema_contract.py`, runs nothing but
SELECTs against `information_schema`, changes nothing, and exits non-zero when
the contract is not satisfied — so it can gate a deploy.

```bash
python scripts/check_schema.py "postgresql://USER@HOST:5432/new_algo_data"
```

For a fuller picture — including the questions that decide how positions are
priced — run the read-only readiness pass instead. It writes nothing:

```bash
./scripts/production_readiness.sh "postgresql://USER@HOST:5432/new_algo_data"
```

Two kinds of finding matter. `missing_column` means a read fails. Ten columns
of `trading.live_results` were reported missing against a database built from
trade-ngin's migrations alone, because **no migration in either repository
creates `trading.live_results` or `trading.executions`** — their shape existed
only as whatever was done by hand on the box that runs the engine. trade-ngin's
migration 011 declares them, additively and idempotently. `unsupplied_not_null`
means a write fails; that one shipped undetected once already.

### Migration order

Apply trade-ngin's migrations in numeric order, with two exceptions worth
stating because the numbers do not imply them:

1. **011 before 010.** 010 UPDATEs `profit_factor`, which 011 is the first thing
   to declare. 010 skips harmlessly if run early and can be re-run afterwards.
2. **009 before deploying a build with the Books tab.** AlgoLens no longer
   creates those tables itself.

Then run the schema check, and only deploy if it passes. In full:

```bash
psql "$DSN" -v ON_ERROR_STOP=1 -f trade-ngin/migrations/011_live_results_and_executions_columns.sql
psql "$DSN" -v ON_ERROR_STOP=1 -f trade-ngin/migrations/010_clear_profit_factor_sentinel.sql
python algolens-api/scripts/check_schema.py "$DSN"   # must exit 0
```

011 is additive and idempotent, so it is safe to run on a database that already
has those columns — it does nothing. 010 only clears rows where `profit_factor`
is at or above 999 **and** `gross_loss` is zero, so a genuine ratio is untouched.
Neither drops anything.

Migration 002 (`002_backfill_qt_from_system.sql`) is a separate decision. It puts
a second stream in `trading.positions` for every symbol and date. AlgoLens reads
positions by stream as of the QT platform branch, so it is ready for that — but
anything else querying that table without a `portfolio_type` predicate will start
blending the model's book with the desk's. See AlgoLens issue #83.

### New endpoints do not need an nginx change

`deployment/algolens.conf` proxies `/auth` and `/portfolio` by prefix, so a new
route under either is already served. Only a route outside both prefixes needs a
new `location` block.
