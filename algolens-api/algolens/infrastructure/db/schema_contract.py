"""What AlgoLens needs the trading schema to look like, declared in one place.

WHY THIS EXISTS
---------------
No migration in either repository creates ``trading.positions``,
``trading.equity_curve``, ``trading.live_results``, ``trading.executions`` or
``trading.strategy_registry``. Migration 001 only ALTERs the first two, so the
shape they start from is written down nowhere that either application can read.

The cost of that was not theoretical. ``demo_seed.sql`` and the integration
fixture had each invented their own looser version of ``trading.positions``,
and the manual position write path was developed and tested against the
invention: it omitted three columns that the real table declares NOT NULL with
no default, so the first edit made against a real database would have been a
500. Every test passed the whole time.

This module is the declaration those tests were missing. It states, per table,
the columns AlgoLens reads and the columns AlgoLens writes, so that a database
can be checked against it instead of assumed. ``check_schema`` does the
comparing and is the thing worth running against a real database.

WHERE THE EXPECTATIONS COME FROM
--------------------------------
Not from this repository's guesses. Each table cites its source:

* ``positions`` / ``equity_curve`` -- trade-ngin's own migration test,
  ``migrations/test_001_migration.sh``, plus what migrations 001 and 003 do.
* ``live_results`` / ``executions`` -- the INSERT statements the engine itself
  issues, in ``trade-ngin/src/data/postgres_database.cpp``. The engine is the
  writer, so its column list is authoritative.
* ``position_overrides`` / ``risk_limits`` / books tables -- migrations 004,
  005 and 009, which do create them.
* ``strategy_registry`` -- **still unverified**. Nothing in either repository
  creates it and no engine code writes it. What is declared here is only what
  AlgoLens requires of it. A schema dump from a real database is the only thing
  that can confirm it, and until then this table is the known soft spot.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TableContract:
    """One table, and what this application needs to be true of it."""

    name: str
    #: Why we believe this shape. Printed in the report so a mismatch can be
    #: argued with, rather than merely obeyed.
    source: str
    #: Columns AlgoLens SELECTs. A missing one breaks a read.
    reads: tuple[str, ...] = ()
    #: Columns AlgoLens supplies on INSERT. Anything the database declares NOT
    #: NULL without a default and which is NOT in this set is a write that
    #: cannot succeed -- exactly the failure described above.
    writes: tuple[str, ...] = ()
    #: True when AlgoLens ever INSERTs rows here. Only then can an unsupplied
    #: NOT NULL column break a write. A table AlgoLens merely UPDATEs (it never
    #: creates strategy_registry rows, for instance) is not at risk from a
    #: column the engine always fills in itself.
    inserts_rows: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)


POSITIONS = TableContract(
    name="trading.positions",
    source="trade-ngin migrations/test_001_migration.sh + migrations 001, 003",
    reads=(
        "symbol", "quantity", "average_price", "daily_unrealized_pnl",
        "daily_realized_pnl", "updated_at", "strategy_id", "strategy_name",
        "date", "portfolio_id", "portfolio_type",
    ),
    writes=(
        "portfolio_id", "strategy_id", "strategy_name", "date", "symbol",
        "portfolio_type", "quantity", "average_price",
        "daily_unrealized_pnl", "daily_realized_pnl", "last_update", "updated_at",
    ),
    inserts_rows=True,
    notes=(
        "daily_unrealized_pnl, daily_realized_pnl and last_update are NOT NULL "
        "with no default in the shipped schema. Omitting them was a 500 on "
        "every manual edit.",
        "ON CONFLICT deliberately does not overwrite the PnL columns or "
        "last_update: they are the engine's numbers.",
    ),
)

EQUITY_CURVE = TableContract(
    name="trading.equity_curve",
    source="trade-ngin migrations/test_001_migration.sh + migrations 001, 003",
    reads=("strategy_id", "portfolio_id", "portfolio_type", "timestamp", "equity"),
)

LIVE_RESULTS = TableContract(
    name="trading.live_results",
    source=(
        "the engine's own writers. The live path is "
        "trade-ngin/src/data/postgres_database_extensions.cpp "
        "(PostgresDatabase::store_live_results_complete), which builds its "
        "column list from the metric maps assembled in "
        "trade-ngin/apps/strategies/live_portfolio_runner.cpp:2930; the legacy "
        "fixed INSERT is PostgresDatabase::store_live_results in "
        "postgres_database.cpp:2096. The engine reads them back in "
        "trade-ngin/src/live/live_data_loader.cpp:167."
    ),
    reads=(
        "date", "portfolio_id", "config", "current_portfolio_value",
        "total_annualized_return", "total_cumulative_return", "volatility",
        "daily_return", "net_leverage", "portfolio_leverage", "margin_posted",
        "equity_to_margin_ratio", "margin_cushion", "gross_notional",
        "total_unrealized_pnl", "total_realized_pnl", "total_transaction_costs",
        "cash_available",
        # Published by the engine and read here since the audit; AlgoLens used
        # to recompute all of these from the equity curve instead.
        "sharpe_ratio", "sortino_ratio", "downside_deviation", "max_drawdown",
        "win_rate", "avg_win", "avg_loss", "profit_factor",
        "best_day", "worst_day",
    ),
    notes=(
        "The engine keys rows on (portfolio_id, strategy_id, date). AlgoLens "
        "matches on config->>'strategy_type' instead, which works only while "
        "the engine keeps writing that key into config.",
        "gross_leverage still exists but the engine stopped writing it; its "
        "value now goes to portfolio_leverage. Reading gross_leverage directly "
        "returns a dead column.",
        "avg_win and avg_loss are mean daily PERCENTAGE returns on winning and "
        "losing days, not dollar amounts. AlgoLens computed a mean dollar "
        "change under the same names and rendered it with a currency symbol.",
        "The engine reports a profit factor of 999.99 for a book with gains "
        "and no losses (live_historical_metrics.cpp). That is a sentinel, not "
        "a measurement; treat it as undefined.",
        "total_return and margin_leverage are written only by the legacy fixed "
        "INSERT, never by the live path. Do not read them.",
    ),
)


EXECUTIONS = TableContract(
    name="trading.executions",
    source="the engine's own INSERT, trade-ngin/src/data/postgres_database.cpp",
    reads=(
        "symbol", "side", "quantity", "price", "execution_time",
        "commissions_fees", "strategy_id", "portfolio_id",
    ),
)

STRATEGY_REGISTRY = TableContract(
    name="trading.strategy_registry",
    source="UNVERIFIED -- nothing in either repository creates or writes this "
           "table. These are AlgoLens's requirements, not a confirmed shape.",
    reads=(
        "id", "strategy_type", "portfolio_id", "name", "description",
        "initial_equity", "managers", "is_active", "lifecycle", "sort_order",
        "mock_capital", "incubation_started_at", "updated_at",
    ),
    writes=("portfolio_id", "lifecycle", "mock_capital", "incubation_started_at", "updated_at"),
    notes=(
        "AlgoLens only ever UPDATEs this table -- rows are created elsewhere -- "
        "so `writes` here lists the columns it sets, not an INSERT column list.",
        "The one table here whose shape is still a reconstruction. A schema "
        "dump from a real database is what would settle it.",
    ),
)

POSITION_OVERRIDES = TableContract(
    name="trading.position_overrides",
    source="trade-ngin migration 004",
    reads=(
        "id", "user_id", "source_app", "strategy_id", "symbol", "before_state",
        "after_state", "reason", "risk_check_result", "overrode_risk", "created_at",
    ),
    writes=(
        "user_id", "source_app", "strategy_id", "symbol", "before_state",
        "after_state", "reason", "risk_check_result", "overrode_risk",
    ),
    inserts_rows=True,
)

RISK_LIMITS = TableContract(
    name="trading.risk_limits",
    source="trade-ngin migration 005",
    reads=("strategy_id", "portfolio_id", "limits"),
)

PORTFOLIOS = TableContract(
    name="trading.portfolios",
    source="trade-ngin migration 009",
    reads=("portfolio_id", "name", "description", "created_by", "created_at"),
    writes=("portfolio_id", "name", "description", "created_by"),
    inserts_rows=True,
)

MEMBERSHIPS = TableContract(
    name="trading.strategy_book_memberships",
    source="trade-ngin migration 009",
    reads=("strategy_id", "portfolio_id", "added_by", "added_at"),
    writes=("strategy_id", "portfolio_id", "added_by"),
    inserts_rows=True,
)

ASSIGNMENTS = TableContract(
    name="trading.portfolio_assignments",
    source="trade-ngin migration 009",
    reads=(
        "id", "strategy_id", "user_id", "from_portfolio_id", "to_portfolio_id",
        "lifecycle_at_move", "reason", "consequences", "acknowledged", "created_at",
    ),
    writes=(
        "strategy_id", "user_id", "from_portfolio_id", "to_portfolio_id",
        "lifecycle_at_move", "reason", "consequences", "acknowledged",
    ),
    inserts_rows=True,
)

CONTRACTS = (
    POSITIONS, EQUITY_CURVE, LIVE_RESULTS, EXECUTIONS, STRATEGY_REGISTRY,
    POSITION_OVERRIDES, RISK_LIMITS, PORTFOLIOS, MEMBERSHIPS, ASSIGNMENTS,
)


def _columns(cursor, schema, table):
    cursor.execute(
        """
        SELECT column_name, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        """,
        (schema, table),
    )
    out = {}
    for row in cursor.fetchall():
        # Works with a plain cursor or a RealDictCursor.
        if isinstance(row, dict):
            out[row["column_name"]] = (row["is_nullable"], row["column_default"])
        else:
            out[row[0]] = (row[1], row[2])
    return out


def check_schema(cursor, contracts=CONTRACTS):
    """Compare a live database against the contract.

    Returns a list of findings, each a dict with ``table``, ``kind``,
    ``column`` and ``detail``. An empty list means the database can serve every
    read this application makes and accept every write it issues.

    The two kinds that matter:

    ``missing_column``
        AlgoLens SELECTs a column the database does not have. The read fails.

    ``unsupplied_not_null``
        The database requires a value for a column on INSERT, with no default,
        and AlgoLens's INSERT does not name it. The write fails. This is the
        one that shipped undetected. Only reported for tables AlgoLens actually
        inserts rows into.
    """
    findings = []
    for contract in contracts:
        schema, _, table = contract.name.partition(".")
        actual = _columns(cursor, schema, table)
        if not actual:
            findings.append({
                "table": contract.name,
                "kind": "missing_table",
                "column": None,
                "detail": f"no such table; expected per {contract.source}",
            })
            continue

        for column in contract.reads:
            if column not in actual:
                findings.append({
                    "table": contract.name,
                    "kind": "missing_column",
                    "column": column,
                    "detail": "AlgoLens reads this column and the database has no such column",
                })

        if not contract.inserts_rows:
            continue

        for column, (nullable, default) in sorted(actual.items()):
            if nullable == "NO" and default is None and column not in contract.writes:
                findings.append({
                    "table": contract.name,
                    "kind": "unsupplied_not_null",
                    "column": column,
                    "detail": (
                        "the database requires a value here on INSERT and AlgoLens "
                        "does not supply one; every write to this table will fail"
                    ),
                })
    return findings


def format_findings(findings):
    """A report a person can act on, or a single line saying there is nothing."""
    if not findings:
        return "Schema contract satisfied: every declared read and write is supported."
    lines = [f"{len(findings)} schema mismatch(es):"]
    for f in findings:
        where = f["table"] + (f".{f['column']}" if f["column"] else "")
        lines.append(f"  [{f['kind']}] {where}\n      {f['detail']}")
    return "\n".join(lines)
