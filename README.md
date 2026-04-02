
# AlgoLens — Investment Portfolio App

The original Figma design is available at https://www.figma.com/design/ZeqHCUFlWocwglts4flaFG/Investment-Portfolio-App.

## Local Development

```bash
npm install
npm run dev       # starts dev server at http://localhost:3000
```

---

## Production Deployment

**Never build on the EC2 instance.** The server is a small instance (limited RAM/CPU). All builds happen locally; only the compiled static files are pushed to the server.

### First-time setup (already done — reference only)

The EC2 instance runs nginx to serve static files directly. No Node.js process is needed for the frontend.

`/etc/nginx/conf.d/algolens.conf` uses:
```nginx
root /home/ec2-user/AlgoLens/build;
location / {
    try_files $uri $uri/ /index.html;
}
```

The `algolens.service` (which ran `serve` on port 3000) has been stopped and disabled.

---

### Deploy pipeline

Run these commands from the repo root on your local machine:

**1. Build the app**
```bash
npm run build
```

**2. Push the build to EC2**
```bash
rsync -avz --delete -e "ssh -i ~/Documents/GitHub/dominick-pem.pem" \
  ./build/ \
  ec2-user@ec2-18-226-98-126.us-east-2.compute.amazonaws.com:/home/ec2-user/AlgoLens/build/
```

**3. Done.** Nginx picks up the new files immediately — no restart needed.

> Tip: combine into one command for quick deploys:
> ```bash
> npm run build && rsync -avz --delete -e "ssh -i ~/Documents/GitHub/dominick-pem.pem" ./build/ ec2-user@ec2-18-226-98-126.us-east-2.compute.amazonaws.com:/home/ec2-user/AlgoLens/build/
> ```

---

### SSH access

```bash
ssh -i ~/Documents/GitHub/dominick-pem.pem ec2-user@ec2-18-226-98-126.us-east-2.compute.amazonaws.com
```

### Useful server commands

```bash
sudo systemctl status nginx          # check nginx
sudo nginx -t                        # test nginx config
sudo systemctl reload nginx          # reload config (no downtime)
sudo journalctl -u nginx -n 50       # nginx logs
```
