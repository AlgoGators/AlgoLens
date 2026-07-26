"""Writes to the qt position stream, paired with an audit row.

Validation lives here rather than in the route so it can be tested without a
Flask app or a database, and so a second caller (a CLI, a batch import) cannot
reach the write path without passing the same guards.
"""

import json
from datetime import date as _date
from numbers import Real

# Set by the service, never by the caller. See test_portfolio_type_cannot_be_
# overridden_by_the_caller for why this is not merely defensive.
QT_STREAM = "qt"

REQUIRED_FIELDS = ("strategy_id", "symbol", "quantity", "reason")


class PositionValidationError(Exception):
    """Bad input from the caller. Maps to HTTP 400."""


class StrategyNameUnresolved(Exception):
    """Cannot determine the engine's strategy_name from existing rows."""


def validate_position_payload(payload):
    """Normalize and check a proposed position edit.

    Returns a new dict; does not mutate the input.
    """
    if not isinstance(payload, dict):
        raise PositionValidationError("Request body must be a JSON object")

    if "portfolio_type" in payload:
        raise PositionValidationError(
            "portfolio_type may not be supplied by the caller: this endpoint "
            "writes the qt stream only. Other portfolio types are read-only."
        )

    for field in REQUIRED_FIELDS:
        if field not in payload or payload[field] is None:
            raise PositionValidationError(f"Missing required field: {field}")

    symbol = str(payload["symbol"]).strip().upper()
    if not symbol:
        raise PositionValidationError("Field 'symbol' must not be empty")

    strategy_id = str(payload["strategy_id"]).strip()
    if not strategy_id:
        raise PositionValidationError("Field 'strategy_id' must not be empty")

    reason = str(payload["reason"]).strip()
    if not reason:
        raise PositionValidationError(
            "Field 'reason' must not be empty: an override with no stated reason "
            "is indistinguishable from an accident when read back months later"
        )

    quantity = payload["quantity"]
    # bool is a subclass of int in Python; True would otherwise become 1 contract.
    if isinstance(quantity, bool) or not isinstance(quantity, Real):
        raise PositionValidationError("Field 'quantity' must be a number")

    average_price = payload.get("average_price")
    if average_price is not None:
        if isinstance(average_price, bool) or not isinstance(average_price, Real):
            raise PositionValidationError("Field 'average_price' must be a number")
        if average_price < 0:
            raise PositionValidationError("Field 'average_price' must not be negative")

    return {
        "strategy_id": strategy_id,
        "symbol": symbol,
        "quantity": quantity,
        "average_price": average_price,
        "reason": reason,
        "portfolio_type": QT_STREAM,
    }


def build_after_state(before, normalized):
    """The full position row as it will look after the edit.

    Starts from the existing row so fields this endpoint does not manage --
    realized PnL, timestamps written by the engine -- survive an edit rather
    than being silently blanked.
    """
    after = dict(before) if before else {}
    after["symbol"] = normalized["symbol"]
    after["quantity"] = normalized["quantity"]
    if normalized["average_price"] is not None:
        after["average_price"] = normalized["average_price"]
    return after


def fetch_qt_book(cursor, strategy_id, portfolio_id):
    """Today's qt positions, one row per symbol."""
    cursor.execute(
        """
        SELECT DISTINCT ON (symbol)
               symbol, quantity, average_price
        FROM trading.positions
        WHERE strategy_id = %s
          AND portfolio_id = %s
          AND portfolio_type = %s
          AND quantity != 0
        ORDER BY symbol, updated_at DESC
        """,
        (strategy_id, portfolio_id, QT_STREAM),
    )
    return [dict(r) for r in cursor.fetchall()]


def fetch_risk_envelope(cursor, strategy_id, portfolio_id):
    """The most recent envelope trade-ngin published for this book.

    Returns None when the table does not exist yet (trade-ngin has not shipped
    the publisher) or holds no row -- the gate reports that as 'not evaluated'
    rather than as a pass.
    """
    cursor.execute(
        """
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'trading' AND table_name = 'risk_limits'
        """
    )
    if cursor.fetchone() is None:
        return None

    cursor.execute(
        """
        SELECT limits
        FROM trading.risk_limits
        WHERE strategy_id = %s AND portfolio_id = %s
        ORDER BY published_at DESC
        LIMIT 1
        """,
        (strategy_id, portfolio_id),
    )
    row = cursor.fetchone()
    return row["limits"] if row else None


def _fetch_existing_position(cursor, cfg, symbol):
    # Lock the row for the rest of the transaction so we capture the true before_state
    # in the audit trail. If two QT members edit the same symbol concurrently, or the
    # engine's daily run writes between our read and write, the lock ensures we read
    # the current row and record what it was at the moment we decided to change it.
    # When the row does not exist yet there is nothing to lock; the ON CONFLICT
    # clause in write_qt_position still makes the insert safe.
    cursor.execute(
        """
        SELECT symbol, quantity, average_price,
               daily_unrealized_pnl, daily_realized_pnl
        FROM trading.positions
        WHERE strategy_id = %s
          AND portfolio_id = %s
          AND portfolio_type = %s
          AND symbol = %s
        ORDER BY updated_at DESC
        LIMIT 1
        FOR UPDATE
        """,
        (cfg["strategy_type"], cfg["portfolio_id"], QT_STREAM, symbol),
    )
    row = cursor.fetchone()
    return dict(row) if row else None


def _resolve_strategy_name(cursor, cfg):
    """The engine's own strategy_name for this book.

    strategy_name is part of the positions primary key, and the engine chooses
    its value. Guessing it (from the registry's display name, say) would write
    QT's edit to a different key than the engine's row -- the write would appear
    to succeed and the engine would never see it. So take the value from the
    rows the engine already wrote.
    """
    cursor.execute(
        """
        SELECT strategy_name
        FROM trading.positions
        WHERE portfolio_id = %s AND strategy_id = %s
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        (cfg["portfolio_id"], cfg["strategy_type"]),
    )
    row = cursor.fetchone()
    if row is None:
        raise StrategyNameUnresolved(
            f"No existing positions for strategy {cfg['strategy_type']} in "
            f"portfolio {cfg['portfolio_id']}, so the engine's strategy_name "
            f"cannot be determined. Refusing to guess: a wrong strategy_name "
            f"writes a row the engine will never reconcile."
        )
    return row["strategy_name"]


def write_qt_position(conn, cfg, normalized, user_id, verdict, overrode_risk):
    """Upsert one qt position and its audit row, atomically.

    Both statements share a transaction: if the audit insert fails, the position
    change is rolled back with it. A position that changed without an audit row
    is the precise failure F2 exists to prevent, so it must not be reachable
    even through a partial failure.
    """
    with conn:  # commits on success, rolls back on exception
        with conn.cursor() as cursor:
            before = _fetch_existing_position(cursor, cfg, normalized["symbol"])
            after = build_after_state(before, normalized)
            strategy_name = _resolve_strategy_name(cursor, cfg)

            cursor.execute(
                """
                INSERT INTO trading.positions
                    (portfolio_id, strategy_id, strategy_name, date, symbol,
                     portfolio_type, quantity, average_price, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())
                ON CONFLICT (portfolio_id, strategy_id, strategy_name, date,
                             symbol, portfolio_type)
                DO UPDATE SET quantity      = EXCLUDED.quantity,
                              average_price = EXCLUDED.average_price,
                              updated_at    = now()
                RETURNING symbol, quantity, average_price
                """,
                (
                    cfg["portfolio_id"],
                    cfg["strategy_type"],
                    strategy_name,
                    _date.today(),
                    normalized["symbol"],
                    QT_STREAM,
                    normalized["quantity"],
                    normalized["average_price"],
                ),
            )
            position = dict(cursor.fetchone())

            cursor.execute(
                """
                INSERT INTO trading.position_overrides
                    (user_id, source_app, strategy_id, symbol,
                     before_state, after_state, reason,
                     risk_check_result, overrode_risk)
                VALUES (%s, 'algolens', %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    user_id,
                    cfg["strategy_type"],
                    normalized["symbol"],
                    json.dumps(before or {}),
                    json.dumps(after),
                    normalized["reason"],
                    json.dumps(verdict),
                    overrode_risk,
                ),
            )
            override_id = cursor.fetchone()["id"]

    return {"position": position, "override_id": override_id}


def fetch_overrides(cursor, strategy_id, limit=100):
    """Recent audit entries. Read-only -- this table cannot be modified."""
    cursor.execute(
        """
        SELECT id, user_id, source_app, strategy_id, symbol,
               before_state, after_state, reason,
               risk_check_result, overrode_risk, created_at
        FROM trading.position_overrides
        WHERE strategy_id = %s
        ORDER BY created_at DESC
        LIMIT %s
        """,
        (strategy_id, limit),
    )
    return [dict(r) for r in cursor.fetchall()]
