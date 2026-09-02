import pytest

from algolens.domain.portfolio.portfolio_assignment import (
    AssignmentValidationError,
    build_membership_audit,
    evaluate_membership_add,
    evaluate_membership_remove,
)


def registry_row(**over):
    row = {
        "id": "trendfollowing",
        "strategy_type": "LIVE_TREND_FOLLOWING",
        "portfolio_id": "CONSERVATIVE_PORTFOLIO",
        "name": "Trend Following",
        "lifecycle": "live",
    }
    row.update(over)
    return row


class TestAdd:
    def test_adding_to_another_book_needs_no_acknowledgement(self):
        # Nothing loses anything: the books it is already in keep it, so their
        # histories stay continuous. This is the whole reason add and remove are
        # gated differently.
        verdict = evaluate_membership_add(
            registry_row(), "AGGRESSIVE_PORTFOLIO", ["CONSERVATIVE_PORTFOLIO"]
        )
        assert verdict["changed"] is True
        assert verdict["requires_acknowledgement"] is False
        assert verdict["consequences"] == []

    def test_adding_to_a_book_it_is_already_in_is_a_no_op(self):
        verdict = evaluate_membership_add(
            registry_row(), "CONSERVATIVE_PORTFOLIO", ["CONSERVATIVE_PORTFOLIO"]
        )
        assert verdict["changed"] is False

    def test_a_retired_strategy_cannot_be_added(self):
        with pytest.raises(AssignmentValidationError) as exc:
            evaluate_membership_add(
                registry_row(lifecycle="retired"), "MACRO_BOOK", ["CONSERVATIVE_PORTFOLIO"]
            )
        assert exc.value.code == "strategy_retired"

    def test_a_missing_strategy_is_an_input_error(self):
        with pytest.raises(AssignmentValidationError) as exc:
            evaluate_membership_add(None, "MACRO_BOOK", [])
        assert exc.value.code == "strategy_not_found"


class TestRemove:
    def test_removing_a_live_strategy_requires_acknowledgement(self):
        verdict = evaluate_membership_remove(
            registry_row(),
            "CONSERVATIVE_PORTFOLIO",
            ["CONSERVATIVE_PORTFOLIO", "AGGRESSIVE_PORTFOLIO"],
        )
        assert verdict["requires_acknowledgement"] is True
        assert verdict["consequences"][0]["code"] == "history_discontinuity"
        assert "CONSERVATIVE_PORTFOLIO" in verdict["consequences"][0]["message"]

    def test_removing_an_incubating_strategy_is_free(self):
        verdict = evaluate_membership_remove(
            registry_row(lifecycle="incubating"),
            "CONSERVATIVE_PORTFOLIO",
            ["CONSERVATIVE_PORTFOLIO", "AGGRESSIVE_PORTFOLIO"],
        )
        assert verdict["changed"] is True
        assert verdict["requires_acknowledgement"] is False

    def test_a_strategy_cannot_be_removed_from_its_only_book(self):
        # Every read in this app is scoped by (strategy, portfolio). Belonging to
        # nothing would make it unreachable rather than merely unassigned, so it
        # is refused outright rather than offered as an acknowledgeable warning.
        with pytest.raises(AssignmentValidationError) as exc:
            evaluate_membership_remove(
                registry_row(), "CONSERVATIVE_PORTFOLIO", ["CONSERVATIVE_PORTFOLIO"]
            )
        assert exc.value.code == "last_book"

    def test_removing_from_a_book_it_is_not_in_is_a_no_op(self):
        verdict = evaluate_membership_remove(
            registry_row(), "MACRO_BOOK", ["CONSERVATIVE_PORTFOLIO", "AGGRESSIVE_PORTFOLIO"]
        )
        assert verdict["changed"] is False

    def test_a_retired_strategy_cannot_be_removed(self):
        with pytest.raises(AssignmentValidationError) as exc:
            evaluate_membership_remove(
                registry_row(lifecycle="retired"),
                "CONSERVATIVE_PORTFOLIO",
                ["CONSERVATIVE_PORTFOLIO", "MACRO_BOOK"],
            )
        assert exc.value.code == "strategy_retired"

    def test_the_last_book_check_runs_before_the_lifecycle_shortcut(self):
        # An incubating strategy still must not be stranded.
        with pytest.raises(AssignmentValidationError) as exc:
            evaluate_membership_remove(
                registry_row(lifecycle="incubating"),
                "CONSERVATIVE_PORTFOLIO",
                ["CONSERVATIVE_PORTFOLIO"],
            )
        assert exc.value.code == "last_book"


class TestMembershipAudit:
    def test_an_add_has_no_origin(self):
        audit = build_membership_audit(
            registry_row(), "MACRO_BOOK", "add", "2", "diversifying", False
        )
        assert audit["to_portfolio_id"] == "MACRO_BOOK"
        assert audit["from_portfolio_id"] is None
        assert audit["acknowledged"] is False

    def test_a_removal_has_no_destination(self):
        audit = build_membership_audit(
            registry_row(), "MACRO_BOOK", "remove", "2", "retiring the sleeve", True
        )
        assert audit["from_portfolio_id"] == "MACRO_BOOK"
        assert audit["to_portfolio_id"] is None
        assert audit["acknowledged"] is True

    def test_it_records_the_lifecycle_at_the_time(self):
        audit = build_membership_audit(
            registry_row(lifecycle="incubating"), "MACRO_BOOK", "add", "2", "trial", False
        )
        assert audit["lifecycle_at_move"] == "incubating"


class TestBookNotEmpty:
    def test_it_carries_the_count_rather_than_only_a_message(self):
        # The adapter builds its own wording from these. Rendering str(exc) into
        # a response is the shape that leaked raw psycopg2 text from the
        # incubation routes; it is not repeated here.
        from algolens.application.portfolio.ports import BookNotEmpty

        exc = BookNotEmpty("CONSERVATIVE_PORTFOLIO", 2)
        assert exc.portfolio_id == "CONSERVATIVE_PORTFOLIO"
        assert exc.occupied == 2


class TestIncubationStatusMapping:
    def test_a_missing_strategy_is_404_and_a_lifecycle_rule_is_400(self):
        from algolens.adapters.http.portfolio import _incubation_error_status
        from algolens.application.portfolio.ports import (
            IncubationError,
            StrategyNotInRegistry,
        )

        assert _incubation_error_status(StrategyNotInRegistry("Strategy x not found")) == 404
        assert _incubation_error_status(IncubationError("already incubating")) == 400

    def test_a_reason_mentioning_not_found_no_longer_changes_the_status(self):
        # The old implementation searched the message for "not found", so a
        # lifecycle refusal quoting a user's reason could turn 400 into 404.
        from algolens.adapters.http.portfolio import _incubation_error_status
        from algolens.application.portfolio.ports import IncubationError

        exc = IncubationError("cannot promote: the backtest was not found in the archive")
        assert _incubation_error_status(exc) == 400
