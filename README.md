
# AlgoLens — Investment Portfolio App

The original Figma design is available at https://www.figma.com/design/ZeqHCUFlWocwglts4flaFG/Investment-Portfolio-App.

---

## Architecture

| Component | Where | How it runs |
|---|---|---|
| Frontend (React/Vite) | trade-ngin host | `algolens-frontend` container (static build behind nginx) |
| Backend API (Flask/gunicorn) | trade-ngin host | `algolens-backend` container on :5000, also on the `qt` network |
| Edge router | trade-ngin host, :8088 | nginx container: `/` -> frontend, `/auth` `/portfolio` `/health` -> backend |
| TLS | old EC2 host, 443 | nginx proxies `algolens.algogators.com` to the edge on the private IP |

**Database:** PostgreSQL at `13.58.153.216:5432`, database `new_algo_data`

### QT desk: AlgoLens and trade-ngin call each other

AlgoLens and the engine (trade-ngin) **talk directly over gRPC**, and Postgres stays the record of everything they do.

| Direction | How | What |
|---|---|---|
| AlgoLens → engine | gRPC to `desk-agent:50051` on the private Docker network `qt` (env `DESK_AGENT_ADDR`, 3 s timeout) | `RunDesk` (a save), `RequestOverride`, `RecordDecision`, `Publish`, `GetRunStatus`. Contract: `algolens-api/proto/qt/v1/desk.proto`, vendored from trade-ngin `proto/qt/v1/desk.proto` |
| Engine → AlgoLens | Postgres (`new_algo_data`) | The three books in `trading.positions` (`system`, `qt_proposal`, `qt`), the command log `trading.position_overrides` (status and result of every command), and `live_run_metadata.published_by` / `published_at` and `settings_used` |

**How a command works:**
1. AlgoLens writes the command row to `trading.position_overrides` first, then calls the matching RPC with the row's id.
2. The engine answers `ACCEPTED`, does the work, and moves the row to `done`, `refused` or `failed`.
3. The page polls the row.
4. If the gRPC call fails, nothing is lost: the desk-agent re-drives every `pending` row every 60 s.

**The rest of the setup:**
- **E-mail:** override approval links go to the VP and the President (env `QT_APPROVERS`, set on both sides). Publish e-mails come from the engine.
- **Feature flag:** the desk UI and its write routes sit behind `QT_DESK_ENABLED`.
- **Spec:** trade-ngin `docs/design/qt-contract.md` and `docs/design/qt-master-rulings.md`. The gRPC channel amends the master document's original "never call each other" (decided 2026-10-09).

---

## Local Development

```bash
cd algolens-frontend
npm install
npm run dev       # frontend dev server at http://localhost:3000
```

For the backend locally, from the repo root create `algolens-api/.env` (see `algolens-api/.env.example`) and run:

```bash
cd algolens-api
pip install -r requirements.txt
python app.py     # runs at http://localhost:5000
```

---

## Production Deployment

A push to the `prod` branch runs `.github/workflows/deploy.yml`: the CI gate, then both images are built and pushed to GHCR, then the trade-ngin box fast-forwards its sparse checkout of `deployment/` and runs `deployment/deploy.sh` with the two image digests. The job fails unless `http://localhost:8088/health` on the box returns 200.

Topology, host bootstrap, cutover and rollback: [deployment/DEPLOYMENT.md](deployment/DEPLOYMENT.md).

### Adding new API routes

1. Add the route to the Flask backend
2. If it uses a new path prefix, add a `location` block for it in `deployment/edge.conf`
3. Merge to `main`, then push `main` to `prod`; the deploy ships the updated edge config

---

## SSH Access

AlgoLens runs on the trade-ngin box. The key is `prod-deploy.pem`; it is **not in the repo**, so get it from a team member.

```bash
ssh -i "/path/to/prod-deploy.pem" ubuntu@ec2-18-118-225-224.us-east-2.compute.amazonaws.com
```

TLS for `algolens.algogators.com` stays on the old host (`ec2-user@ec2-18-226-98-126`, `dominick-pem.pem`), in `/etc/nginx/conf.d/algolens.conf`.

On Windows, restrict the key file permissions first:
```powershell
icacls "C:\path	o\prod-deploy.pem" /inheritance:r /grant:r "$($env:USERNAME):R"
```

### Useful server commands (trade-ngin box)

```bash
docker ps --filter name=algolens          # edge, frontend, backend
docker logs algolens-backend --tail 50
curl -s localhost:8088/health             # through the edge
cat ~/.config/algogators/algolens.previous-images   # what a rollback would restore
docker ps --filter name=desk-agent        # the engine side of the QT desk (/home/ubuntu/qt-engine)
```
