#!/usr/bin/env bash
# Roll the AlgoLens stack on the trade-ngin box to one pair of image digests.
#
#   deploy.sh ghcr.io/algogators/algolens-backend@sha256:... \
#             ghcr.io/algogators/algolens-frontend@sha256:...
#
# CI (.github/workflows/deploy.yml, on a push to `prod`) fast-forwards the
# sparse checkout at /home/ubuntu/algolens to the commit it built, then runs
# this script from that checkout. Rolling back is the same command with the
# previous refs, which this script records in $STATE_DIR/algolens.previous-images.
#
# Steps: pull both images, stop the running AlgoLens containers (memory), start
# the new ones, wait for http://localhost:8088/health, record state, prune.
set -euo pipefail

BACKEND_IMAGE="${1:?usage: deploy.sh <backend-image-ref> <frontend-image-ref>}"
FRONTEND_IMAGE="${2:?usage: deploy.sh <backend-image-ref> <frontend-image-ref>}"
DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="${STATE_DIR:-/home/ubuntu/.config/algogators}"
ALGOLENS_ENV_FILE="${ALGOLENS_ENV_FILE:-$STATE_DIR/algolens.env}"
HEALTH_URL="${HEALTH_URL:-http://localhost:8088/health}"
# AlgoLens' own containers, stopped before the new ones start.
CONTAINERS=(algolens-edge algolens-frontend algolens-backend)

log() { echo "[$(date -Is)] $*"; }
die() { echo "::error::$*" >&2; exit 1; }

[ -f "$ALGOLENS_ENV_FILE" ] || die "env file $ALGOLENS_ENV_FILE is missing (see deployment/DEPLOYMENT.md)"

export BACKEND_IMAGE FRONTEND_IMAGE ALGOLENS_ENV_FILE
compose() {
    docker compose -f "$DEPLOY_DIR/docker-compose.prod.yml" "$@"
}

# The backend joins the network the trade-ngin desk-agent will share.
docker network create qt >/dev/null 2>&1 || true

log "pulling $BACKEND_IMAGE"
docker pull "$BACKEND_IMAGE"
log "pulling $FRONTEND_IMAGE"
docker pull "$FRONTEND_IMAGE"
compose pull edge

prev_backend=$(docker inspect algolens-backend --format '{{.Config.Image}}' 2>/dev/null || true)
prev_frontend=$(docker inspect algolens-frontend --format '{{.Config.Image}}' 2>/dev/null || true)
case "$prev_backend|$prev_frontend" in
    ghcr.io/*@sha256:*\|ghcr.io/*@sha256:*)
        rollback="$DEPLOY_DIR/deploy.sh $prev_backend $prev_frontend" ;;
    *)
        rollback="point the old host's nginx back at localhost:3000/5001 (deployment/DEPLOYMENT.md, Rollback)" ;;
esac

# Stop the running AlgoLens containers before starting the new ones: the box
# has ~200 MB free, and old and new side by side would push the OOM killer
# toward trade-ngin or Airflow.
for c in "${CONTAINERS[@]}"; do
    if docker ps --format '{{.Names}}' | grep -qx "$c"; then
        log "stopping $c"
        docker stop "$c" >/dev/null
    fi
done

log "starting backend=$BACKEND_IMAGE frontend=$FRONTEND_IMAGE"
compose up -d --remove-orphans

log "waiting for $HEALTH_URL"
healthy=0
for _ in $(seq 1 36); do
    if curl -fsS --max-time 5 "$HEALTH_URL" >/dev/null 2>&1; then
        healthy=1
        break
    fi
    sleep 5
done
if [ "$healthy" -ne 1 ]; then
    compose ps >&2 || true
    compose logs --tail=60 backend edge >&2 || true
    die "AlgoLens never became healthy at $HEALTH_URL; roll back with: $rollback"
fi

mkdir -p "$STATE_DIR"
if [ -n "$prev_backend" ] && [ "$prev_backend|$prev_frontend" != "$BACKEND_IMAGE|$FRONTEND_IMAGE" ]; then
    printf '%s %s\n' "$prev_backend" "$prev_frontend" > "$STATE_DIR/algolens.previous-images"
fi
printf '%s %s\n' "$BACKEND_IMAGE" "$FRONTEND_IMAGE" > "$STATE_DIR/algolens.current-images"

docker image prune -f --filter 'until=168h' >/dev/null
log "deployed backend=$BACKEND_IMAGE frontend=$FRONTEND_IMAGE"
log "rollback: $rollback"
