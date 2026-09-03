"""Reading one strategy in one book.

A strategy in several books has a separate set of positions, a separate risk
envelope and possibly a different universe in each. The detail view used to
read `strategy_registry.portfolio_id` unconditionally, so every book except the
primary was unreachable from the app: you could see that the strategy also
traded elsewhere, and you could not look at it.
"""

from datetime import date

import pytest

from algolens.application.portfolio.ports import PortfolioDetailRows
from algolens.application.portfolio.use_cases import (
    GetStrategyDetail,
    StrategyNotFound,
)
from algolens.domain.portfolio.portfolio_assignment import AssignmentValidationError

PRIMARY = "CONSERVATIVE_PORTFOLIO"
OTHER = "MACRO_BOOK"


class _Registry:
    def __init__(self, books):
        self.books = list(books)

    def get(self, strategy_id):
        if strategy_id != "trendfollowing":
            return None
        return {
            "id": "trendfollowing",
            "strategy_type": "LIVE_TREND_FOLLOWING",
            "portfolio_id": PRIMARY,
            "name": "Trend Following",
            "description": "",
            "managers": [],
            "initial_equity": 500000,
            "lifecycle": "live",
        }

    def books_for_strategy(self, strategy_id):
        return list(self.books)


class _Reader:
    """Returns a different position per book, so the two are distinguishable."""

    def __init__(self):
        self.asked = []

    def fetch_detail_rows(self, strategy_type, portfolio_id):
        self.asked.append((strategy_type, portfolio_id))
        symbol = "ES" if portfolio_id == PRIMARY else "6E"
        return PortfolioDetailRows(
            # Every field build_strategy_detail reads. The numbers are not
            # what these tests are about; which book they came from is.
            latest={
                "date": date(2026, 9, 3),
                "current_portfolio_value": 500000,
                "total_annualized_return": 8.0,
                "total_cumulative_return": 8.0,
                "volatility": 12.0,
                "daily_return": 0.1,
                "gross_leverage": 1.0,
                "net_leverage": 1.0,
                "portfolio_leverage": 1.0,
                "margin_posted": 0.0,
                "equity_to_margin_ratio": 0.0,
                "margin_cushion": 0.0,
                "gross_notional": 0.0,
                "total_unrealized_pnl": 0.0,
                "total_realized_pnl": 0.0,
                "total_transaction_costs": 0.0,
                "cash_available": 0.0,
            },
            equity_curve=[],
            equity_by_stream={},
            positions=[
                {
                    "symbol": symbol,
                    "quantity": 1,
                    "average_price": 100.0,
                    "daily_unrealized_pnl": 0,
                    "daily_realized_pnl": 0,
                }
            ],
            executions=[],
            yesterday_positions=[],
        )


def _symbols(detail):
    return [p["symbol"] for p in detail["positions"]]


def test_omitting_the_book_reads_the_primary():
    reader = _Reader()
    detail = GetStrategyDetail(_Registry([PRIMARY, OTHER]), reader).execute("trendfollowing")

    assert detail["portfolio_id"] == PRIMARY
    assert reader.asked == [("LIVE_TREND_FOLLOWING", PRIMARY)]
    assert _symbols(detail) == ["ES"]


def test_naming_a_book_reads_that_book():
    reader = _Reader()
    detail = GetStrategyDetail(_Registry([PRIMARY, OTHER]), reader).execute(
        "trendfollowing", OTHER
    )

    # The whole point: different book, different rows.
    assert detail["portfolio_id"] == OTHER
    assert reader.asked == [("LIVE_TREND_FOLLOWING", OTHER)]
    assert _symbols(detail) == ["6E"]


def test_the_reply_always_lists_every_book_it_is_in():
    detail = GetStrategyDetail(_Registry([PRIMARY, OTHER]), _Reader()).execute(
        "trendfollowing", OTHER
    )
    assert detail["books"] == [PRIMARY, OTHER]


def test_a_book_the_strategy_is_not_in_is_refused():
    reader = _Reader()
    with pytest.raises(AssignmentValidationError) as excinfo:
        GetStrategyDetail(_Registry([PRIMARY]), reader).execute("trendfollowing", "GROWTH")

    assert excinfo.value.code == "not_a_member_of_book"
    # Nothing was read: the refusal happens before any query.
    assert reader.asked == []


def test_the_book_is_matched_without_regard_to_case():
    reader = _Reader()
    detail = GetStrategyDetail(_Registry([PRIMARY, "macro_book"]), reader).execute(
        "trendfollowing", "MACRO_BOOK"
    )
    # Reads the row as it is actually spelled in the database.
    assert reader.asked == [("LIVE_TREND_FOLLOWING", "macro_book")]
    assert detail["portfolio_id"] == "macro_book"


def test_a_registry_without_membership_falls_back_to_the_primary():
    class _Old(_Registry):
        books_for_strategy = None

    registry = _Old([])
    registry.books_for_strategy = None
    detail = GetStrategyDetail(registry, _Reader()).execute("trendfollowing")
    assert detail["books"] == [PRIMARY]
    assert detail["portfolio_id"] == PRIMARY


def test_an_unknown_strategy_is_still_a_404():
    with pytest.raises(StrategyNotFound):
        GetStrategyDetail(_Registry([PRIMARY]), _Reader()).execute("nope", PRIMARY)
