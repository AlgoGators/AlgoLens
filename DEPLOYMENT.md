# AlgoLens Deployment Guide

## Overview

The frontend is a static Vite/React build served by nginx on an AWS EC2 instance. **Builds happen on your local machine** — never on the server. You compile the app, then copy the output files to EC2.

---

## Prerequisites

### 1. SSH Access (required)
You need the `dominick-pem.pem` private key to connect to the EC2 instance. **This file is not in the repo** — get it from a current team member and place it at:
```
~/Downloads/dominick-pem.pem     # or anywhere you prefer
```
Then restrict its permissions (required by SSH):
```bash
chmod 400 ~/Downloads/dominick-pem.pem
```

### 2. Node.js
Make sure you have Node.js installed (`node -v`). v18+ recommended.

---

## Deploy Steps

### 1. Install dependencies (first time only)
```bash
npm install
```

### 2. Build the app
```bash
npm run build
```
This outputs compiled files to the `build/` folder.

### 3. Push to EC2
```bash
scp -i "/path/to/dominick-pem.pem" -r ./build/. ec2-user@ec2-18-226-98-126.us-east-2.compute.amazonaws.com:/home/ec2-user/AlgoLens/build/
```
Replace `/path/to/dominick-pem.pem` with the actual path to your key file.

**One-liner (build + deploy):**
```bash
npm run build && scp -i "/path/to/dominick-pem.pem" -r ./build/. ec2-user@ec2-18-226-98-126.us-east-2.compute.amazonaws.com:/home/ec2-user/AlgoLens/build/
```

That's it. Nginx picks up the new files immediately — no server restart needed.

---

## Server Info

| | |
|---|---|
| **URL** | https://algolens.algogators.com |
| **EC2 host** | ec2-18-226-98-126.us-east-2.compute.amazonaws.com |
| **EC2 user** | ec2-user |
| **Build path on server** | `/home/ec2-user/AlgoLens/build/` |
| **Web server** | nginx (static file serving) |
| **Backend API** | runs on `localhost:5001` on the same instance |

---

## SSH into the server (for debugging)
```bash
ssh -i "/path/to/dominick-pem.pem" ec2-user@ec2-18-226-98-126.us-east-2.compute.amazonaws.com
```

Useful commands once inside:
```bash
sudo systemctl status nginx        # check nginx is running
sudo nginx -t                      # validate nginx config
sudo systemctl reload nginx        # reload config (no downtime)
sudo journalctl -u nginx -n 50     # view nginx logs
```

---

## Do I need the pem file?

**Yes.** The pem file is the SSH private key that grants access to the EC2 instance. It is intentionally not committed to this repo for security reasons. Anyone deploying needs to obtain it from a current team member — do not share it over email or public channels. Use a password manager or a private Slack DM.
