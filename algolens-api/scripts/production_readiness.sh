#!/usr/bin/env bash
#
# Everything the QT platform branch needs answered from the production database,
# in one read-only pass. Writes nothing. Run it, paste the output.
#
#   ./scripts/production_readiness.sh "postgresql://USER@HOST:5432/new_algo_data"
#
# Credentials live in /home/ec2-user/algolens-docker/.env on the EC2 host and are
# gitignored, so this script takes the DSN as an argument rather than hunting for
# them. Nothing here is stored, echoed back, or written to a file.
#
# It answers four questions that no amount of reading the code can settle:
#
#   1. Which equity-index contract does the fund actually hold?
#      trade-ngin's InstrumentRegistry rewrites ES to MES, YM to MYM and NQ to
#      MNQ before every lookup, so it prices a full-size ticker as the micro.
#      AlgoLens does not, and never has. If both rows exist in the metadata
#      table, the engine and the dashboard differ by TEN TIMES on equity-index
#      exposure. See QT_PLATFORM_AUDIT.md 8.3.
#
#   2. Does "Contract Size" hold underlying units or point values?
#      Both applications now recognise either, but knowing which is the
#      difference between reading a log line and guessing.
#
#   3. What shape is trading.strategy_registry really?
#      Nothing in either repository creates it and no engine code writes it.
#      What AlgoLens assumes is a reconstruction, and it is the last table in
#      the schema contract whose shape is a guess.
#
#   4. Is the schema ready for this branch?
#      Ten metric columns on trading.live_results, and two on
#      trading.executions, are created by no migration anywhere.
#
# It also reports the two live data problems raised as issues, so they can be
# confirmed or dismissed from the same output: AlgoLens #83 (both streams
# present in trading.positions) and #84 (the equity strategy mapped to
# BASE_PORTFOLIO).

set -uo pipefail

DSN="${1:-}"
if [ -z "$DSN" ]; then
    echo "usage: $0 <postgres-dsn>" >&2
    echo "  e.g. $0 \"postgresql://user@13.58.153.216:5432/new_algo_data\"" >&2
    exit 2
fi

PSQL="psql --no-psqlrc -v ON_ERROR_STOP=0 -X -d $DSN"

rule() { printf '\n=== %s ===\n' "$1"; }

rule "1. EQUITY-INDEX CONTRACTS  (the ten-times question)"
echo "If MES/MNQ/MYM/M2K rows exist alongside ES/NQ/YM/RTY, the engine is pricing"
echo "the micro and AlgoLens the full-size. If only the full-size rows exist, the"
echo "engine's remap resolves to nothing and its fallback table decides instead."
$PSQL -c "
SELECT \"Databento Symbol\" AS symbol,
       \"IB Symbol\"        AS ib,
       \"Name\"             AS name,
       \"Contract Size\"    AS contract_size
  FROM metadata.contract_metadata
 WHERE \"Databento Symbol\" IN ('ES','MES','NQ','MNQ','YM','MYM','RTY','M2K',
                                '6E','M6E','6B','M6B','GC','MGC','SI','MSF')
 ORDER BY 1;"

rule "1b. WHICH EQUITY-INDEX SYMBOLS ARE ACTUALLY HELD"
echo "The metadata table can list contracts the fund never trades. This is what"
echo "is in the book."
$PSQL -c "
SELECT split_part(symbol,'.',1) AS root,
       count(*) AS rows,
       min(date) AS first_seen,
       max(date) AS last_seen
  FROM trading.positions
 WHERE split_part(symbol,'.',1) IN ('ES','MES','NQ','MNQ','YM','MYM','RTY','M2K')
 GROUP BY 1 ORDER BY 1;"

rule "2. CONTRACT SIZE CONVENTION"
echo "ZN 100000 and ZC 5000 mean the column holds UNDERLYING UNITS."
echo "ZN 1000   and ZC 50   mean it holds POINT VALUES."
echo "Both applications handle either; this says which they will see."
$PSQL -c "
SELECT \"Databento Symbol\" AS symbol, \"Contract Size\" AS contract_size
  FROM metadata.contract_metadata
 WHERE \"Databento Symbol\" IN ('ZN','ZB','ZC','ZS','ZL','LE','ES','CL','GC')
 ORDER BY 1;"

rule "3. trading.strategy_registry -- THE LAST UNVERIFIED SHAPE"
$PSQL -c "
SELECT column_name, data_type, is_nullable, column_default
  FROM information_schema.columns
 WHERE table_schema='trading' AND table_name='strategy_registry'
 ORDER BY ordinal_position;"
echo "-- and its rows, which issue #84 says map the equity strategy to the wrong book:"
$PSQL -c "
SELECT id, strategy_type, portfolio_id, lifecycle, is_active
  FROM trading.strategy_registry ORDER BY id;"

rule "4. SCHEMA READINESS FOR THIS BRANCH"
echo "Every column below must read 'present'. Any 'MISSING' is a 500 on the"
echo "dashboard, and trade-ngin migration 011 is what adds them."
$PSQL -c "
WITH needed(tbl, col) AS (VALUES
    ('live_results','sharpe_ratio'), ('live_results','sortino_ratio'),
    ('live_results','downside_deviation'), ('live_results','max_drawdown'),
    ('live_results','win_rate'), ('live_results','avg_win'),
    ('live_results','avg_loss'), ('live_results','profit_factor'),
    ('live_results','best_day'), ('live_results','worst_day'),
    ('live_results','gross_profit'), ('live_results','gross_loss'),
    ('live_results','portfolio_leverage'), ('live_results','strategy_id'),
    ('executions','execution_time'), ('executions','commissions_fees'),
    ('positions','portfolio_type'), ('equity_curve','portfolio_type'))
SELECT n.tbl, n.col,
       CASE WHEN c.column_name IS NULL THEN 'MISSING' ELSE 'present' END AS status
  FROM needed n
  LEFT JOIN information_schema.columns c
         ON c.table_schema='trading' AND c.table_name=n.tbl AND c.column_name=n.col
 ORDER BY 3 DESC, 1, 2;"

rule "4b. THE PROFIT-FACTOR SENTINEL, IF ANY IS LEFT"
echo "Rows migration 010 will clear. A count of 0 means there is nothing to do."
$PSQL -c "
SELECT count(*) AS sentinel_rows
  FROM trading.live_results
 WHERE profit_factor >= 999.0 AND coalesce(gross_loss,0) = 0;" 2>/dev/null \
 || echo "(profit_factor column absent -- apply 011 first)"

rule "5. ISSUE #83 -- ARE BOTH STREAMS PRESENT YET"
echo "One stream means migration 002 has not been applied and the blending has"
echo "not started. Two means it has, and the stream predicate is required."
$PSQL -c "
SELECT portfolio_type, count(*) AS rows, max(date) AS latest
  FROM trading.positions GROUP BY 1 ORDER BY 1;" 2>/dev/null \
 || echo "(portfolio_type absent -- migration 001 not applied)"

rule "6. THE DEAD gross_leverage COLUMN"
echo "AlgoLens reads portfolio_leverage first now. This shows what the abandoned"
echo "column still holds, which is whatever it held the day the engine stopped."
$PSQL -c "
SELECT count(*) FILTER (WHERE gross_leverage IS NOT NULL) AS stale_rows,
       max(date) FILTER (WHERE gross_leverage IS NOT NULL) AS last_written
  FROM trading.live_results;" 2>/dev/null || echo "(column absent)"

printf '\n=== DONE. Nothing above wrote to the database. ===\n'
