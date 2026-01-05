#!/bin/bash

# One-time SSL certificate setup script for AlgoLens
# Run this on your EC2 instance after DNS is configured

set -e

echo "=== AlgoLens SSL Setup ==="
echo ""

# Check if running on EC2
if [ ! -f /home/ec2-user/.bashrc ]; then
    echo "Warning: This script should be run on your EC2 instance"
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

echo "Step 1: Installing Certbot..."
sudo yum install -y certbot python3-certbot-nginx

echo ""
echo "Step 2: Testing DNS resolution..."
if ! nslookup algolens.algogators.com | grep -q "18.226.98.126"; then
    echo "WARNING: DNS may not be configured correctly yet."
    echo "Make sure algolens.algogators.com points to 18.226.98.126"
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

echo ""
echo "Step 3: Temporarily updating Nginx config for certificate challenge..."
# Create a temporary HTTP-only config for certbot
sudo tee /etc/nginx/conf.d/algolens.conf > /dev/null << 'EOF'
server {
    listen 80;
    server_name algolens.algogators.com;

    location / {
        proxy_pass http://localhost:3000;
        proxy_set_header Host $host;
    }
}
EOF

sudo nginx -t && sudo systemctl restart nginx

echo ""
echo "Step 4: Obtaining SSL certificate..."
sudo certbot --nginx -d algolens.algogators.com --non-interactive --agree-tos --email [email protected] --redirect

echo ""
echo "Step 5: Restoring full Nginx configuration..."
cd /home/ec2-user/AlgoLens
sudo cp nginx.conf /etc/nginx/conf.d/algolens.conf
sudo nginx -t && sudo systemctl restart nginx

echo ""
echo "Step 6: Setting up automatic certificate renewal..."
sudo systemctl enable certbot-renew.timer
sudo systemctl start certbot-renew.timer

echo ""
echo "=== Setup Complete! ==="
echo ""
echo "Your site should now be accessible at: https://algolens.algogators.com"
echo "SSL certificate will auto-renew before expiration."
echo ""
echo "Next steps:"
echo "1. Test the site: curl -I https://algolens.algogators.com"
echo "2. Update your Wix button to point to https://algolens.algogators.com"
echo ""
