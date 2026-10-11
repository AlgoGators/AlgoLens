#!/usr/bin/env bash
# Renew the Let's Encrypt certificate for algolens.algogators.com and reload
# the edge. Run from root's cron (algolens-tls.cron). certbot only renews
# within 30 days of expiry, so running it often is harmless. Challenges are
# answered over HTTP-01 from /var/www/certbot, which algolens-edge serves on
# port 80.
set -euo pipefail

docker run --rm \
    -v /etc/letsencrypt:/etc/letsencrypt \
    -v /var/lib/letsencrypt:/var/lib/letsencrypt \
    -v /var/www/certbot:/var/www/certbot \
    certbot/certbot:v3.1.0 renew --webroot -w /var/www/certbot --quiet

# A reload picks up a renewed certificate; it is a no-op otherwise.
docker exec algolens-edge nginx -s reload
