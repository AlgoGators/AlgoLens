#!/usr/bin/env bash
# Roll the AlgoLens stack on the trade-ngin box to one pair of image digests.
#
#   deploy.sh ghcr.io/algogators/algolens-backend@sha256:... \
#             ghcr.io/algogators/algolens-frontend@sha256:...
#
# CI (.github/workflows/deploy.yml, on a push to `prod`) fast-forwards the
# sparse checkout at /home/ubuntu/algolens to the commit it built, then runs
# this script from that checkout.
#
# Steps:
#   1. pull both images;
#   2. pre-flight: a one-off container of the NEW backend image (`docker
#      compose run --rm`, which reads the env file exactly as the service
#      does) connects to the database. If that fails the deploy stops here and
#      the running stack is left alone;
#   3. stop the running AlgoLens containers (memory: old and new never run side
#      by side), start the new ones;
#   4. wait for readiness, http://localhost:8088/health (backend + database);
#   5. on failure, roll back automatically to the images recorded in
#      $STATE_DIR/algolens.current-images by the last good deploy, and exit 1;
#   6. on success, record current/previous images, tag them locally
#      (algolens-{backend,frontend}:current and :previous) so `docker image
#      prune` never removes a rollback target, and prune.
#
# The containers' own healthcheck is liveness (/health/live, no database), so
# a database outage does not mark the backend unhealthy; the deploy gate is
# readiness (/health, 503 without the database).
set -euo pipefail

BACKEND_IMAGE="${1:?usage: deploy.sh <backend-image-ref> <frontend-image-ref>}"
FRONTEND_IMAGE="${2:?usage: deploy.sh <backend-image-ref> <frontend-image-ref>}"
DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="${STATE_DIR:-/home/ubuntu/.config/algogators}"
ALGOLENS_ENV_FILE="${ALGOLENS_ENV_FILE:-$STATE_DIR/algolens.env}"
HEALTH_URL="${HEALTH_URL:-http://localhost:8088/health}"
# Readiness wait: HEALTH_TRIES x HEALTH_SLEEP seconds (default 3 minutes).
HEALTH_TRIES="${HEALTH_TRIES:-36}"
HEALTH_SLEEP="${HEALTH_SLEEP:-5}"
PREFLIGHT_TIMEOUT="${PREFLIGHT_TIMEOUT:-60}"
CURRENT_FILE="$STATE_DIR/algolens.current-images"
PREVIOUS_FILE="$STATE_DIR/algolens.previous-images"
# AlgoLens' own containers, stopped before the new ones start.
CONTAINERS=(algolens-edge algolens-frontend algolens-backend)

log() { echo "[$(date -Is)] $*"; }
die() { echo "::error::$*" >&2; exit 1; }

[ -f "$ALGOLENS_ENV_FILE" ] || die "env file $ALGOLENS_ENV_FILE is missing (see deployment/DEPLOYMENT.md)"

export BACKEND_IMAGE FRONTEND_IMAGE ALGOLENS_ENV_FILE
compose() {
    docker compose -f "$DEPLOY_DIR/docker-compose.prod.yml" "$@"
}

# The last good pair, recorded by the previous successful deploy (never read
# from the running containers, which may be a half-finished roll).
prev_backend=""
prev_frontend=""
if [ -s "$CURRENT_FILE" ]; then
    read -r prev_backend prev_frontend _ < "$CURRENT_FILE" || true
fi

# The backend joins the network it shares with the trade-ngin engine-rpc container.
docker network create qt >/dev/null 2>&1 || true

log "pulling $BACKEND_IMAGE"
docker pull "$BACKEND_IMAGE"
log "pulling $FRONTEND_IMAGE"
docker pull "$FRONTEND_IMAGE"
compose pull edge

# Pre-flight readiness of the database, from the new image, before anything
# running is touched: a short-lived one-off backend container (no edge, no
# frontend) under the service's memory cap, reading the env file exactly as
# the service does.
log "pre-flight: database from $BACKEND_IMAGE"
docker rm -f algolens-preflight >/dev/null 2>&1 || true
if ! timeout "$PREFLIGHT_TIMEOUT" docker compose -f "$DEPLOY_DIR/docker-compose.prod.yml" \
        run --rm --no-deps -T --name algolens-preflight --entrypoint python backend -c \
        'from algolens.infrastructure.db.postgres import get_db_connection
conn = get_db_connection()
with conn.cursor() as cursor:
    cursor.execute("SELECT 1")
conn.close()
print("database ok")'; then
    die "pre-flight failed: the new backend image cannot reach the database with $ALGOLENS_ENV_FILE; nothing was stopped"
fi

stop_running() {
    for c in "${CONTAINERS[@]}"; do
        if docker ps --format '{{.Names}}' | grep -qx "$c"; then
            log "stopping $c"
            docker stop "$c" >/dev/null
        fi
    done
}

start_stack() {  # <backend-ref> <frontend-ref>
    BACKEND_IMAGE="$1" FRONTEND_IMAGE="$2" compose up -d --remove-orphans
}

wait_ready() {
    local _
    for _ in $(seq 1 "$HEALTH_TRIES"); do
        if curl -fsS --max-time 5 "$HEALTH_URL" >/dev/null 2>&1; then
            return 0
        fi
        sleep "$HEALTH_SLEEP"
    done
    return 1
}

# Stop the running AlgoLens containers before starting the new ones: the box
# has ~200 MB free, and old and new side by side would push the OOM killer
# toward trade-ngin or Airflow.
stop_running

log "starting backend=$BACKEND_IMAGE frontend=$FRONTEND_IMAGE"
started=1
start_stack "$BACKEND_IMAGE" "$FRONTEND_IMAGE" || started=0

log "waiting for $HEALTH_URL"
if [ "$started" -ne 1 ] || ! wait_ready; then
    compose ps >&2 || true
    compose logs --tail=60 backend edge >&2 || true
    if [ -n "$prev_backend" ] && [ -n "$prev_frontend" ] \
        && [ "$prev_backend|$prev_frontend" != "$BACKEND_IMAGE|$FRONTEND_IMAGE" ]; then
        log "ROLLING BACK to backend=$prev_backend frontend=$prev_frontend"
        stop_running
        if start_stack "$prev_backend" "$prev_frontend" && wait_ready; then
            die "AlgoLens never became healthy at $HEALTH_URL; rolled back to $prev_backend $prev_frontend, which is healthy"
        fi
        die "AlgoLens never became healthy at $HEALTH_URL, and the rollback to $prev_backend $prev_frontend is not healthy either; see deployment/DEPLOYMENT.md, Rollback"
    fi
    die "AlgoLens never became healthy at $HEALTH_URL and there is no earlier deploy to roll back to (see deployment/DEPLOYMENT.md, Rollback)"
fi

mkdir -p "$STATE_DIR"
if [ -n "$prev_backend" ] && [ "$prev_backend|$prev_frontend" != "$BACKEND_IMAGE|$FRONTEND_IMAGE" ]; then
    printf '%s %s\n' "$prev_backend" "$prev_frontend" > "$PREVIOUS_FILE"
fi
printf '%s %s\n' "$BACKEND_IMAGE" "$FRONTEND_IMAGE" > "$CURRENT_FILE"

# Local tags keep the current and previous images out of reach of prune
# (pulled by digest they are otherwise untagged, i.e. dangling once their
# container is gone).
tag_pair() {  # <name> <current-ref> <previous-ref>
    if [ -n "$3" ] && docker image inspect "$3" >/dev/null 2>&1; then
        docker tag "$3" "$1:previous"
    fi
    docker tag "$2" "$1:current"
}
if [ -s "$PREVIOUS_FILE" ]; then
    read -r tagged_prev_backend tagged_prev_frontend _ < "$PREVIOUS_FILE" || true
fi
tag_pair algolens-backend "$BACKEND_IMAGE" "${tagged_prev_backend:-}"
tag_pair algolens-frontend "$FRONTEND_IMAGE" "${tagged_prev_frontend:-}"

docker image prune -f --filter 'until=168h' >/dev/null
rollback="$DEPLOY_DIR/deploy.sh $(cat "$PREVIOUS_FILE" 2>/dev/null || echo '<no previous deploy recorded>')"
log "deployed backend=$BACKEND_IMAGE frontend=$FRONTEND_IMAGE"
log "rollback: $rollback"
