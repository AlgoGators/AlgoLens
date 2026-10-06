"""A book change breaks the history. These say exactly where, and how hard."""

from datetime import date, datetime

from algolens.domain.portfolio.history_segments import (
    book_change_breaks,
    latest_segment,
    split_at_breaks,
)


def move(frm, to, when, **extra):
    return {
        "from_portfolio_id": frm,
        "to_portfolio_id": to,
        "created_at": when,
        **extra,
    }


def curve(*dates):
    return [{"date": d, "value": 100.0} for d in dates]


class TestWhatCountsAsABreak:
    def test_a_move_between_two_books_breaks_the_line(self):
        breaks = book_change_breaks([move("BASE", "CONSERVATIVE", date(2026, 3, 2))])

        assert breaks == [
            {
                "date": "2026-03-02",
                "fromPortfolioId": "BASE",
                "toPortfolioId": "CONSERVATIVE",
                "reason": "book_change",
            }
        ]

    def test_being_placed_in_a_first_book_breaks_nothing(self):
        # No from_portfolio_id: the strategy had no book to leave, so there is
        # no earlier composition for the line to stop describing.
        assert book_change_breaks([move(None, "BASE", date(2026, 3, 2))]) == []

    def test_a_move_that_lands_where_it_started_breaks_nothing(self):
        assert book_change_breaks([move("BASE", "BASE", date(2026, 3, 2))]) == []

    def test_a_row_with_no_date_is_ignored_rather_than_guessed_at(self):
        assert book_change_breaks([move("BASE", "CONSERVATIVE", None)]) == []

    def test_no_assignments_at_all(self):
        assert book_change_breaks([]) == []
        assert book_change_breaks(None) == []

    def test_timestamps_are_read_as_their_calendar_day(self):
        breaks = book_change_breaks(
            [move("BASE", "CONSERVATIVE", datetime(2026, 3, 2, 22, 51, 48))]
        )

        assert breaks[0]["date"] == "2026-03-02"

    def test_an_iso_string_is_read_the_same_way(self):
        breaks = book_change_breaks(
            [move("BASE", "CONSERVATIVE", "2026-03-02T22:51:48+00:00")]
        )

        assert breaks[0]["date"] == "2026-03-02"

    def test_breaks_come_back_earliest_first(self):
        breaks = book_change_breaks(
            [
                move("B", "C", date(2026, 5, 1)),
                move("A", "B", date(2026, 1, 1)),
            ]
        )

        assert [b["date"] for b in breaks] == ["2026-01-01", "2026-05-01"]

    def test_two_moves_on_one_day_are_one_break_naming_both_ends(self):
        # A -> B -> C in an afternoon is one discontinuity, and the history
        # continues into C.
        breaks = book_change_breaks(
            [
                move("A", "B", datetime(2026, 3, 2, 9, 0)),
                move("B", "C", datetime(2026, 3, 2, 16, 0)),
            ]
        )

        assert len(breaks) == 1
        assert breaks[0]["fromPortfolioId"] == "A"
        assert breaks[0]["toPortfolioId"] == "C"


class TestSplittingTheCurve:
    def test_an_unbroken_curve_is_one_segment(self):
        points = curve("2026-01-01", "2026-01-02")

        assert split_at_breaks(points, []) == [points]

    def test_the_day_of_the_move_starts_the_new_segment(self):
        # The move takes effect that day, so that day's equity is the first of
        # the new book's history, not the last of the old one's.
        points = curve("2026-02-28", "2026-03-01", "2026-03-02", "2026-03-03")
        breaks = book_change_breaks([move("A", "B", date(2026, 3, 2))])

        before, after = split_at_breaks(points, breaks)

        assert [p["date"] for p in before] == ["2026-02-28", "2026-03-01"]
        assert [p["date"] for p in after] == ["2026-03-02", "2026-03-03"]

    def test_two_breaks_make_three_segments(self):
        points = curve("2026-01-01", "2026-02-01", "2026-03-01")
        breaks = book_change_breaks(
            [move("A", "B", date(2026, 2, 1)), move("B", "C", date(2026, 3, 1))]
        )

        assert [len(s) for s in split_at_breaks(points, breaks)] == [1, 1, 1]

    def test_a_break_before_any_data_leaves_the_first_segment_empty(self):
        # Rather than dropping it. An empty leading segment is the truthful
        # answer: this book has no history on this side of the move.
        points = curve("2026-03-01")
        breaks = book_change_breaks([move("A", "B", date(2026, 1, 1))])

        assert split_at_breaks(points, breaks) == [[], points]

    def test_always_at_least_one_segment(self):
        assert split_at_breaks([], []) == [[]]
        assert split_at_breaks(None, None) == [[]]


class TestTheWindowMayNotSpanABreak:
    def test_the_latest_segment_is_what_a_window_measures(self):
        points = curve("2026-02-28", "2026-03-02", "2026-03-03")
        breaks = book_change_breaks([move("A", "B", date(2026, 3, 2))])

        assert [p["date"] for p in latest_segment(points, breaks)] == [
            "2026-03-02",
            "2026-03-03",
        ]

    def test_it_skips_back_over_a_segment_the_move_left_empty(self):
        # Moved twice in a week: the newest segment can hold nothing yet, and
        # the answer is then the last stretch that does.
        points = curve("2026-01-01", "2026-02-01")
        breaks = book_change_breaks(
            [move("A", "B", date(2026, 2, 1)), move("B", "C", date(2026, 3, 1))]
        )

        assert [p["date"] for p in latest_segment(points, breaks)] == ["2026-02-01"]

    def test_an_unbroken_curve_is_measured_whole(self):
        points = curve("2026-01-01", "2026-01-02")

        assert latest_segment(points, []) == points

    def test_no_points_at_all(self):
        assert latest_segment([], []) == []
