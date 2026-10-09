
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

Key file: `dominick-pem.pem` — **not in the repo**, get it from a team member.

```bash
ssh -i "/path/to/dominick-pem.pem" ec2-user@ec2-18-226-98-126.us-east-2.compute.amazonaws.com
```

On Windows, restrict the key file permissions first:
```powershell
icacls "C:\path\to\dominick-pem.pem" /inheritance:r /grant:r "$($env:USERNAME):R"
```

### Useful server commands

```bash
# Nginx
sudo systemctl status nginx
sudo nginx -t && sudo systemctl reload nginx
sudo journalctl -u nginx -n 50

# Frontend service
sudo systemctl status algolens
sudo systemctl restart algolens

# Backend Docker container
docker ps
docker logs algolens-docker-backend-1 --tail 50
docker restart algolens-docker-backend-1

# Memory / swap
free -h
```

> **Note:** The 2 GB swapfile (`/swapfile`) was added manually to prevent OOM during builds. It is enabled at boot via `/etc/fstab`. Do not remove it.
