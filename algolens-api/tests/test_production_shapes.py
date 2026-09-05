"""Behaviours the demo database cannot exercise, because it is too clean.

Every test here covers a case that arises only against a real trade-ngin
database: a column the engine stopped writing but did not drop, a sentinel in a
numeric field, a metadata table that spells contract size the other way. On the
demo seed all three are absent, so the code was correct there and wrong in
production, and nothing in a green test run said so.

That is the same failure the position-snapshot tests were written for: the
suite proved the code matched its own assumptions.
"""

import pytest

from algolens.domain.portfolio.calculations import (
    PROFIT_FACTOR_SENTINEL,
    live_leverage,
    published_or_computed,
    published_profit_factor,
)
from algolens.domain.portfolio.contract_multipliers import (
    ALREADY_POINT_VALUE,
    REPORTED_UNRECOGNISED,
    SCALED_CONTRACT_SIZE,
    UNKNOWN_SYMBOL,
    known_multiplier,
    resolve_multiplier,
)


class TestProfitFactorSentinel:
    """999.99 is not a profit factor of 999.99."""

    def test_the_live_sentinel_is_dropped(self):
        assert published_profit_factor(999.99, 1.4) is None

    def test_the_backtest_sentinel_is_dropped(self):
        # The backtest path spelled the same thing 999.0.
        assert published_profit_factor(999.0, 1.4) is None

    def test_the_local_computation_is_not_used_as_a_fallback_either(self):
        # The sentinel is only written where there is no denominator, so the
        # locally computed figure would be undefined for the same reason.
        # Falling back to it would put a number on screen for a quantity that
        # does not have one.
        assert published_profit_factor(999.99, 2.5) is None

    def test_a_real_ratio_is_published_unchanged(self):
        assert published_profit_factor(1.75, None) == 1.75

    def test_a_large_but_believable_ratio_survives(self):
        # The guard is a sentinel check, not a plausibility filter. A book that
        # made $998 for every $1 it lost has an extraordinary profit factor and
        # is entitled to say so.
        assert published_profit_factor(998.5, None) == 998.5

    def test_an_absent_value_still_falls_back_to_the_computation(self):
        # A row written before the engine published the column at all.
        assert published_profit_factor(None, 1.4) == 1.4

    def test_it_agrees_with_published_or_computed_everywhere_but_the_sentinel(self):
        for published, computed in [(1.2, 3.4), (None, 3.4), (None, None), (0.0, 9.9)]:
            assert published_profit_factor(published, computed) == published_or_computed(
                published, computed
            )

    def test_the_sentinel_threshold_matches_the_engine(self):
        assert PROFIT_FACTOR_SENTINEL == 999.0


class TestContractSizeIsNotAlwaysAMultiplier:
    """The 100x class of error, in the column every exposure is multiplied by."""

    def test_a_treasury_contract_size_is_scaled_to_its_point_value(self):
        # $100,000 of face value quoted as a percentage of par. One point is
        # $1,000. Reading the column directly gave forty contracts an exposure
        # of $449,400,000 against a $264,000 book.
        multiplier, how = resolve_multiplier("ZN.v.0", 100000.0)
        assert multiplier == 1000.0
        assert how == SCALED_CONTRACT_SIZE

    def test_a_grain_contract_size_is_scaled_to_its_point_value(self):
        # 5,000 bushels quoted in cents. One point -- one cent -- is $50.
        multiplier, how = resolve_multiplier("ZC.v.0", 5000.0)
        assert multiplier == 50.0
        assert how == SCALED_CONTRACT_SIZE

    def test_livestock_and_soybean_oil_are_scaled_too(self):
        assert resolve_multiplier("LE", 40000.0)[0] == 400.0
        assert resolve_multiplier("ZL", 60000.0)[0] == 600.0

    def test_a_column_already_holding_point_values_is_not_scaled_again(self):
        # Which convention the column holds is not settled, and this is the
        # branch that stops a correct database from being made wrong: 1,000 for
        # ZN must not become 10.
        multiplier, how = resolve_multiplier("ZN", 1000.0)
        assert multiplier == 1000.0
        assert how == ALREADY_POINT_VALUE

    def test_where_the_two_coincide_either_reading_gives_the_same_answer(self):
        # Crude is dollars per barrel on 1,000 barrels; gold dollars per ounce
        # on 100. For these the question never arises, which is why it went
        # unnoticed for as long as it did.
        assert resolve_multiplier("CL", 1000.0)[0] == 1000.0
        assert resolve_multiplier("GC", 100.0)[0] == 100.0
        assert resolve_multiplier("ES", 50.0)[0] == 50.0

    def test_the_grains_that_are_not_quoted_in_cents_are_left_alone(self):
        # Soybean meal is dollars per short ton, rough rice dollars per
        # hundredweight. A blanket rule would break these.
        assert resolve_multiplier("ZM", 100.0)[0] == 100.0
        assert resolve_multiplier("ZR", 2000.0)[0] == 2000.0

    def test_an_unrecognised_figure_is_used_but_flagged(self):
        multiplier, how = resolve_multiplier("ZN", 7.0)
        assert multiplier == 7.0
        assert how == REPORTED_UNRECOGNISED

    def test_an_unknown_symbol_passes_its_figure_through(self):
        multiplier, how = resolve_multiplier("WHEAT", 5000.0)
        assert multiplier == 5000.0
        assert how == UNKNOWN_SYMBOL

    def test_the_table_agrees_with_the_engines(self):
        # These are the values in trade-ngin's contract_multiplier.cpp. The two
        # tables have to stay in step, or the engine and the dashboard price the
        # same position differently.
        expected = {
            "ES": 50.0, "NQ": 20.0, "RTY": 50.0,
            "ZN": 1000.0, "ZB": 1000.0, "ZT": 2000.0, "UB": 1000.0,
            "ZC": 50.0, "ZS": 50.0, "ZW": 50.0, "KE": 50.0, "ZL": 600.0,
            "ZM": 100.0, "ZR": 2000.0,
            "LE": 400.0, "HE": 400.0, "GF": 500.0,
            "CL": 1000.0, "NG": 10000.0, "GC": 100.0, "SI": 5000.0,
            "6E": 125000.0, "6B": 62500.0,
        }
        for symbol, multiplier in expected.items():
            assert known_multiplier(symbol) == pytest.approx(multiplier), symbol

    def test_notional_of_a_real_position_is_plausible(self):
        multiplier, _ = resolve_multiplier("ZN.v.0", 100000.0)
        assert 40 * 110.5 * multiplier == pytest.approx(4_420_000.0)


class TestAbandonedLeverageColumn:
    """trading.live_results.gross_leverage is dead and was never dropped."""

    def test_the_live_column_wins(self):
        # In production the abandoned column holds a real number frozen on the
        # day the engine stopped writing it. Preferring it put that number on
        # screen as today's leverage.
        assert live_leverage(15.6, 99.9) == 15.6

    def test_the_abandoned_column_is_the_fallback_for_an_old_row(self):
        assert live_leverage(None, 8.2) == 8.2

    def test_neither_is_unknown_rather_than_zero(self):
        assert live_leverage(None, None) is None

    def test_a_zero_live_figure_is_not_treated_as_absent(self):
        # A flat book really can have zero gross leverage, and falling through
        # to the stale column would report the day it stopped being flat.
        assert live_leverage(0.0, 99.9) == 0.0
