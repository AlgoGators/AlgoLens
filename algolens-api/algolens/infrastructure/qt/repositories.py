"""Postgres side of the QT desk: books, the command log and settings.

Tables (trade-ngin migrations, new_algo_data):
  trading.positions            portfolio_type system / qt_proposal / qt (021)
  trading.position_overrides   the command log (023, 025). AlgoLens only
                               inserts, always `pending` with the engine's
                               columns NULL (the 025 insert trigger). After 025
                               it holds no UPDATE there, so no SELECT ... FOR
                               UPDATE either: writers serialise on a
                               transaction advisory lock per (portfolio, day).
  trading.live_run_metadata    published_by / published_at / settings_used (022);
                               publish_source / sent_at (026, read when present)
  trading.strategy_config      the desk's settings versions (022)
  metadata.contract_metadata   the instruments the desk may add
  futures_data.ohlcv_1d        latest close of a new symbol (no key: ties
                               broken by the engine's keep order)
"""

import time
from contextlib import contextmanager

import psycopg2.errors
from psycopg2.extras import Json

from algolens.application.qt.ports import DeskConflict, DeskNotFound, DeskNotSeeded
from algolens.domain.qt.desk import (
    DECIDING_STATUSES,
    DONE,
    OPEN_STATUSES,
    OVERRIDE_DECISION,
    OVERRIDE_REQUEST,
    PENDING,
    PUBLISH,
    SAVE,
    DeskRuleError,
    open_override_request,
    override_payload,
    proposal_snapshot,
    request_matches,
    snapshot_sha256,
)
from algolens.infrastructure.db.postgres import get_db_connection

STALE_OVERRIDE = (
    "The proposal changed after the override was requested; request a new override"
)

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


# trade-ngin migration 026 adds live_run_metadata.publish_source and sent_at.
# AlgoLens reads them when they exist and treats them as NULL before. The
# information_schema answer is cached: for good once both are there, and for
# _CUTOFF_COLUMNS_TTL_SECONDS while they are not, so 026 is picked up without
# a restart.
CUTOFF_COLUMNS = ("publish_source", "sent_at")
_CUTOFF_COLUMNS_TTL_SECONDS = 300
_cutoff_columns_cache: frozenset | None = None
_cutoff_columns_expires_at = 0.0


def reset_cutoff_columns_cache():
    """Forget the cached 026 column check (tests rebuild the schema)."""
    global _cutoff_columns_cache, _cutoff_columns_expires_at
    _cutoff_columns_cache = None
    _cutoff_columns_expires_at = 0.0


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

    @contextmanager
    def _transaction(self):
        """A cursor in one transaction, committed on success and rolled back
        on any error. A unique violation (the 025 partial indexes: one open
        publish, one open override request, one decision per request) is a
        409, like the checks this code makes under the lock first."""
        conn = self.connection_factory()
        try:
            with conn.cursor() as cursor:
                yield cursor
            conn.commit()
        except psycopg2.errors.UniqueViolation as exc:
            conn.rollback()
            raise DeskConflict(
                "Another command of this kind is already open for this day; reload to see it"
            ) from exc
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _lock_day(cursor, portfolio_id, day):
        """Serialise AlgoLens' writers of one portfolio's book day (save,
        override request, decision, publish) until the transaction ends. An
        advisory lock needs no table privilege."""
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"algolens.qt_desk|{portfolio_id}|{day.isoformat()}",),
        )

    def _published(self, cursor, portfolio_id, day):
        """C3: a day is published once live_run_metadata.published_at is set
        for it, which also covers the engine's own non-trading-day publish. A
        done publish row counts too, should the two ever disagree.

        No information_schema guard here: if this role cannot read the column
        the write must fail, not proceed as if the day were open."""
        cursor.execute(
            """
            SELECT 1 FROM trading.live_run_metadata
            WHERE portfolio_id = %s AND date = %s AND published_at IS NOT NULL
            LIMIT 1
            """,
            (portfolio_id, day),
        )
        if cursor.fetchone() is not None:
            return True
        cursor.execute(
            """
            SELECT 1 FROM trading.position_overrides
            WHERE portfolio_id = %s AND date = %s AND kind = %s AND status = %s
            LIMIT 1
            """,
            (portfolio_id, day, PUBLISH, DONE),
        )
        return cursor.fetchone() is not None

    @staticmethod
    def _open_publish(cursor, portfolio_id, day):
        cursor.execute(
            """
            SELECT id, status FROM trading.position_overrides
            WHERE portfolio_id = %s AND date = %s AND kind = %s AND status = ANY(%s)
            ORDER BY id
            LIMIT 1
            """,
            (portfolio_id, day, PUBLISH, list(OPEN_STATUSES)),
        )
        return cursor.fetchone()

    def _guard_day(self, cursor, portfolio_id, day, refuse_open_publish=True):
        """Under the day lock: refuse a published day (C3) and, unless told
        otherwise, a day whose publish is pending or running."""
        if self._published(cursor, portfolio_id, day):
            raise DeskConflict(f"The {day.isoformat()} book is already published")
        if refuse_open_publish:
            publish = self._open_publish(cursor, portfolio_id, day)
            if publish is not None:
                raise DeskConflict(
                    f"A publish of the {day.isoformat()} book is already "
                    f"{publish['status']} (#{publish['id']})"
                )

    @staticmethod
    def _snapshot_rows(cursor, portfolio_id, day, lock=True):
        """Every qt_proposal row of the day (zero rows included), locked FOR
        SHARE (C1) so no save changes them before the transaction ends."""
        cursor.execute(
            """
            SELECT strategy_name, symbol, quantity
            FROM trading.positions
            WHERE portfolio_id = %s AND date = %s AND portfolio_type = 'qt_proposal'
            ORDER BY strategy_name, symbol, strategy_id
            """
            + (" FOR SHARE" if lock else ""),
            (portfolio_id, day),
        )
        return cursor.fetchall()

    @staticmethod
    def _day_commands(cursor, portfolio_id, day):
        cursor.execute(
            """
            SELECT * FROM trading.position_overrides
            WHERE portfolio_id = %s AND date = %s
            ORDER BY id
            """,
            (portfolio_id, day),
        )
        return cursor.fetchall()

    @staticmethod
    def _now(cursor):
        cursor.execute("SELECT now() AS now")
        return cursor.fetchone()["now"]

    @staticmethod
    def _insert(cursor, portfolio_id, day, kind, requested_by, reason=None, payload=None,
                parent_id=None, approver_role=None):
        # Always pending with the engine-owned columns NULL: the 025 insert
        # trigger refuses anything else.
        cursor.execute(
            """
            INSERT INTO trading.position_overrides
                (portfolio_id, date, kind, status, requested_by, reason, payload,
                 parent_id, approver_role)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (portfolio_id, day, kind, PENDING, requested_by, reason,
             Json(dict(payload or {})), parent_id, approver_role),
        )
        return cursor.fetchone()

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

    def proposal_rows(self, portfolio_id, day):
        """The day's qt_proposal rows as the override snapshot sees them, unlocked."""
        conn = self.connection_factory()
        try:
            with conn.cursor() as cursor:
                return self._snapshot_rows(cursor, portfolio_id, day, lock=False)
        finally:
            conn.close()

    def symbol_choices(self, asset_class):
        if asset_class != "futures":
            return []  # ruling 13: no equity desk editing in the first release
        return self._read(
            _CHOICES_SQL + ' ORDER BY cm."Databento Symbol", px.time DESC',
            (list(_EXCLUDED_FUTURES),),
        )

    def save_proposal(self, portfolio_id, day, plan, reason, requested_by):
        """One transaction under the day lock: refuse a published day or one
        whose publish is open (C3), lock the proposal, plan the changes from
        the locked quantities (the plan refuses an edit made against
        quantities that changed meanwhile), upsert them, log the save."""
        with self._transaction() as cursor:
            self._lock_day(cursor, portfolio_id, day)
            self._guard_day(cursor, portfolio_id, day)
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
                symbol: sum(r["quantity"] for r in held) for symbol, held in by_symbol.items()
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

            return self._insert(
                cursor, portfolio_id, day, SAVE, requested_by, reason=reason,
                payload={"changes": changes},
            )

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

    def find_request_by_token_hash(self, token_hash):
        return self._read(
            """
            SELECT * FROM trading.position_overrides
            WHERE token_hash = %s AND kind = 'override_request'
            """,
            (token_hash,),
            one=True,
        )

    def insert_publish(self, portfolio_id, day, requested_by):
        """Under the day lock: refuse a published day and an open publish."""
        with self._transaction() as cursor:
            self._lock_day(cursor, portfolio_id, day)
            self._guard_day(cursor, portfolio_id, day)
            return self._insert(cursor, portfolio_id, day, PUBLISH, requested_by)

    def insert_override_request(self, portfolio_id, day, requested_by, reason):
        """Under the day lock: refuse a published day, an open publish and a
        second open request (C2), and snapshot the proposal, locked FOR
        SHARE, into the payload (C1)."""
        with self._transaction() as cursor:
            self._lock_day(cursor, portfolio_id, day)
            self._guard_day(cursor, portfolio_id, day)
            rows = self._snapshot_rows(cursor, portfolio_id, day)
            if not rows:
                raise DeskNotSeeded(
                    f"No QT proposal is seeded for {portfolio_id} on {day.isoformat()}"
                )
            payload = override_payload(rows)
            open_request = open_override_request(
                self._day_commands(cursor, portfolio_id, day),
                self._now(cursor),
                payload["proposal_sha256"],
            )
            if open_request is not None:
                raise DeskConflict(
                    f"Override request #{open_request['id']} for this book is still open "
                    f"({open_request['status']}); wait for its decision or for its link "
                    "to expire"
                )
            return self._insert(
                cursor, portfolio_id, day, OVERRIDE_REQUEST, requested_by,
                reason=reason, payload=payload,
            )

    def insert_decision(self, request_id, approved, approver, approver_role, reason):
        """Under the request's day lock: refuse a request already decided
        (C2), one not e-mailed yet (not done), a published day (C3) and, on
        an approval, a proposal that changed since the request (C1)."""
        with self._transaction() as cursor:
            cursor.execute(
                "SELECT portfolio_id, date FROM trading.position_overrides "
                "WHERE id = %s AND kind = %s",
                (request_id, OVERRIDE_REQUEST),
            )
            found = cursor.fetchone()
            if found is None:
                raise DeskNotFound(f"No override request {request_id}")
            portfolio_id, day = found["portfolio_id"], found["date"]
            # Two approvers clicking at once: the second waits here, then
            # sees the first one's decision.
            self._lock_day(cursor, portfolio_id, day)
            commands = self._day_commands(cursor, portfolio_id, day)
            request = next(c for c in commands if c["id"] == request_id)
            if any(
                c["kind"] == OVERRIDE_DECISION
                and c["parent_id"] == request_id
                and c["status"] in DECIDING_STATUSES
                for c in commands
            ):
                raise DeskConflict("This override request has already been decided")
            if request["status"] != DONE:
                raise DeskConflict(
                    f"This override request is {request['status']}, not e-mailed yet; "
                    "it cannot be decided"
                )
            self._guard_day(cursor, portfolio_id, day, refuse_open_publish=False)
            if approved:
                current = snapshot_sha256(
                    proposal_snapshot(self._snapshot_rows(cursor, portfolio_id, day))
                )
                if not request_matches(request, current):
                    raise DeskConflict(STALE_OVERRIDE)
            return self._insert(
                cursor, portfolio_id, day, OVERRIDE_DECISION, approver,
                reason=reason, payload={"approved": approved}, parent_id=request_id,
                approver_role=approver_role,
            )

    @staticmethod
    def _cached_cutoff_columns():
        if _cutoff_columns_cache is not None and (
            len(_cutoff_columns_cache) == len(CUTOFF_COLUMNS)
            or time.monotonic() < _cutoff_columns_expires_at
        ):
            return _cutoff_columns_cache
        return None

    def _cutoff_columns(self, cursor):
        """Which of 026's columns live_run_metadata has (cached, see above)."""
        global _cutoff_columns_cache, _cutoff_columns_expires_at
        cached = self._cached_cutoff_columns()
        if cached is not None:
            return cached
        now = time.monotonic()
        cursor.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'trading' AND table_name = 'live_run_metadata'
              AND column_name = ANY(%s)
            """,
            (list(CUTOFF_COLUMNS),),
        )
        _cutoff_columns_cache = frozenset(row["column_name"] for row in cursor.fetchall())
        _cutoff_columns_expires_at = now + _CUTOFF_COLUMNS_TTL_SECONDS
        return _cutoff_columns_cache

    def send_tracking(self):
        """Whether live_run_metadata has 026's publish_source and sent_at."""
        cached = self._cached_cutoff_columns()
        if cached is not None:
            return len(cached) == len(CUTOFF_COLUMNS)
        conn = self.connection_factory()
        try:
            with conn.cursor() as cursor:
                return len(self._cutoff_columns(cursor)) == len(CUTOFF_COLUMNS)
        finally:
            conn.close()

    def publish_state(self, portfolio_id, day):
        """published_by / published_at (022) and publish_source / sent_at
        (026; NULL without the columns) of a published day, or None. sent_at
        is the latest over the day's rows of the portfolio."""
        conn = self.connection_factory()
        try:
            with conn.cursor() as cursor:
                if not self._has_column(cursor, "live_run_metadata", "published_at"):
                    return None
                present = self._cutoff_columns(cursor)
                source = "m.publish_source" if "publish_source" in present else "NULL::text"
                sent = (
                    """(SELECT max(s.sent_at) FROM trading.live_run_metadata s
                        WHERE s.portfolio_id = m.portfolio_id AND s.date = m.date)"""
                    if "sent_at" in present
                    else "NULL::timestamptz"
                )
                cursor.execute(
                    f"""
                    SELECT m.published_by, m.published_at,
                           {source} AS publish_source, {sent} AS sent_at
                    FROM trading.live_run_metadata m
                    WHERE m.portfolio_id = %s AND m.date = %s AND m.published_at IS NOT NULL
                    ORDER BY m.published_at DESC
                    LIMIT 1
                    """,
                    (portfolio_id, day),
                )
                return cursor.fetchone()
        finally:
            conn.close()

    # --- settings (022) ------------------------------------------------------

    def latest_settings_used(self, portfolio_id):
        conn = self.connection_factory()
        try:
            with conn.cursor() as cursor:
                if not self._has_column(cursor, "live_run_metadata", "settings_used"):
                    return None
                cursor.execute(
                    """
                    SELECT date, settings_used
                    FROM trading.live_run_metadata
                    WHERE portfolio_id = %s AND settings_used IS NOT NULL
                    ORDER BY date DESC
                    LIMIT 1
                    """,
                    (portfolio_id,),
                )
                return cursor.fetchone()
        finally:
            conn.close()

    def config_versions(self, portfolio_id, limit=50):
        return self._read(
            """
            SELECT id, portfolio_id, version, overrides, reason, created_by, created_at, is_active
            FROM trading.strategy_config
            WHERE portfolio_id = %s
            ORDER BY version DESC
            LIMIT %s
            """,
            (portfolio_id, limit),
        )

    def config_version(self, portfolio_id, version):
        return self._read(
            """
            SELECT id, portfolio_id, version, overrides, reason, created_by, created_at, is_active
            FROM trading.strategy_config
            WHERE portfolio_id = %s AND version = %s
            """,
            (portfolio_id, version),
            one=True,
        )

    def insert_config_version(
        self, portfolio_id, overrides, reason, created_by, expected_active_version
    ):
        conn = self.connection_factory()
        try:
            with conn.cursor() as cursor:
                # Serialise writers of this portfolio's settings. The lock is on
                # the portfolio's rows; the first-ever version has none, and the
                # (portfolio_id, version) key settles that race instead.
                cursor.execute(
                    """
                    SELECT version, is_active FROM trading.strategy_config
                    WHERE portfolio_id = %s
                    FOR UPDATE
                    """,
                    (portfolio_id,),
                )
                rows = cursor.fetchall()
                active = next((r["version"] for r in rows if r["is_active"]), None)
                if active != expected_active_version:
                    raise DeskConflict(
                        "The settings were changed by someone else meanwhile; reload and retry"
                    )
                next_version = max((r["version"] for r in rows), default=0) + 1
                cursor.execute(
                    """
                    UPDATE trading.strategy_config SET is_active = false
                    WHERE portfolio_id = %s AND is_active
                    """,
                    (portfolio_id,),
                )
                cursor.execute(
                    """
                    INSERT INTO trading.strategy_config
                        (portfolio_id, version, overrides, reason, created_by, is_active)
                    VALUES (%s, %s, %s, %s, %s, true)
                    RETURNING id, portfolio_id, version, overrides, reason, created_by,
                              created_at, is_active
                    """,
                    (portfolio_id, next_version, Json(dict(overrides)), reason, created_by),
                )
                row = cursor.fetchone()
            conn.commit()
            return row
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
