"""Read-only, fail-closed instrument classification for QT quantity validation.

Contract size and price tick are not asset type or quantity increment. Resolve
only explicit metadata, preserving dotted equity and continuous-futures keys.
"""

import re
from collections.abc import Mapping

import psycopg2

from algolens.domain.portfolio.position_edit import PositionValidationError
from algolens.infrastructure.db.postgres import get_db_connection


_ROLL_SYMBOL = re.compile(r"^(.+)\.(?:v|c|n)\.[0-9]+$")
_TYPES = {"FUTURE": "FUTURE", "FUT": "FUTURE", "FUTURES": "FUTURE",
          "EQUITY": "EQUITY", "STK": "EQUITY"}


def _unavailable():
    return PositionValidationError(
        "instrument_type_unavailable", "Instrument type could not be verified"
    )


def _lookup(cursor, symbol):
    cursor.execute(
        '''SELECT "Asset Type" AS asset_type
           FROM metadata.contract_metadata
           WHERE "Databento Symbol" = %s OR "IB Symbol" = %s
           LIMIT 2''',
        (symbol, symbol),
    )
    rows = cursor.fetchall()
    if len(rows) > 1:
        raise PositionValidationError(
            "instrument_type_ambiguous", "Multiple catalog rows match this instrument"
        )
    if not rows:
        return None
    raw = rows[0].get("asset_type") if isinstance(rows[0], Mapping) else rows[0][0]
    if not isinstance(raw, str) or not raw.strip():
        raise _unavailable()
    kind = _TYPES.get(raw.strip().upper())
    if kind is None:
        raise PositionValidationError(
            "instrument_type_unsupported", "Instrument type is not supported for QT edits"
        )
    return kind


class PostgresInstrumentCatalog:
    def __init__(self, connection_factory=None):
        self.connection_factory = connection_factory or get_db_connection

    def resolve_asset_type(self, symbol):
        if not isinstance(symbol, str) or not symbol:
            raise _unavailable()
        conn = None
        try:
            conn = self.connection_factory()
            # Exact and root lookups see one catalog snapshot. This is not a
            # promise to lock external metadata through the later position save.
            conn.set_session(readonly=True, isolation_level="REPEATABLE READ")
            with conn.cursor() as cursor:
                exact = _lookup(cursor, symbol)
                if exact is not None:
                    return exact
                roll = _ROLL_SYMBOL.fullmatch(symbol)
                if roll is not None and _lookup(cursor, roll.group(1)) == "FUTURE":
                    return "FUTURE"
                raise _unavailable()
        except psycopg2.Error:
            # Driver details can include host/SQL; only a stable domain error
            # crosses the adapter boundary. Missing tables/columns deny edits.
            raise _unavailable() from None
        finally:
            if conn is not None:
                conn.close()
