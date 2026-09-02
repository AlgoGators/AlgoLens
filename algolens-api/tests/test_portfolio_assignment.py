import pytest

from algolens.domain.portfolio.portfolio_assignment import (
    AssignmentValidationError,
    build_assignment_audit,
    evaluate_assignment,
    normalize_portfolio_id,
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


class TestNormalizePortfolioId:
    def test_uppercases_and_trims(self):
        assert normalize_portfolio_id("  aggressive_portfolio ") == "AGGRESSIVE_PORTFOLIO"

    def test_rejects_missing(self):
        with pytest.raises(AssignmentValidationError) as exc:
            normalize_portfolio_id(None)
        assert exc.value.code == "missing_portfolio_id"

    def test_rejects_empty_after_trimming(self):
        with pytest.raises(AssignmentValidationError) as exc:
            normalize_portfolio_id("   ")
        assert exc.value.code == "empty_portfolio_id"

    def test_rejects_non_string(self):
        with pytest.raises(AssignmentValidationError) as exc:
            normalize_portfolio_id(7)
        assert exc.value.code == "portfolio_id_not_a_string"

    def test_rejects_punctuation(self):
        # This value lands in audit rows and engine config, not prose.
        with pytest.raises(AssignmentValidationError) as exc:
            normalize_portfolio_id("DROP; TABLE")
        assert exc.value.code == "portfolio_id_invalid_characters"

    def test_allows_underscores_and_hyphens(self):
        assert normalize_portfolio_id("macro-book_2") == "MACRO-BOOK_2"

    def test_rejects_absurd_length(self):
        with pytest.raises(AssignmentValidationError) as exc:
            normalize_portfolio_id("A" * 65)
        assert exc.value.code == "portfolio_id_too_long"


class TestEvaluateAssignment:
    def test_moving_a_live_strategy_requires_acknowledgement(self):
        verdict = evaluate_assignment(registry_row(), "AGGRESSIVE_PORTFOLIO")
        assert verdict["changed"] is True
        assert verdict["requires_acknowledgement"] is True
        codes = {c["code"] for c in verdict["consequences"]}
        assert codes == {"history_discontinuity", "engine_config_drift"}

    def test_moving_an_incubating_strategy_is_free(self):
        # Nothing has traded, so no history can be made discontinuous.
        verdict = evaluate_assignment(
            registry_row(lifecycle="incubating"), "AGGRESSIVE_PORTFOLIO"
        )
        assert verdict["changed"] is True
        assert verdict["requires_acknowledgement"] is False
        assert verdict["consequences"] == []

    def test_a_retired_strategy_cannot_be_moved_at_all(self):
        # Not an acknowledgeable warning: its book is closed and already reported.
        with pytest.raises(AssignmentValidationError) as exc:
            evaluate_assignment(registry_row(lifecycle="retired"), "AGGRESSIVE_PORTFOLIO")
        assert exc.value.code == "strategy_retired"

    def test_assigning_to_the_same_portfolio_is_a_no_op(self):
        verdict = evaluate_assignment(registry_row(), "CONSERVATIVE_PORTFOLIO")
        assert verdict["changed"] is False
        assert verdict["requires_acknowledgement"] is False

    def test_missing_strategy_is_an_input_error(self):
        with pytest.raises(AssignmentValidationError) as exc:
            evaluate_assignment(None, "AGGRESSIVE_PORTFOLIO")
        assert exc.value.code == "strategy_not_found"

    def test_lifecycle_defaults_to_live_when_absent(self):
        # An unknown lifecycle must be treated as the careful case, not the free one.
        row = registry_row()
        del row["lifecycle"]
        assert evaluate_assignment(row, "AGGRESSIVE_PORTFOLIO")["requires_acknowledgement"]

    def test_lifecycle_is_matched_case_insensitively(self):
        verdict = evaluate_assignment(
            registry_row(lifecycle="Incubating"), "AGGRESSIVE_PORTFOLIO"
        )
        assert verdict["requires_acknowledgement"] is False

    def test_the_consequence_message_names_both_portfolios(self):
        verdict = evaluate_assignment(registry_row(), "AGGRESSIVE_PORTFOLIO")
        message = verdict["consequences"][0]["message"]
        assert "CONSERVATIVE_PORTFOLIO" in message
        assert "AGGRESSIVE_PORTFOLIO" in message


class TestBuildAssignmentAudit:
    def test_records_who_what_and_whether_it_was_overridden(self):
        verdict = evaluate_assignment(registry_row(), "AGGRESSIVE_PORTFOLIO")
        audit = build_assignment_audit(
            registry_row(), verdict, user_id="42", reason="Rebalancing books", acknowledged=True
        )
        assert audit["strategy_id"] == "trendfollowing"
        assert audit["user_id"] == "42"
        assert audit["from_portfolio_id"] == "CONSERVATIVE_PORTFOLIO"
        assert audit["to_portfolio_id"] == "AGGRESSIVE_PORTFOLIO"
        assert audit["lifecycle_at_move"] == "live"
        assert audit["reason"] == "Rebalancing books"
        assert audit["acknowledged"] is True
        assert len(audit["consequences"]) == 2

    def test_acknowledged_is_always_a_bool(self):
        verdict = evaluate_assignment(
            registry_row(lifecycle="incubating"), "AGGRESSIVE_PORTFOLIO"
        )
        audit = build_assignment_audit(
            registry_row(lifecycle="incubating"), verdict, "1", "moving", acknowledged=None
        )
        assert audit["acknowledged"] is False
