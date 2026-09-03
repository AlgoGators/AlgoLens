"""ChangeBookMembership, driven through the use case rather than the domain
functions it calls.

The domain rules have their own tests. What those cannot see is the wiring:
which registry method gets called, with which spelling, and what the caller is
told afterwards. The first bug this file exists for was an ``unknown_action``
branch that raised a NameError, because the exception it named was never
imported -- every domain test passed, and no test had ever called the use case.
"""

import pytest

from algolens.application.portfolio.ports import MembershipAcknowledgementRequired
from algolens.application.portfolio.use_cases import ChangeBookMembership
from algolens.domain.portfolio.portfolio_assignment import AssignmentValidationError


class _Registry:
    """Just enough registry to see what the use case does with it."""

    def __init__(self, books, lifecycle="live", primary="CONSERVATIVE_PORTFOLIO"):
        self.books = list(books)
        self.row = {
            "id": "trendfollowing",
            "strategy_type": "LIVE_TREND_FOLLOWING",
            "portfolio_id": primary,
            "name": "Trend Following",
            "lifecycle": lifecycle,
        }
        self.calls = []

    def get_any(self, strategy_id):
        return self.row if strategy_id == self.row["id"] else None

    def get(self, strategy_id):
        return self.get_any(strategy_id)

    def books_for_strategy(self, strategy_id):
        return list(self.books)

    def add_membership(self, strategy_id, portfolio_id, audit):
        self.calls.append(("add", portfolio_id, audit))
        return {"strategy_id": strategy_id, "portfolio_id": portfolio_id}

    def remove_membership(self, strategy_id, portfolio_id, audit):
        self.calls.append(("remove", portfolio_id, audit))
        repointed = portfolio_id == self.row["portfolio_id"]
        return {
            "strategy_id": strategy_id,
            "portfolio_id": portfolio_id,
            "primary_portfolio_id": "MACRO_BOOK" if repointed else None,
        }


def test_an_unknown_action_is_a_validation_error_not_a_crash():
    registry = _Registry(["CONSERVATIVE_PORTFOLIO"])
    with pytest.raises(AssignmentValidationError) as excinfo:
        ChangeBookMembership(registry).execute(
            "trendfollowing", "MACRO_BOOK", "rename", user_id="1", reason="x"
        )
    assert excinfo.value.code == "unknown_action"
    assert registry.calls == []


def test_adding_a_new_book_writes_it_and_needs_no_acknowledgement():
    registry = _Registry(["CONSERVATIVE_PORTFOLIO"])
    result = ChangeBookMembership(registry).execute(
        "trendfollowing", "macro_book", "add", user_id="1", reason="diversify"
    )
    assert result["changed"] is True
    assert result["portfolio_id"] == "MACRO_BOOK"
    assert [c[:2] for c in registry.calls] == [("add", "MACRO_BOOK")]


def test_adding_a_book_it_is_already_in_under_another_spelling_changes_nothing():
    registry = _Registry(["CONSERVATIVE_PORTFOLIO", "macro_book"])
    result = ChangeBookMembership(registry).execute(
        "trendfollowing", "MACRO_BOOK", "add", user_id="1", reason="again"
    )
    assert result["changed"] is False
    assert registry.calls == []


def test_removing_uses_the_spelling_the_database_holds():
    registry = _Registry(["CONSERVATIVE_PORTFOLIO", "macro_book"])
    result = ChangeBookMembership(registry).execute(
        "trendfollowing", "MACRO_BOOK", "remove", user_id="1", reason="done",
        acknowledge=True,
    )
    assert result["changed"] is True
    # The row is spelled 'macro_book'; deleting 'MACRO_BOOK' would delete nothing.
    assert [c[:2] for c in registry.calls] == [("remove", "macro_book")]


def test_removing_a_live_strategy_from_a_book_needs_an_acknowledgement_first():
    registry = _Registry(["CONSERVATIVE_PORTFOLIO", "MACRO_BOOK"])
    with pytest.raises(MembershipAcknowledgementRequired):
        ChangeBookMembership(registry).execute(
            "trendfollowing", "MACRO_BOOK", "remove", user_id="1", reason="done"
        )
    assert registry.calls == []


def test_removing_the_primary_book_reports_where_the_primary_moved():
    registry = _Registry(["CONSERVATIVE_PORTFOLIO", "MACRO_BOOK"])
    result = ChangeBookMembership(registry).execute(
        "trendfollowing", "CONSERVATIVE_PORTFOLIO", "remove", user_id="1",
        reason="consolidate", acknowledge=True,
    )
    assert result["changed"] is True
    assert result["primary_portfolio_id"] == "MACRO_BOOK"


def test_removing_a_non_primary_book_reports_no_repoint():
    registry = _Registry(["CONSERVATIVE_PORTFOLIO", "MACRO_BOOK"])
    result = ChangeBookMembership(registry).execute(
        "trendfollowing", "MACRO_BOOK", "remove", user_id="1",
        reason="consolidate", acknowledge=True,
    )
    assert result["primary_portfolio_id"] is None


def test_the_last_book_cannot_be_removed():
    registry = _Registry(["CONSERVATIVE_PORTFOLIO"])
    with pytest.raises(AssignmentValidationError) as excinfo:
        ChangeBookMembership(registry).execute(
            "trendfollowing", "CONSERVATIVE_PORTFOLIO", "remove", user_id="1",
            reason="x", acknowledge=True,
        )
    assert excinfo.value.code == "last_book"
    assert registry.calls == []
