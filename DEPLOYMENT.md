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
| Frontend | 3000 | `algolens.service` via `npx serve ./build` |
| Backend API | **5000** | Docker container — authoritative backend with DB credentials |
| Legacy backend | ~~5001~~ | `algolens-backend.service` — no DB env vars, do not route to this |
| Nginx (public) | 80 / 443 | `/` → 3000 · `/auth` → 5000 · `/portfolio` → 5000 |

All new API routes added to `deployment/algolens.conf` must proxy to port **5000**.

---

## Automatic Deploy (GitHub Actions)

Push to `main`. The workflow (`.github/workflows/deploy.yml`) will:

1. SSH into EC2
2. `git pull origin main`
3. `npm ci && npm run build` — builds frontend with `VITE_API_URL` from `/home/ec2-user/AlgoLens/.env`
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
npm ci
npm run build
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
| `/home/ec2-user/AlgoLens/.env` | `VITE_API_URL=https://algolens.algogators.com` |
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
