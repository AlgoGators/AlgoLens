"""Where each number on the dashboard comes from.

Every test here pins a figure to its source. They exist because an audit found
three ways a number can be wrong without being missing: computed locally when
the engine already published it, labelled as something it is not, and read from
a table without the date predicate that makes the read meaningful.
"""

import pytest

from algolens.domain.portfolio.calculations import (
    compute_return_stats,
    net_pnl,
    published_or_computed,
    transform_finalized,
)


class TestNetPnL:
    """Net P&L sits beside unrealised, realised and commissions, and a reader
    adds those three to check it."""

    def test_it_is_the_sum_of_the_three_figures_beside_it(self):
        assert net_pnl(6330.00, 950.00, 20.60) == pytest.approx(7259.40)

    def test_a_missing_part_makes_the_whole_unknown(self):
        # Summing what is known and calling it "net" reports a partial figure
        # as a complete one.
        assert net_pnl(None, 950.00, 20.60) is None
        assert net_pnl(6330.00, None, 20.60) is None
        assert net_pnl(6330.00, 950.00, None) is None

    def test_it_is_not_the_return_since_inception(self):
        """The regression this replaces.

        The card held current value minus starting equity. On the demo book
        that is $92,405.72 sitting next to three figures that sum to $7,259.40,
        under a heading that invites the reader to add them.
        """
        assert net_pnl(6330.00, 950.00, 20.60) != pytest.approx(92405.72)


class TestPublishedOrComputed:
    def test_the_engine_wins_when_it_published_a_figure(self):
        assert published_or_computed(4.6707, 3.9) == pytest.approx(4.6707)

    def test_the_local_computation_is_only_a_fallback(self):
        assert published_or_computed(None, 3.9) == pytest.approx(3.9)

    def test_both_unknown_stays_unknown(self):
        assert published_or_computed(None, None) is None

    def test_a_published_zero_is_a_measurement_not_a_missing_value(self):
        # `or` instead of an explicit None check would silently prefer the
        # local number here.
        assert published_or_computed(0.0, 3.9) == 0.0


class TestClosedLots:
    """A lot that is gone today exited at a price nothing in the engine's data
    records. The engine writes no row for a closed position -- not even a
    zero-quantity one -- so there is nothing to read the exit from."""

    def test_a_closed_lot_reports_an_unknown_exit_price(self):
        yesterday = [
            {
                "symbol": "ZB.v.0",
                "quantity": 8,
                "average_price": 119.50,
                "daily_realized_pnl": 640.00,
            }
        ]
        rows = transform_finalized(yesterday, [])

        assert len(rows) == 1
        assert rows[0]["symbol"] == "ZB"
        assert rows[0]["entryPrice"] == pytest.approx(119.50)
        # Not 119.50. Carrying the entry price forward as the exit was a guess
        # dressed as a fill, and it made every closed lot look flat.
        assert rows[0]["exitPrice"] is None
        assert rows[0]["realizedPnL"] == pytest.approx(640.00)

    def test_a_resized_lot_reports_both_prices(self):
        yesterday = [
            {
                "symbol": "RTY.v.0",
                "quantity": 6,
                "average_price": 2279.40,
                "daily_realized_pnl": 440.00,
            }
        ]
        today = [{"symbol": "RTY.v.0", "quantity": 9, "average_price": 2285.60}]
        rows = transform_finalized(yesterday, today)

        assert len(rows) == 1
        assert rows[0]["entryPrice"] == pytest.approx(2279.40)
        assert rows[0]["exitPrice"] == pytest.approx(2285.60)

    def test_an_unchanged_lot_is_not_a_closed_one(self):
        same = [{"symbol": "ES.v.0", "quantity": 12, "average_price": 5280.25}]
        assert transform_finalized(same, list(same)) == []


class TestReturnStatsStayUndefinedRatherThanZero:
    def test_a_curve_with_no_losing_day_has_no_profit_factor(self):
        curve = [{"value": v} for v in (100.0, 101.0, 102.0, 103.0)]
        stats = compute_return_stats(curve)
        # The engine's own convention here is 999.99, which is a sentinel and
        # not a measurement. Undefined is reported as undefined.
        assert stats["profit_factor"] is None
        assert stats["avg_loss"] is None
        assert stats["win_rate"] == pytest.approx(100.0)

    def test_an_empty_curve_measures_nothing(self):
        stats = compute_return_stats([])
        assert stats["best_day"] is None
        assert stats["worst_day"] is None
        assert stats["win_rate"] is None
