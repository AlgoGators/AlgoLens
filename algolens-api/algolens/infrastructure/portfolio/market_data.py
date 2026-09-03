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

    def contract_multipliers(self, base_symbols):
        """{root symbol: contract size}.

        Keyed on the root (``ES``), because that is how the metadata table is
        keyed, while positions and price bars carry the continuous-contract
        suffix (``ES.v.0``).
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
            for key in (databento, ib):
                if key:
                    sizes.setdefault(key, value)
        return sizes
