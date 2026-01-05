# Domain Setup Guide for AlgoLens

This guide will help you configure `algolens.algogators.com` to point to your AlgoLens application.

## Prerequisites

- Access to your domain registrar (where you manage algogators.com)
- SSH access to your EC2 instance
- EC2 security group allowing inbound traffic on ports 80 and 443

## Step 1: Configure DNS

1. Log in to your domain registrar (e.g., GoDaddy, Namecheap, Google Domains)
2. Navigate to DNS settings for `algogators.com`
3. Add a new **A Record**:
   - **Name/Host**: `algolens`
   - **Type**: `A`
   - **Value/Points to**: `18.226.98.126`
   - **TTL**: `300` (or leave as default)
4. Save the DNS record
5. Wait 5-10 minutes for DNS propagation

**Verify DNS is working:**
```bash
nslookup algolens.algogators.com
```
You should see `18.226.98.126` in the response.

## Step 2: Configure EC2 Security Group

Ensure your EC2 security group allows inbound traffic:

1. Go to AWS Console → EC2 → Security Groups
2. Find your instance's security group
3. Add these inbound rules if not already present:
   - **Port 80** (HTTP): Source `0.0.0.0/0`
   - **Port 443** (HTTPS): Source `0.0.0.0/0`

## Step 3: Deploy Updated Configuration

1. Commit and push the changes to GitHub:
   ```bash
   git add .
   git commit -m "Configure Nginx reverse proxy for algolens.algogators.com"
   git push origin main
   ```

2. Wait for GitHub Actions deployment to complete (check the Actions tab)

## Step 4: Set Up SSL Certificate (One-Time)

SSH into your EC2 instance and run the setup script:

```bash
ssh -i your-key.pem ec2-user@18.226.98.126
cd /home/ec2-user/AlgoLens
chmod +x setup-ssl.sh
./setup-ssl.sh
```

This script will:
- Install Certbot
- Verify DNS configuration
- Obtain SSL certificate from Let's Encrypt
- Configure automatic certificate renewal

## Step 5: Test Your Setup

```bash
# Test HTTP redirect to HTTPS
curl -I http://algolens.algogators.com

# Test HTTPS
curl -I https://algolens.algogators.com

# Or simply open in browser:
# https://algolens.algogators.com
```

## Step 6: Update Wix Button

1. Log in to your Wix dashboard
2. Find the "AlgoLens" button
3. Update the link from `http://18.226.98.126:3000` to:
   ```
   https://algolens.algogators.com
   ```
4. Publish your Wix site

## Troubleshooting

### DNS not resolving
- Wait longer (DNS can take up to 24 hours, though usually 5-10 minutes)
- Check DNS with: `nslookup algolens.algogators.com`
- Verify A record was saved correctly in your registrar

### Cannot connect on port 80/443
- Check EC2 security group inbound rules
- Verify Nginx is running: `sudo systemctl status nginx`

### SSL certificate error
- Ensure DNS is fully propagated before running setup-ssl.sh
- Check Nginx logs: `sudo tail -f /var/log/nginx/error.log`
- Verify Certbot: `sudo certbot certificates`

### Site not loading
- Check frontend service: `sudo systemctl status algolens`
- Check Nginx: `sudo systemctl status nginx`
- View logs: `sudo journalctl -u algolens -n 50`

## Architecture

```
User Browser
    ↓
https://algolens.algogators.com
    ↓
DNS (A Record) → 18.226.98.126
    ↓
EC2 Instance
    ↓
Nginx (Port 443) → SSL Termination
    ↓
Frontend Service (localhost:3000)
Backend Service (localhost:5000)
```

## Automatic Certificate Renewal

Let's Encrypt certificates expire after 90 days. Certbot automatically renews them via a systemd timer. Check renewal status:

```bash
sudo systemctl status certbot-renew.timer
sudo certbot renew --dry-run
```
