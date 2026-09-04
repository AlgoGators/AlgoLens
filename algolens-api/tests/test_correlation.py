"""The correlation matrix, which used to be a panel explaining its own absence.

The Strategy Builder said "a real correlation matrix needs per-symbol price
history, which the API does not expose yet". The history was never missing --
``futures_data.ohlcv_1d`` is where every market price on the site comes from.
Nothing read it.
"""

import math

import pytest

from algolens.domain.portfolio.correlation import (
    MIN_OBSERVATIONS,
    build_matrix,
    log_returns,
    pearson,
)


def _series(start, returns):
    """A price path from a starting level and a list of log returns."""
    prices, level = [start], start
    for r in returns:
        level *= math.exp(r)
        prices.append(level)
    return prices


class TestLogReturns:
    def test_a_flat_series_returns_zeros(self):
        assert log_returns([100.0, 100.0, 100.0]) == [0.0, 0.0]

    def test_a_doubling_and_a_halving_are_negatives_of_each_other(self):
        up = log_returns([100.0, 200.0])[0]
        down = log_returns([200.0, 100.0])[0]
        assert up == pytest.approx(-down)

    def test_a_non_positive_price_ends_the_series(self):
        # A zero or negative close makes every return after it undefined.
        # Returning what is usable beats raising on data the app must render.
        assert len(log_returns([100.0, 101.0, 0.0, 105.0])) == 1

    def test_a_single_price_is_no_return_at_all(self):
        assert log_returns([100.0]) == []


class TestPearson:
    def test_a_series_correlates_perfectly_with_itself(self):
        xs = [0.01, -0.02, 0.015, 0.0, -0.005, 0.02, -0.01, 0.004, 0.011, -0.03, 0.02]
        assert pearson(xs, xs) == pytest.approx(1.0)

    def test_a_series_correlates_minus_one_with_its_negation(self):
        xs = [0.01, -0.02, 0.015, 0.0, -0.005, 0.02, -0.01, 0.004, 0.011, -0.03, 0.02]
        assert pearson(xs, [-x for x in xs]) == pytest.approx(-1.0)

    def test_a_self_correlation_never_exceeds_one(self):
        """Floating point can push it a hair past 1.0, which then renders as
        "1.00" beside a cell that says "1.00" and is a different number."""
        xs = [1e-9 * i for i in range(40)]
        value = pearson(xs, xs)
        assert value is not None and -1.0 <= value <= 1.0

    def test_too_few_points_is_unknown_not_zero(self):
        short = [0.01] * (MIN_OBSERVATIONS - 1)
        assert pearson(short, short) is None

    def test_a_series_that_never_moves_has_no_correlation(self):
        # "How does a constant co-move" has no answer. Reporting 0.00 would
        # claim two instruments are independent, which is a strong statement
        # about risk to make from a flat line.
        flat = [0.0] * 30
        moving = [0.001 * i for i in range(30)]
        assert pearson(flat, moving) is None


class TestBuildMatrix:
    def _two_symbols(self):
        days = list(range(40))
        a = _series(100.0, [0.01 if i % 2 else -0.01 for i in range(39)])
        b = _series(50.0, [-0.02 if i % 2 else 0.02 for i in range(39)])
        return {
            "A.v.0": list(zip(days, a)),
            "B.v.0": list(zip(days, b)),
        }

    def test_the_diagonal_is_one_and_the_matrix_is_symmetric(self):
        result = build_matrix(self._two_symbols())
        assert result.symbols == ("A.v.0", "B.v.0")
        for i in range(2):
            assert result.matrix[i][i] == pytest.approx(1.0)
        assert result.matrix[0][1] == pytest.approx(result.matrix[1][0])

    def test_opposing_series_correlate_minus_one(self):
        result = build_matrix(self._two_symbols())
        assert result.matrix[0][1] == pytest.approx(-1.0)

    def test_pairs_are_aligned_on_date_before_differencing(self):
        """A gap in one series must not be closed up silently.

        Differencing each series on its own dates and then zipping would pair
        each return with the wrong one, correlating two series that are
        shifted against each other.
        """
        days = list(range(30))
        a = _series(100.0, [0.01 if i % 3 else -0.02 for i in range(29)])
        full = list(zip(days, a))
        # B is missing three midweek days, as a symbol that did not trade would be.
        gapped = [(d, v) for d, v in full if d not in (10, 11, 12)]

        result = build_matrix({"A.v.0": full, "B.v.0": gapped})
        # Same underlying path, so on the shared dates they are the same series.
        assert result.matrix[0][1] == pytest.approx(1.0)
        # And the count reflects the shared window, not the longer one.
        assert result.observations < len(full) - 1

    def test_observations_reports_the_thinnest_pair(self):
        days = list(range(40))
        long_series = list(zip(days, _series(100.0, [0.01] * 39)))
        short_series = long_series[:15]
        result = build_matrix({"A.v.0": long_series, "B.v.0": short_series})
        assert result.observations == 14

    def test_no_symbols_is_an_empty_matrix_not_an_error(self):
        result = build_matrix({})
        assert result.symbols == ()
        assert result.matrix == ()
        assert result.observations == 0

    def test_an_unmeasurable_pair_is_null_while_the_rest_still_reports(self):
        days = list(range(40))
        moving = list(zip(days, _series(100.0, [0.01 if i % 2 else -0.01 for i in range(39)])))
        flat = list(zip(days, [50.0] * 40))
        result = build_matrix({"A.v.0": moving, "B.v.0": flat})
        assert result.matrix[0][0] == pytest.approx(1.0)
        assert result.matrix[0][1] is None
        assert result.matrix[1][1] is None
