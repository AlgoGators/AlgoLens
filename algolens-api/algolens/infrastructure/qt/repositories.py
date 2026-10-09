"""Postgres side of the QT desk: books, the command log and settings.

Tables (trade-ngin migrations, new_algo_data):
  trading.positions            portfolio_type system / qt_proposal / qt (021)
  trading.position_overrides   the command log (023); AlgoLens only inserts
  trading.live_run_metadata    published_by / published_at / settings_used (022)
  trading.strategy_config      the desk's settings versions (022)
  metadata.contract_metadata   the instruments the desk may add
  futures_data.ohlcv_1d        latest close of a new symbol (no key: ties
                               broken by the engine's keep order)
"""

from psycopg2.extras import Json

from algolens.application.qt.ports import DeskConflict, DeskNotFound, DeskNotSeeded
from algolens.domain.qt.desk import OVERRIDE_DECISION, PENDING, SAVE, DeskRuleError
from algolens.infrastructure.db.postgres import get_db_connection

# trade-ngin market_data_utils::kFuturesBarKeepOrder: which copy of a
# duplicated (symbol, time) bar the engine keeps.
_FUTURES_BAR_KEEP_ORDER = "volume DESC, close, open, high, low"

# The engine's futures universe drops the full-size ES (it trades the micro);
# live_portfolio.cpp. The desk cannot add what the engine never trades.
_EXCLUDED_FUTURES = ("ES.v.0",)

_CHOICES_SQL = f"""
    SELECT DISTINCT ON (cm."Databento Symbol")
           cm."Databento Symbol" || '.v.0' AS symbol,
           cm."Databento Symbol"           AS root,
           cm."Name"                       AS name,
           cm."Sector"                     AS sector,
           px.close                        AS price,
           px.time                         AS price_date
    FROM metadata.contract_metadata cm
    JOIN LATERAL (
        SELECT o.close, o.time
        FROM futures_data.ohlcv_1d o
        WHERE o.symbol = cm."Databento Symbol" || '.v.0'
        ORDER BY o.time DESC, {_FUTURES_BAR_KEEP_ORDER}
        LIMIT 1
    ) px ON px.close IS NOT NULL
    WHERE lower(cm."Asset Type") = 'futures'
      AND cm."Databento Symbol" || '.v.0' <> ALL(%s)
"""


class PostgresDeskRepository:
    def __init__(self, connection_factory=None):
        self.connection_factory = connection_factory or get_db_connection

    # --- helpers -------------------------------------------------------------

    def _read(self, sql, params=(), one=False):
        conn = self.connection_factory()
        try:
            with conn.cursor() as cursor:
                cursor.execute(sql, params)
                return cursor.fetchone() if one else cursor.fetchall()
        finally:
            conn.close()

    @staticmethod
    def _has_column(cursor, table, column):
        cursor.execute(
            """
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'trading' AND table_name = %s AND column_name = %s
            """,
            (table, column),
        )
        return cursor.fetchone() is not None

    # --- books ---------------------------------------------------------------

    def desk_date(self, portfolio_id):
        """The portfolio's latest model-run date: the newest system or
        qt_proposal row. A day whose system book exists but whose proposal
        does not is a day the desk may not edit yet (ruling 14)."""
        row = self._read(
            """
            SELECT max(date) AS day FROM trading.positions
            WHERE portfolio_id = %s AND portfolio_type IN ('system', 'qt_proposal')
            """,
            (portfolio_id,),
            one=True,
        )
        return row["day"] if row else None

    def book_rows(self, portfolio_id, day, book):
        """One book on one date, netted per symbol. Zero rows are kept: a
        zero-quantity row is the desk's (or the engine's) flatten."""
        return self._read(
            """
            SELECT symbol,
                   SUM(quantity) AS quantity,
                   CASE WHEN SUM(quantity) <> 0
                        THEN SUM(quantity * average_price) / SUM(quantity)
                        ELSE MAX(average_price) END AS average_price,
                   string_agg(DISTINCT moved_by, ',') AS moved_by
            FROM trading.positions
            WHERE portfolio_id = %s AND date = %s AND portfolio_type = %s
            GROUP BY symbol
            ORDER BY symbol
            """,
            (portfolio_id, day, book),
        )

    def symbol_choices(self, asset_class):
        if asset_class != "futures":
            return []  # ruling 13: no equity desk editing in the first release
        return self._read(
            _CHOICES_SQL + ' ORDER BY cm."Databento Symbol", px.time DESC',
            (list(_EXCLUDED_FUTURES),),
        )

    def save_proposal(self, portfolio_id, day, plan, reason, requested_by):
        conn = self.connection_factory()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT symbol, quantity, strategy_id, strategy_name
                    FROM trading.positions
                    WHERE portfolio_id = %s AND date = %s AND portfolio_type = 'qt_proposal'
                    ORDER BY symbol, strategy_id, strategy_name
                    FOR UPDATE
                    """,
                    (portfolio_id, day),
                )
                rows = cursor.fetchall()
                if not rows:
                    raise DeskNotSeeded(
                        f"No QT proposal is seeded for {portfolio_id} on {day.isoformat()}"
                    )
                by_symbol = {}
                for row in rows:
                    by_symbol.setdefault(row["symbol"], []).append(row)
                current = {
                    symbol: sum(r["quantity"] for r in held)
                    for symbol, held in by_symbol.items()
                }
                changes = plan(current)
                sleeves = {(r["strategy_id"], r["strategy_name"]) for r in rows}

                for change in changes:
                    symbol, to = change["symbol"], change["to"]
                    held = by_symbol.get(symbol)
                    if held and len(held) > 1:
                        raise DeskRuleError(
                            f"{symbol} is held in several sleeves; the desk edits a "
                            "symbol held in one sleeve only"
                        )
                    if held:
                        cursor.execute(
                            """
                            UPDATE trading.positions
                            SET quantity = %s, daily_unrealized_pnl = 0,
                                daily_realized_pnl = 0, last_update = now(), updated_at = now()
                            WHERE portfolio_id = %s AND strategy_id = %s AND strategy_name = %s
                              AND date = %s AND symbol = %s AND portfolio_type = 'qt_proposal'
                            """,
                            (to, portfolio_id, held[0]["strategy_id"],
                             held[0]["strategy_name"], day, symbol),
                        )
                        continue
                    if len(sleeves) != 1:
                        raise DeskRuleError(
                            "The proposal holds several sleeves; a new symbol cannot be "
                            "placed in one of them from here"
                        )
                    (strategy_id, strategy_name), = sleeves
                    cursor.execute(
                        _CHOICES_SQL + ' AND cm."Databento Symbol" || \'.v.0\' = %s',
                        (list(_EXCLUDED_FUTURES), symbol),
                    )
                    choice = cursor.fetchone()
                    if choice is None:
                        raise DeskRuleError(
                            f"{symbol} is not a futures contract with market data; "
                            "pick a symbol from the list"
                        )
                    cursor.execute(
                        """
                        INSERT INTO trading.positions
                            (symbol, quantity, average_price, daily_unrealized_pnl,
                             daily_realized_pnl, last_update, updated_at, strategy_id,
                             strategy_name, date, portfolio_id, portfolio_type)
                        VALUES (%s, %s, %s, 0, 0, now(), now(), %s, %s, %s, %s, 'qt_proposal')
                        ON CONFLICT (portfolio_id, strategy_id, strategy_name, date, symbol,
                                     portfolio_type)
                        DO UPDATE SET quantity = EXCLUDED.quantity,
                                      daily_unrealized_pnl = 0, daily_realized_pnl = 0,
                                      last_update = now(), updated_at = now()
                        """,
                        (symbol, to, choice["price"], strategy_id, strategy_name, day,
                         portfolio_id),
                    )

                cursor.execute(
                    """
                    INSERT INTO trading.position_overrides
                        (portfolio_id, date, kind, status, requested_by, reason, payload)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (portfolio_id, day, SAVE, PENDING, requested_by, reason,
                     Json({"changes": changes})),
                )
                command = cursor.fetchone()
            conn.commit()
            return command
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # --- command log ---------------------------------------------------------

    def get_command(self, command_id):
        return self._read(
            "SELECT * FROM trading.position_overrides WHERE id = %s", (command_id,), one=True
        )

    def commands(self, portfolio_id, day):
        return self._read(
            """
            SELECT * FROM trading.position_overrides
            WHERE portfolio_id = %s AND date = %s
            ORDER BY id
            """,
            (portfolio_id, day),
        )

    def insert_command(self, portfolio_id, day, kind, requested_by, reason=None, payload=None):
        conn = self.connection_factory()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO trading.position_overrides
                        (portfolio_id, date, kind, status, requested_by, reason, payload)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (portfolio_id, day, kind, PENDING, requested_by, reason,
                     Json(dict(payload or {}))),
                )
                row = cursor.fetchone()
            conn.commit()
            return row
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def find_request_by_token_hash(self, token_hash):
        return self._read(
            """
            SELECT * FROM trading.position_overrides
            WHERE token_hash = %s AND kind = 'override_request'
            """,
            (token_hash,),
            one=True,
        )

    def insert_decision(self, request_id, approved, approver, approver_role, reason):
        conn = self.connection_factory()
        try:
            with conn.cursor() as cursor:
                # Serialises two approvers clicking at once: the second waits
                # here, then sees the first one's decision.
                cursor.execute(
                    """
                    SELECT * FROM trading.position_overrides
                    WHERE id = %s AND kind = 'override_request'
                    FOR UPDATE
                    """,
                    (request_id,),
                )
                request = cursor.fetchone()
                if request is None:
                    raise DeskNotFound(f"No override request {request_id}")
                cursor.execute(
                    """
                    SELECT id FROM trading.position_overrides
                    WHERE parent_id = %s AND kind = %s
                    LIMIT 1
                    """,
                    (request_id, OVERRIDE_DECISION),
                )
                if cursor.fetchone() is not None:
                    raise DeskConflict("This override request has already been decided")
                cursor.execute(
                    """
                    INSERT INTO trading.position_overrides
                        (portfolio_id, date, kind, status, requested_by, reason, payload,
                         parent_id, approver_role)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (request["portfolio_id"], request["date"], OVERRIDE_DECISION, PENDING,
                     approver, reason, Json({"approved": approved}), request_id,
                     approver_role),
                )
                row = cursor.fetchone()
            conn.commit()
            return row
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def publish_state(self, portfolio_id, day):
        """published_by / published_at from live_run_metadata (022), or None."""
        conn = self.connection_factory()
        try:
            with conn.cursor() as cursor:
                if not self._has_column(cursor, "live_run_metadata", "published_at"):
                    return None
                cursor.execute(
                    """
                    SELECT published_by, published_at
                    FROM trading.live_run_metadata
                    WHERE portfolio_id = %s AND date = %s AND published_at IS NOT NULL
                    ORDER BY published_at DESC
                    LIMIT 1
                    """,
                    (portfolio_id, day),
                )
                return cursor.fetchone()
        finally:
            conn.close()
