
# AlgoLens — Investment Portfolio App

The original Figma design is available at https://www.figma.com/design/ZeqHCUFlWocwglts4flaFG/Investment-Portfolio-App.

---

## Architecture

| Component | Port | How it runs |
|---|---|---|
| Frontend (React/Vite) | 3000 | `algolens.service` via `npx serve ./build` |
| Backend API (Flask/gunicorn) | 5000 | Docker container `algolens-docker-backend-1` |
| ~~Legacy backend~~ | ~~5001~~ | `algolens-backend.service` — **do not use**, has no DB credentials |
| Nginx (public) | 80 / 443 | Reverse proxy: `/` → 3000, `/auth` + `/portfolio` → 5000 |

**Database:** PostgreSQL at `13.58.153.216:5432`, database `new_algo_data`

---

## Local Development

```bash
npm install
npm run dev       # frontend dev server at http://localhost:5173
```

For the backend locally, create `backend/.env` (see `backend/.env.example`) and run:

```bash
cd backend
pip install -r requirements.txt
python app.py     # runs at http://localhost:5000
```

---

## Production Deployment

Pushing to `main` triggers the GitHub Actions workflow (`.github/workflows/deploy.yml`), which:

1. SSHes into the EC2 instance
2. Runs `git pull origin main`
3. Runs `npm ci && npm run build` on EC2 (2 GB swap is provisioned to handle this)
4. Copies `deployment/` service and nginx configs, reloads nginx
5. Restarts `algolens` (frontend) and `algolens-backend` (legacy systemd backend) services

> The Docker backend container (`algolens-docker-backend-1`) is **not** restarted by CI/CD — restart it manually if you change backend env vars or the Docker image.

### Environment files on EC2 (not in git)

| File | Purpose |
|---|---|
| `/home/ec2-user/AlgoLens/.env` | `VITE_API_URL=https://algolens.algogators.com` — baked into the frontend build |
| `/home/ec2-user/algolens-docker/.env` | DB credentials and JWT secret for the backend Docker container |

If you need to change DB credentials or the DB name, update `/home/ec2-user/algolens-docker/.env` and run:
```bash
docker restart algolens-docker-backend-1
```

### Adding new API routes

1. Add the route to the Flask backend
2. Add a `location` block in `deployment/algolens.conf` pointing to `http://localhost:5000/<route>`
3. Push to `main` — CI/CD will deploy the new nginx config automatically

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
