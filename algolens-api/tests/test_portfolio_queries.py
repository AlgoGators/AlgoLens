"""Regression guard: every query against the `trading` schema must constrain
the portfolio it reads from.

Background: trading.positions, equity_curve, live_results and executions are all
keyed by portfolio_id as well as strategy_id (portfolio_id is part of
positions_pkey). LIVE_TREND_FOLLOWING exists in more than one portfolio, so a
query filtering only on strategy_id silently returns a blend of portfolios --
it does not error, it just reports numbers that belong to no real portfolio.

This scans the backend source rather than executing SQL, so it needs no database
and no Flask app context, and it keeps working if the queries move between
modules (e.g. into a service layer).
"""

import os
import re

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Tables that carry a portfolio_id and therefore must always be constrained.
PORTFOLIO_SCOPED_TABLES = {
    "trading.positions",
    "trading.equity_curve",
    "trading.live_results",
    "trading.executions",
}

# A `cursor.execute(...)` call: capture the SQL string literal that follows.
EXECUTE_RE = re.compile(r"""\.execute\(\s*(?:f?["']{3})(.*?)(?:["']{3})""", re.S)

# Lifecycle closure intentionally discovers every historical book for one
# locked registry identity. This is the sole safe cross-portfolio read: it
# selects only portfolio ids, joins positions through strategy_type, and binds
# that join to the registry's unique id before the next UNION branch. Keeping
# the terminating UNION in the pattern prevents a broadened ``OR`` predicate
# from being silently allowlisted.
HISTORICAL_BOOK_DISCOVERY_RE = re.compile(
    r"""
    \bSELECT\s+positions\.portfolio_id\s+
    FROM\s+trading\.positions\s+AS\s+positions\s+
    JOIN\s+trading\.strategy_registry\s+AS\s+registry\s+
    ON\s+registry\.strategy_type\s*=\s*positions\.strategy_id\s+
    WHERE\s+registry\.id\s*=\s*%s\s+
    UNION\b
    """,
    re.I | re.X,
)


def _is_registry_bounded_historical_book_discovery(table, sql):
    return (
        table == "trading.positions"
        and len(re.findall(r"\b(?:FROM|JOIN)\s+trading\.positions\b", sql, re.I)) == 1
        and HISTORICAL_BOOK_DISCOVERY_RE.search(sql) is not None
    )


def _python_sources():
    for root, dirs, files in os.walk(BACKEND_DIR):
        dirs[:] = [
            d
            for d in dirs
            if d not in {"tests", "__pycache__", ".venv", "venv", "temp"}
        ]
        for fname in files:
            if fname.endswith(".py"):
                yield os.path.join(root, fname)


def _portfolio_scoped_queries():
    """Yield (path, table, sql) for every SQL literal reading a scoped table."""
    for path in _python_sources():
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        for match in EXECUTE_RE.finditer(src):
            sql = match.group(1)
            for table in PORTFOLIO_SCOPED_TABLES:
                if re.search(rf"\b(?:FROM|JOIN)\s+{re.escape(table)}\b", sql, re.I):
                    yield path, table, sql


def test_there_are_queries_to_check():
    """Guard the guard: if the scan finds nothing, the test is silently useless."""
    found = list(_portfolio_scoped_queries())
    assert found, (
        "No queries against portfolio-scoped trading tables were found. Either the "
        "queries moved in a way this scan does not recognise, or the regex needs "
        "updating -- do not treat this as a pass."
    )


def test_every_trading_query_constrains_portfolio_id():
    offenders = []
    for path, table, sql in _portfolio_scoped_queries():
        if (
            not re.search(r"\bportfolio_id\s*=", sql, re.I)
            and not _is_registry_bounded_historical_book_discovery(table, sql)
        ):
            offenders.append(f"{os.path.relpath(path, BACKEND_DIR)} -> {table}")

    assert not offenders, (
        "These queries read a portfolio-scoped table without constraining "
        "portfolio_id, so they will silently blend portfolios together:\n  "
        + "\n  ".join(offenders)
    )
