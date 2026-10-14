#!/usr/bin/env bash
# Take a READ-ONLY snapshot of production new_algo_data for the simulator.
#
# Dom runs this by hand (it is never run by tooling). It only reads: pg_dump and
# `\copy (SELECT ...) TO STDOUT`, streamed back over ssh. Nothing is written on the server,
# no file, no table.
#
#   bash sim/snapshot.sh                 # writes sim/data/snapshot-<UTC timestamp>/
#   bash sim/snapshot.sh my-name         # writes sim/data/my-name/
#
# Then: bash sim/simctl load sim/data/<that directory>
#
# What it takes (all gzip-compressed):
#   schema.sql.gz         schema only of trading, metadata, futures_data, auth, ops, investor
#                         (the ones present), --no-owner --no-privileges
#   data.sql.gz           every row of metadata.contract_metadata, futures_data.ohlcv_1d (the
#                         engine's market data, ~3 years), ops.data_ready and
#                         trading.strategy_registry
#   trading.<t>.csv.gz    rows of the QT portfolios only (QT_CONSERVATIVE_PORTFOLIO,
#                         QT_CONSERVATIVE_MODEL_PORTFOLIO) of positions, executions,
#                         live_results, live_run_metadata, equity_curve, position_overrides,
#                         strategy_config and signals (the ones present)
#   server_version        the server's version (restore into the same major version: PG_IMAGE)
# Not taken: auth.users rows and any other user data. The simulator seeds its own users.
#
# Database login: the read role in ~/.config/algogators/db-app-roles.env on the host, when that
# file sets PGUSER and PGPASSWORD; otherwise you are asked here and the answers are sent to the
# server over the ssh connection's stdin (never on a command line).
set -euo pipefail

SSH_HOST="${SNAPSHOT_SSH_HOST:-ubuntu@ec2-18-118-225-224.us-east-2.compute.amazonaws.com}"
SSH_KEY="${SNAPSHOT_SSH_KEY:-C:/Users/domdd/Documents/GitHub/prod-deploy.pem}"
DB_NAME="new_algo_data"
ROLES_FILE='~/.config/algogators/db-app-roles.env'
QT_PORTFOLIOS="'QT_CONSERVATIVE_PORTFOLIO','QT_CONSERVATIVE_MODEL_PORTFOLIO'"
SCHEMAS=(trading metadata futures_data auth ops investor)
FULL_TABLES=(metadata.contract_metadata futures_data.ohlcv_1d ops.data_ready trading.strategy_registry)
QT_TABLES=(positions executions live_results live_run_metadata equity_curve position_overrides
           strategy_config signals)

here="$(cd "$(dirname "$0")" && pwd)"
name="${1:-snapshot-$(date -u +%Y%m%d-%H%M%S)}"
out="$here/data/$name"
if [ -e "$out" ]; then
    echo "snapshot: $out already exists" >&2
    exit 1
fi

ssh_q() { ssh -i "$SSH_KEY" -o BatchMode=yes -o ConnectTimeout=15 "$SSH_HOST" "$@"; }

# Whether the host's roles file provides the login.
creds_from_file=no
if ssh_q "f=$ROLES_FILE; [ -f \"\$f\" ] && (set -a; . \"\$f\"; [ -n \"\${PGUSER:-}\" ] && [ -n \"\${PGPASSWORD:-}\" ])" </dev/null; then
    creds_from_file=yes
    echo "snapshot: using PGUSER/PGPASSWORD from $ROLES_FILE on the host"
    login=""
else
    echo "snapshot: $ROLES_FILE on the host has no PGUSER/PGPASSWORD; enter a READ-ONLY login"
    read -r -p "  PGUSER: " pg_user
    read -r -s -p "  PGPASSWORD: " pg_password
    echo
    login="$pg_user"$'\n'"$pg_password"$'\n'
fi

# Runs a command on the host with the login in the environment and a read-only session.
# The command is passed as one argument to `bash -c` on the host; stdout comes back here.
remote() {
    local cmd="$1"
    local prelude
    if [ "$creds_from_file" = yes ]; then
        prelude="set -a; . $ROLES_FILE; set +a;"
    else
        prelude="IFS= read -r PGUSER; IFS= read -r PGPASSWORD; export PGUSER PGPASSWORD;"
    fi
    printf '%s' "$login" | ssh_q "bash -c $(printf '%q' "set -euo pipefail; $prelude export PGHOST=\${PGHOST:-localhost} PGDATABASE=$DB_NAME PGOPTIONS='-c default_transaction_read_only=on'; $cmd")"
}

mkdir -p "$out"
echo "snapshot: writing $out"

remote "psql -XAtc 'SHOW server_version'" > "$out/server_version"
echo "  server_version $(cat "$out/server_version")"

present_schemas=$(remote "psql -XAtc \"SELECT string_agg(nspname, ' ') FROM pg_namespace WHERE nspname IN ($(printf "'%s'," "${SCHEMAS[@]}" | sed 's/,$//'))\"")
echo "  schemas: $present_schemas"
schema_args=""
for s in $present_schemas; do schema_args+=" -n $s"; done

echo "  schema.sql.gz"
remote "pg_dump --schema-only --no-owner --no-privileges $schema_args" | gzip > "$out/schema.sql.gz"

table_present() {
    remote "psql -XAtc \"SELECT to_regclass('$1') IS NOT NULL\""
}

full_args=""
for t in "${FULL_TABLES[@]}"; do
    if [ "$(table_present "$t")" = t ]; then full_args+=" -t $t"; else echo "  (no $t)"; fi
done
echo "  data.sql.gz:$full_args"
remote "pg_dump --data-only --no-owner --no-privileges --disable-triggers $full_args" | gzip > "$out/data.sql.gz"

for t in "${QT_TABLES[@]}"; do
    if [ "$(table_present "trading.$t")" != t ]; then
        echo "  (no trading.$t)"
        continue
    fi
    echo "  trading.$t.csv.gz"
    remote "psql -Xc \"\\copy (SELECT * FROM trading.$t WHERE portfolio_id IN ($QT_PORTFOLIOS)) TO STDOUT WITH (FORMAT csv, HEADER true)\"" \
        | gzip > "$out/trading.$t.csv.gz"
done

du -sh "$out" | sed 's/^/snapshot: done, /'
echo "next: bash sim/simctl load $out"
