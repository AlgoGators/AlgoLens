"""Strategy incubation service: lifecycle transitions and mock capital management.

Strategies can be "incubated" on mock capital for 3-4 months, running the same cron
jobs as live strategies but isolated from the real portfolio. Incubating strategies
do not appear in get_registry() and therefore do not affect headline portfolio metrics.

Every state transition (incubate, promote, retire) is recorded in an audit table
with before_state, after_state, reason, and user_id.
"""

from datetime import datetime, timedelta
import logging

import psycopg2

from database import get_db_connection

logger = logging.getLogger(__name__)

# Incubation window: strategies are observed for 3-4 months
INCUBATION_WINDOW_DAYS = 120


class IncubationError(Exception):
    """Raised when an incubation operation violates state constraints."""

    pass


def get_incubating(cursor):
    """Return list of incubating strategies with days elapsed since start.

    Returns: list of dicts with keys: id, strategy_type, portfolio_id, name,
    mock_capital, incubation_started_at, days_elapsed, window_days
    """
    cursor.execute(
        """
        SELECT id, strategy_type, portfolio_id, name, mock_capital,
               incubation_started_at
        FROM trading.strategy_registry
        WHERE lifecycle = 'incubating'
        ORDER BY incubation_started_at ASC
        """
    )
    rows = cursor.fetchall()

    result = []
    now = (
        datetime.now(rows[0]["incubation_started_at"].tzinfo)
        if rows and rows[0]["incubation_started_at"]
        else datetime.utcnow()
    )

    for row in rows:
        row_dict = {
            "id": row["id"],
            "strategy_type": row["strategy_type"],
            "portfolio_id": row["portfolio_id"],
            "name": row["name"],
            "mock_capital": float(row["mock_capital"]) if row["mock_capital"] else None,
            "incubation_started_at": row["incubation_started_at"],
        }

        if row["incubation_started_at"]:
            # Clamped at zero. `incubation_started_at` is stamped by the DATABASE
            # (`now()`), while this subtracts the APPLICATION host's clock, and the
            # two are never perfectly in step. timedelta.days floors toward negative
            # infinity, so a sub-second skew of the wrong sign turns into -1 -- which
            # is what a strategy incubated moments ago actually reported. A negative
            # elapsed count then renders as negative progress against the window.
            days_elapsed = max(0, (now - row["incubation_started_at"]).days)
            row_dict["days_elapsed"] = days_elapsed
            row_dict["window_days"] = INCUBATION_WINDOW_DAYS
        else:
            row_dict["days_elapsed"] = 0
            row_dict["window_days"] = INCUBATION_WINDOW_DAYS

        result.append(row_dict)

    return result


def start_incubation(conn, strategy_id, mock_capital, reason, user_id):
    """Move a strategy into incubation on mock capital.

    Args:
        conn: Database connection
        strategy_id: Strategy to incubate
        mock_capital: Notional capital to trade against (must be > 0)
        reason: Audit reason (must be non-empty)
        user_id: User making this change

    Raises:
        IncubationError: If strategy already incubating, if mock_capital <= 0,
                        if reason is empty, or if strategy doesn't exist
    """
    if mock_capital <= 0:
        raise IncubationError("mock_capital must be positive")

    if not reason or not reason.strip():
        raise IncubationError("reason must be non-empty")

    try:
        with conn.cursor() as cursor:
            # Check current state
            cursor.execute(
                "SELECT lifecycle FROM trading.strategy_registry WHERE id = %s",
                (strategy_id,),
            )
            row = cursor.fetchone()

            if row is None:
                raise IncubationError(f"Strategy {strategy_id} not found")

            current_state = row["lifecycle"]

            if current_state == "incubating":
                raise IncubationError(f"Strategy {strategy_id} is already incubating")

            # Update registry
            cursor.execute(
                """
                UPDATE trading.strategy_registry
                SET lifecycle = %s, mock_capital = %s,
                    incubation_started_at = now(), updated_at = now()
                WHERE id = %s
                """,
                ("incubating", mock_capital, strategy_id),
            )

            # Record audit
            cursor.execute(
                """
                INSERT INTO trading.strategy_lifecycle_log
                    (strategy_id, before_state, after_state, reason, user_id)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (strategy_id, current_state, "incubating", reason, user_id),
            )

            conn.commit()
    except psycopg2.Error as e:
        conn.rollback()
        raise IncubationError(f"Database error: {e}") from e


def promote_to_live(conn, strategy_id, reason, user_id):
    """Move an incubating strategy back into live trading.

    Args:
        conn: Database connection
        strategy_id: Strategy to promote
        reason: Audit reason (must be non-empty)
        user_id: User making this change

    Raises:
        IncubationError: If strategy not currently incubating, if reason is empty
    """
    if not reason or not reason.strip():
        raise IncubationError("reason must be non-empty")

    try:
        with conn.cursor() as cursor:
            # Check current state
            cursor.execute(
                "SELECT lifecycle FROM trading.strategy_registry WHERE id = %s",
                (strategy_id,),
            )
            row = cursor.fetchone()

            if row is None:
                raise IncubationError(f"Strategy {strategy_id} not found")

            current_state = row["lifecycle"]

            if current_state != "incubating":
                raise IncubationError(
                    f"Strategy {strategy_id} is not currently incubating"
                )

            # Update registry: clear mock_capital when promoting to live
            cursor.execute(
                """
                UPDATE trading.strategy_registry
                SET lifecycle = %s, mock_capital = NULL,
                    incubation_started_at = NULL, updated_at = now()
                WHERE id = %s
                """,
                ("live", strategy_id),
            )

            # Record audit
            cursor.execute(
                """
                INSERT INTO trading.strategy_lifecycle_log
                    (strategy_id, before_state, after_state, reason, user_id)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (strategy_id, "incubating", "live", reason, user_id),
            )

            conn.commit()
    except psycopg2.Error as e:
        conn.rollback()
        raise IncubationError(f"Database error: {e}") from e


def retire(conn, strategy_id, reason, user_id):
    """Retire a strategy (can be live or incubating).

    Args:
        conn: Database connection
        strategy_id: Strategy to retire
        reason: Audit reason (must be non-empty)
        user_id: User making this change

    Raises:
        IncubationError: If strategy doesn't exist or reason is empty
    """
    if not reason or not reason.strip():
        raise IncubationError("reason must be non-empty")

    try:
        with conn.cursor() as cursor:
            # Check current state
            cursor.execute(
                "SELECT lifecycle FROM trading.strategy_registry WHERE id = %s",
                (strategy_id,),
            )
            row = cursor.fetchone()

            if row is None:
                raise IncubationError(f"Strategy {strategy_id} not found")

            current_state = row["lifecycle"]

            # Update registry
            cursor.execute(
                """
                UPDATE trading.strategy_registry
                SET lifecycle = %s, mock_capital = NULL,
                    incubation_started_at = NULL, updated_at = now()
                WHERE id = %s
                """,
                ("retired", strategy_id),
            )

            # Record audit
            cursor.execute(
                """
                INSERT INTO trading.strategy_lifecycle_log
                    (strategy_id, before_state, after_state, reason, user_id)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (strategy_id, current_state, "retired", reason, user_id),
            )

            conn.commit()
    except psycopg2.Error as e:
        conn.rollback()
        raise IncubationError(f"Database error: {e}") from e


def get_incubation_performance(cursor, strategy_id, portfolio_id):
    """Get day-by-day positions and equity for an incubating strategy.

    Returns only data from incubation_started_at onward; pre-incubation history
    is excluded so performance is judged only on observed behavior.

    Args:
        cursor: Database cursor
        strategy_id: Strategy to fetch
        portfolio_id: Portfolio (required for trading table scoping)

    Returns:
        Dict with 'positions' (list of daily position records) and 'equity_curve'
    """
    # First, get incubation start date
    cursor.execute(
        """
        SELECT incubation_started_at
        FROM trading.strategy_registry
        WHERE id = %s AND lifecycle = 'incubating'
        """,
        (strategy_id,),
    )
    row = cursor.fetchone()
    if row is None or row["incubation_started_at"] is None:
        return {"positions": [], "equity_curve": []}

    incubation_start = row["incubation_started_at"]

    # Fetch positions only from incubation_started_at onward
    cursor.execute(
        """
        SELECT date, symbol, quantity, entry_price
        FROM trading.positions
        WHERE strategy_id = %s AND portfolio_id = %s AND date >= %s
        ORDER BY date ASC, symbol ASC
        """,
        (strategy_id, portfolio_id, incubation_start),
    )
    positions = cursor.fetchall()

    # Fetch equity curve only from incubation_started_at onward
    cursor.execute(
        """
        SELECT date, equity
        FROM trading.equity_curve
        WHERE strategy_id = %s AND portfolio_id = %s AND date >= %s
        ORDER BY date ASC
        """,
        (strategy_id, portfolio_id, incubation_start),
    )
    equity = cursor.fetchall()

    return {
        "positions": [
            {
                "date": p["date"],
                "symbol": p["symbol"],
                "quantity": p["quantity"],
                "entry_price": p["entry_price"],
            }
            for p in positions
        ],
        "equity_curve": [
            {"date": e["date"], "equity": float(e["equity"])} for e in equity
        ],
    }
