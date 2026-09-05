"""Prices and contract sizes, read from the systems that own them.

data-ngin owns market data and writes it to ``<asset class>_data.ohlcv_<freq>``;
for futures at daily frequency that is ``futures_data.ohlcv_1d``. Contract
metadata lives in ``metadata.contract_metadata``. Both are read here with the
same queries trade-ngin uses, so the price AlgoLens shows and the price the
engine trades on come from one place:

* latest price -- ``PostgresDatabase::get_latest_prices``:
  ``SELECT DISTINCT ON (symbol) symbol, close ... ORDER BY symbol, time DESC``
* contract size -- ``InstrumentRegistry``, which reads ``"Contract Size"``
  from ``metadata.contract_metadata`` keyed on ``"Databento Symbol"`` and
  falling back to ``"IB Symbol"``.

Both lookups degrade to "unknown" rather than to a number. A database without
market data (a fresh demo, a partial restore) yields an empty mapping, and every
caller is written to show that as unknown rather than as zero. A fabricated
price is indistinguishable from a real one once it is on screen.
"""

import logging

import psycopg2

from algolens.domain.portfolio.contract_multipliers import (
    REPORTED_UNRECOGNISED,
    SCALED_CONTRACT_SIZE,
    UNKNOWN_SYMBOL,
    resolve_multiplier,
)
from algolens.infrastructure.db.postgres import get_db_connection

logger = logging.getLogger(__name__)

#: Futures, daily. AlgoLens shows daily marks; the engine builds this name from
#: asset class and frequency (trade_ngin/core/types.hpp, build_table_name).
PRICE_TABLE = "futures_data.ohlcv_1d"
METADATA_TABLE = "metadata.contract_metadata"


class PostgresMarketData:
    """Latest close prices and contract sizes.

    Every method returns a mapping that may be empty or partial. Missing is a
    normal answer here, not an error: AlgoLens is a reader of these tables and
    must render whatever state the pipeline has left them in.
    """

    def __init__(self, connection_factory=None):
        self.connection_factory = connection_factory or get_db_connection

    def _query(self, sql, params, what):
        conn = self.connection_factory()
        try:
            with conn.cursor() as cursor:
                cursor.execute(sql, params)
                return cursor.fetchall()
        except psycopg2.Error as exc:
            # An absent table is the common case on a database that has not run
            # the data pipeline. Logged once per call, never raised: the detail
            # view must still render, with the price shown as unknown.
            conn.rollback()
            logger.warning("[MARKET_DATA] %s unavailable: %s", what, exc)
            return []
        finally:
            conn.close()

    def latest_prices(self, symbols):
        """{symbol: close} for the most recent bar of each symbol."""
        wanted = [s for s in dict.fromkeys(symbols) if s]
        if not wanted:
            return {}
        rows = self._query(
            f"""
            SELECT DISTINCT ON (symbol) symbol, close
            FROM {PRICE_TABLE}
            WHERE symbol = ANY(%s)
            ORDER BY symbol, time DESC
            """,
            (wanted,),
            PRICE_TABLE,
        )
        prices = {}
        for row in rows:
            symbol = row["symbol"] if isinstance(row, dict) else row[0]
            close = row["close"] if isinstance(row, dict) else row[1]
            if close is not None:
                prices[symbol] = float(close)
        return prices

    def close_series(self, symbols, lookback_days=180):
        """{symbol: [(date, close), ...]} in ascending date order.

        The history behind the correlation matrix. Same table as
        ``latest_prices``, so a correlation and the market price beside it are
        computed from one series rather than two sources that can disagree.

        Bounded by date rather than by row count: a LIMIT would take the newest
        N rows across ALL symbols together, so a symbol with denser history
        would crowd the others out of the window and the pairs would no longer
        share dates.
        """
        wanted = [s for s in dict.fromkeys(symbols) if s]
        if not wanted:
            return {}
        rows = self._query(
            f"""
            SELECT symbol, time::date AS day, close
            FROM {PRICE_TABLE}
            WHERE symbol = ANY(%s)
              AND time >= (CURRENT_DATE - %s * INTERVAL '1 day')
              AND close IS NOT NULL
            ORDER BY symbol, time
            """,
            (wanted, lookback_days),
            PRICE_TABLE,
        )
        series = {}
        for row in rows:
            symbol = row["symbol"] if isinstance(row, dict) else row[0]
            day = row["day"] if isinstance(row, dict) else row[1]
            close = row["close"] if isinstance(row, dict) else row[2]
            series.setdefault(symbol, []).append((day, float(close)))
        return series

    def contract_multipliers(self, base_symbols):
        """{root symbol: PRICE MULTIPLIER}.

        Keyed on the root (``ES``), because that is how the metadata table is
        keyed, while positions and price bars carry the continuous-contract
        suffix (``ES.v.0``).

        The value is the currency worth of one point of the quoted price, which
        is not always what the ``"Contract Size"`` column holds. A ten-year note
        is $100,000 of face value quoted as a percentage of par, so its point
        value is $1,000; corn is 5,000 bushels quoted in cents, so its point
        value is $50. Multiplying by the column directly overstated those by
        100x. See domain/portfolio/contract_multipliers.py, which recognises
        either convention rather than assuming one.
        """
        wanted = [s for s in dict.fromkeys(base_symbols) if s]
        if not wanted:
            return {}
        rows = self._query(
            f"""
            SELECT "Databento Symbol" AS databento, "IB Symbol" AS ib,
                   "Contract Size" AS contract_size
            FROM {METADATA_TABLE}
            WHERE "Databento Symbol" = ANY(%s) OR "IB Symbol" = ANY(%s)
            """,
            (wanted, wanted),
            METADATA_TABLE,
        )
        sizes = {}
        for row in rows:
            if isinstance(row, dict):
                databento, ib, size = row["databento"], row["ib"], row["contract_size"]
            else:
                databento, ib, size = row[0], row[1], row[2]
            if size is None:
                continue
            try:
                value = float(size)
            except (TypeError, ValueError):
                continue
            # The engine treats a non-positive contract size as absent rather
            # than as a multiplier of zero, which would erase the position.
            if value <= 0:
                continue

            multiplier, how = resolve_multiplier(databento or ib, value)
            if how == SCALED_CONTRACT_SIZE and multiplier != value:
                logger.info(
                    "%s: contract size %s scaled by quote convention to point value %s",
                    databento or ib, value, multiplier,
                )
            elif how in (REPORTED_UNRECOGNISED, UNKNOWN_SYMBOL):
                # Priced anyway -- refusing would blank an exposure the reader
                # needs -- but nobody has checked this number against a
                # contract specification, and the log is where that is said.
                logger.warning(
                    "%s: contract size %s taken as a point value unchecked (%s)",
                    databento or ib, value, how,
                )

            for key in (databento, ib):
                if key:
                    sizes.setdefault(key, multiplier)
        return sizes
