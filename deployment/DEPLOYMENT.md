# AlgoLens Deployment

AlgoLens runs as Docker containers on the **trade-ngin box**
(`ubuntu@ec2-18-118-225-224`, private IP `172.31.23.190`, Ubuntu), next to
trade-ngin and the data-ngin Airflow stack. The **old host** (`ec2-user`,
Amazon Linux) keeps one job: terminating TLS for `algolens.algogators.com`
and forwarding everything to the box, the same way it already forwards
`airflow.algogators.com` to `172.31.23.190:8080`.

The setup mirrors data-ngin's deploy in AlgoGators/algogators
(`_publish-container.yml`, `_deploy-ssh.yml`, `services/data-ngin/deploy/`).

## Topology

```
browser --https--> old host nginx (TLS, certbot)
                     |  proxy_pass http://172.31.23.190:8088   (VPC-private)
                     v
  trade-ngin box (t2.medium: 2 vCPU, 4 GiB RAM)
  +-------------------------------------------------------------+
  | algolens-edge      nginx, publishes 8088            32m     |
  |   /            -> algolens-frontend:80                      |
  |   /auth/*      -> algolens-backend:5000                     |
  |   /portfolio/* -> algolens-backend:5000                     |
  |   /health      -> algolens-backend:5000                     |
  |   /edge-health -> edge itself                               |
  | algolens-frontend  static React build behind nginx  64m     |
  | algolens-backend   Flask/gunicorn, 2 workers        256m    |
  |                    networks: default + external `qt`        |
  | (trade-ngin, airflow-*: not managed here)                   |
  +-------------------------------------------------------------+
```

- `/auth`, `/portfolio` and `/health` are every backend path the frontend
  calls. A new backend path prefix needs a `location` in `deployment/edge.conf`.
  Nothing on the old host changes.
- The backend also joins the external Docker network `qt` (alias
  `algolens-backend`), which the trade-ngin desk-agent will share later.
- **Memory.** The box is a t2.medium (2 vCPU, 4 GiB RAM) shared with
  Postgres, trade-ngin and the data-ngin Airflow stack, and trade-ngin's
  live run (cron inside its container, 09:30 daily) must never be
  OOM-killed. Every AlgoLens container has a hard `mem_limit` (with no extra
  swap) and `oom_score_adj: 800`, so under pressure the kernel kills AlgoLens
  first. `deploy.sh` stops the old AlgoLens containers before it starts the
  new ones, so two copies never run side by side. Avoid deploying around 09:30.

Files:

| File | Purpose |
|---|---|
| `deployment/docker-compose.prod.yml` | the stack; images come in as `BACKEND_IMAGE` / `FRONTEND_IMAGE` digests |
| `deployment/edge.conf` | edge routing |
| `deployment/deploy.sh` | the roll, run on the box |
| `deployment/algolens.env.example` | backend variable names |
| `deployment/old-host-nginx-algolens.conf` | the old host's new server block |
| `deployment/algolens.conf` | the old host's previous server block, kept for reference and rollback |

## How a deploy works

Push to the `prod` branch (for example `git push origin main:prod`).
`.github/workflows/deploy.yml` then:

1. **quality**: runs AlgoLens CI (`ci.yml`, called as a reusable workflow):
   backend pytest, frontend build and vitest.
2. **backend-image / frontend-image**: `_publish-container.yml` builds
   `algolens-api` and `algolens-frontend` and pushes
   `ghcr.io/algogators/algolens-{backend,frontend}` tagged `latest`,
   `sha-<short>`, the full SHA and `prod`, and outputs the **digest**. The
   frontend is built with `VITE_API_URL=https://algolens.algogators.com`
   (override with the repo variable `ALGOLENS_PUBLIC_URL`).
3. **deploy**: SSHes to the box, logs in to GHCR with the run's token,
   clones `/home/ubuntu/algolens` on first use (sparse: `deployment/` only),
   fast-forwards it to the exact commit that was built, and runs
   `deployment/deploy.sh <backend@sha256:...> <frontend@sha256:...>`.
4. **health**: a second SSH step curls `http://localhost:8088/health` on the
   box and fails the job unless it returns 200. Port 8088 is not reachable
   from GitHub runners.

`deploy.sh`:
- dies if `/home/ubuntu/.config/algogators/algolens.env` is missing;
- `docker network create qt || true`;
- pulls both images;
- **pre-flight**: runs a one-off container of the new backend image
  (`docker compose run --rm backend`, so the env file is read exactly as the
  service reads it) that connects to the database. If that fails, the deploy
  stops before anything running is touched;
- stops `algolens-edge`, `algolens-frontend` and `algolens-backend` (memory:
  old and new never run side by side);
- runs `docker compose up -d --remove-orphans`;
- waits up to 3 minutes for readiness, `localhost:8088/health` (backend and
  database);
- **on failure rolls back automatically** to the pair recorded in
  `algolens.current-images` by the last good deploy (never the running
  containers' images, which may belong to a half-finished roll), waits for it
  to be healthy, and exits 1 either way;
- on success writes `algolens.previous-images` and `algolens.current-images`
  to `/home/ubuntu/.config/algogators/`, tags the images locally
  `algolens-{backend,frontend}:current` and `:previous` so `docker image
  prune` never removes a rollback target, and prints the rollback command;
- prunes dangling images older than 168h.

Health endpoints: `/health/live` is liveness (no database) and is the
containers' healthcheck, so a database outage does not mark the backend
unhealthy. `/health` is readiness (503 when the backend cannot reach the
database) and is the deploy gate, so a broken env file fails the deploy.

Logs: every service logs to json-file capped at 3 x 10 MB, set per service in
`docker-compose.prod.yml`. The Docker daemon config is shared with the live
trading engine and is left alone.

Manual runs: *Actions > Deploy AlgoLens > Run workflow*. `dry-run` (default on)
builds without pushing. Untick it and tick `deploy` on the `prod` branch to
redeploy.

### Repository secrets

| Secret | Value |
|---|---|
| `SSH_HOST` | the trade-ngin box, reachable from GitHub runners |
| `SSH_USER` | `ubuntu` |
| `SSH_KEY` | private key authorized for that user |

These have the same names as the data-ngin deploy secrets in
AlgoGators/algogators, but GitHub secrets are per repo, so set them on
AlgoGators/AlgoLens. The old `EC2_HOST`, `EC2_USER` and `EC2_SSH_KEY`
secrets are no longer used.

GHCR pushes use `GITHUB_TOKEN`. If `algolens-backend` and `algolens-frontend`
were first pushed by hand, grant AlgoGators/AlgoLens **Write** under each
package's *Package settings > Manage Actions access*, or the push returns 403.

## First-time bootstrap (trade-ngin box)

```bash
ssh ubuntu@ec2-18-118-225-224

# 1. Docker and the compose plugin (trade-ngin and airflow already use them)
docker --version && docker compose version
groups | grep -qw docker || echo "add ubuntu to the docker group"
git --version

# 2. Env file, outside any checkout so a git pull can never touch it.
#    Names: deployment/algolens.env.example. Copy the values the old host's
#    backend container uses, with FLASK_ENV=production, FLASK_DEBUG=False,
#    CORS_ORIGINS=https://algolens.algogators.com
mkdir -p ~/.config/algogators
nano ~/.config/algogators/algolens.env
chmod 600 ~/.config/algogators/algolens.env

# 3. Shared network for the desk-agent (deploy.sh also does this)
docker network create qt || true
```

`/home/ubuntu/algolens` is created by the first deploy. Do not create it by
hand.

**Security group** (trade-ngin box): add an inbound rule for **TCP 8088 from
the old host's private IP /32 only**. Never open it to `0.0.0.0/0`. The edge
publishes on `0.0.0.0:8088` and trusts the `X-Forwarded-*` headers it
receives, which is safe only because the old host is its sole client.

Then create the `prod` branch and push to it (`git push origin main:prod`),
and watch the workflow.

## Cutover (old host)

1. From the old host, check the stack over the private network:
   ```bash
   curl -fsS http://172.31.23.190:8088/health
   curl -fsS -o /dev/null -w '%{http_code}\n' http://172.31.23.190:8088/
   ```
2. Back up the current config:
   ```bash
   sudo cp /etc/nginx/conf.d/algolens.conf /etc/nginx/conf.d/algolens.conf.pre-docker
   ```
3. Install `deployment/old-host-nginx-algolens.conf` as
   `/etc/nginx/conf.d/algolens.conf`.
4. `sudo nginx -t && sudo systemctl reload nginx`
5. Check `https://algolens.algogators.com`: the page loads, login works, and
   the strategy list loads.
6. After a few quiet days, stop the old-host app processes: the bare
   `python3 backend/app.py` on 5001, the frontend container on 3000, the
   unrouted backend container on 5000, any systemd units, and the old cron
   deploy script. Until then they are the rollback target.

## Rollback

**Traffic back to the old host.** This works while its processes still run:

```bash
sudo cp /etc/nginx/conf.d/algolens.conf.pre-docker /etc/nginx/conf.d/algolens.conf && sudo nginx -t && sudo systemctl reload nginx
```

That restores `/` -> `localhost:3000` and `/auth`, `/portfolio` ->
`localhost:5001`.

**Previous AlgoLens version on the box.** A deploy that never becomes healthy
rolls itself back to the last good pair. To go back further by hand,
`deploy.sh` prints the exact command at the end of every deploy. In general:

```bash
cd ~/algolens && bash deployment/deploy.sh $(cat ~/.config/algogators/algolens.previous-images)
```

You can also re-run an earlier successful Deploy AlgoLens run.

## Operations

```bash
cat ~/.config/algogators/algolens.current-images
docker ps --filter name=algolens
docker stats --no-stream algolens-backend algolens-frontend algolens-edge
docker logs -f algolens-backend
# After editing algolens.env, re-run deploy.sh with the current images:
cd ~/algolens && bash deployment/deploy.sh $(cat ~/.config/algogators/algolens.current-images)
```

## Retired

These are no longer part of the deployment. Do not reinstall them:

- systemd units `algolens.service` (frontend via `npx serve`) and
  `algolens-backend.service` (bare Flask on 5001). Removed from the repo.
- the old deploy (GitHub Actions SSH plus the cron deploy script on the old
  host) that ran `git pull`, `npm ci && npm run build` and `pip3 install`,
  then restarted systemd. The server checkout had diverged, so it was failing
  anyway.
- the server-side git checkout in `/home/ec2-user/AlgoLens` and the
  `:latest` containers started from the repo-root `docker-compose.prod.yml`.
