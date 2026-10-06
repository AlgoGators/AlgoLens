"""What a real trade-ngin database contains that the demo seed does not.

The demo seed is clean by construction. It leaves the abandoned
``gross_leverage`` column empty, it never writes a profit-factor sentinel, and
its ``metadata.contract_metadata`` holds point values. A production database has
none of those courtesies: the abandoned column holds whatever it held on the day
the engine stopped writing it, historical rows carry 999.99, and the column
spelled "Contract Size" may well hold contract sizes.

So the three fixes for those cases were, until this file existed, exercised by
nothing. Every unit test passed and the demo looked right, which is precisely
the state the position-snapshot bug shipped in.

These plant the production shapes into a seeded database and read back through
the same SQL the application uses.

Named ..._postgres to keep its basename distinct from the pure-Python
tests/test_production_shapes.py beside it: pytest names modules by basename when
the directory has no __init__.py, and two files called the same thing collide at
collection time rather than at import.
"""

import pathlib
import re

import pytest

from tests.integration.conftest import (
    OWNERSHIP_MARK,
    refuse_to_clobber_a_real_schema,
    require_test_dsn,
)

psycopg2 = pytest.importorskip("psycopg2")

from algolens.domain.portfolio.calculations import (  # noqa: E402
    live_leverage,
    published_profit_factor,
)
from algolens.infrastructure.portfolio.market_data import (  # noqa: E402
    PostgresMarketData,
)

pytestmark = pytest.mark.integration

SEED = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "demo_seed.sql"

SCHEMAS = ("trading", "auth", "futures_data", "metadata")


def _seed_body():
    text = SEED.read_text(encoding="utf-8")
    text = re.sub(r"(?im)^\s*CREATE DATABASE .*?;\s*$", "", text)
    text = re.sub(r"(?im)^\s*\\c .*$", "", text)
    return text


@pytest.fixture()
def seeded():
    conn = psycopg2.connect(require_test_dsn())
    conn.autocommit = True
    with conn.cursor() as cur:
        refuse_to_clobber_a_real_schema(cur)
        for schema in SCHEMAS:
            cur.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        cur.execute(_seed_body())
        cur.execute("COMMENT ON SCHEMA trading IS %s", (OWNERSHIP_MARK,))
    yield conn
    with conn.cursor() as cur:
        for schema in SCHEMAS:
            cur.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
    conn.close()


@pytest.fixture()
def market_data(seeded):
    return PostgresMarketData(connection_factory=lambda: _Borrowed(seeded))


class _Borrowed:
    """The fixture's connection, with close() made a no-op.

    PostgresMarketData closes what its factory hands it, and the fixture still
    needs the connection afterwards to check what the test changed.
    """

    def __init__(self, conn):
        self._conn = conn

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def close(self):
        pass


class TestContractSizeConvention:
    """Whichever way production spells it, the exposure must come out the same."""

    def test_contract_sizes_in_underlying_units_resolve_to_point_values(
        self, seeded, market_data
    ):
        # This is the shape the column name implies, and the shape trade-ngin's
        # old fallback table held: face value and bushels.
        with seeded.cursor() as cur:
            cur.execute(
                'UPDATE metadata.contract_metadata SET "Contract Size" = 100000'
                " WHERE \"Databento Symbol\" IN ('ZN', 'ZB')"
            )
            cur.execute(
                'UPDATE metadata.contract_metadata SET "Contract Size" = 5000'
                " WHERE \"Databento Symbol\" = 'ZS'"
            )

        multipliers = market_data.contract_multipliers(["ZN", "ZB", "ZS", "ES"])
        assert multipliers["ZN"] == 1000.0
        assert multipliers["ZB"] == 1000.0
        assert multipliers["ZS"] == 50.0
        assert multipliers["ES"] == 50.0

    def test_contract_sizes_already_holding_point_values_are_unchanged(
        self, market_data
    ):
        # The demo seed's own convention. Scaling these again would turn ZN into
        # 10, which is the same error pointing the other way.
        multipliers = market_data.contract_multipliers(["ZN", "ZB", "ZS", "ES"])
        assert multipliers["ZN"] == 1000.0
        assert multipliers["ZB"] == 1000.0
        assert multipliers["ZS"] == 50.0
        assert multipliers["ES"] == 50.0

    def test_the_two_conventions_give_identical_exposure(self, seeded, market_data):
        # The property that actually matters: a position is worth the same
        # money either way the column is spelled.
        before = market_data.contract_multipliers(["ZN", "ZS", "CL", "GC", "6E"])
        with seeded.cursor() as cur:
            cur.execute(
                'UPDATE metadata.contract_metadata SET "Contract Size" = 100000'
                " WHERE \"Databento Symbol\" = 'ZN'"
            )
            cur.execute(
                'UPDATE metadata.contract_metadata SET "Contract Size" = 5000'
                " WHERE \"Databento Symbol\" = 'ZS'"
            )
        after = market_data.contract_multipliers(["ZN", "ZS", "CL", "GC", "6E"])
        assert before == after

    def test_an_unrecognised_size_is_still_returned(self, seeded, market_data):
        # A contract nobody has written a spec for still has to be priced. The
        # warning is in the log; blanking the exposure would be worse.
        with seeded.cursor() as cur:
            cur.execute(
                'UPDATE metadata.contract_metadata SET "Contract Size" = 7'
                " WHERE \"Databento Symbol\" = 'ZN'"
            )
        assert market_data.contract_multipliers(["ZN"])["ZN"] == 7.0


class TestAbandonedAndSentinelColumns:
    """Columns that hold something in production and nothing in the demo."""

    def test_a_stale_gross_leverage_does_not_displace_the_live_figure(self, seeded):
        # The engine stopped writing gross_leverage and moved the number to
        # portfolio_leverage. The old column was not dropped, so in production
        # it holds a value frozen on the day of that change. Reading it in
        # preference showed that frozen number as today's leverage -- and the
        # demo, where the column is NULL, could never reveal it.
        with seeded.cursor() as cur:
            cur.execute("UPDATE trading.live_results SET gross_leverage = 99.9")
            cur.execute(
                "SELECT portfolio_leverage, gross_leverage FROM trading.live_results"
                " ORDER BY date DESC LIMIT 1"
            )
            portfolio_leverage, stale = cur.fetchone()

        assert float(stale) == 99.9
        assert portfolio_leverage is not None

        chosen = live_leverage(portfolio_leverage, stale)
        assert chosen != 99.9
        assert chosen == float(portfolio_leverage)

    def test_a_historical_profit_factor_sentinel_reads_as_undefined(self, seeded):
        with seeded.cursor() as cur:
            cur.execute("UPDATE trading.live_results SET profit_factor = 999.99")
            cur.execute(
                "SELECT profit_factor FROM trading.live_results"
                " ORDER BY date DESC LIMIT 1"
            )
            published = cur.fetchone()[0]

        assert float(published) == 999.99
        assert published_profit_factor(published, 1.4) is None

    def test_the_seed_leaves_the_abandoned_column_empty(self, seeded):
        # Stated as a fact about the seed rather than assumed by the tests
        # above, so that seeding it later breaks this instead of them.
        with seeded.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM trading.live_results"
                " WHERE gross_leverage IS NOT NULL"
            )
            assert cur.fetchone()[0] == 0

    def test_the_seed_writes_no_profit_factor_sentinel(self, seeded):
        with seeded.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM trading.live_results"
                " WHERE profit_factor >= 999"
            )
            assert cur.fetchone()[0] == 0
