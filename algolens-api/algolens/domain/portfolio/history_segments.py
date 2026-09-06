"""Where a strategy's history restarts, and what that does to a chart.

A strategy that moves from one book to another keeps producing one continuous
equity curve, but the money behind it changed: the composition before the move
and the composition after it are different portfolios. Drawing them as one line
invites exactly the reading that is wrong -- that the whole line describes one
thing whose return can be measured end to end.

DECISION (2026-09-06, John): option B. The line breaks at the move. The history
is explicitly segmented, the break is labelled with the two books, and no window
figure is allowed to span it.

What this module does NOT do is rewrite the numbers. The equity values either
side of a break are the engine's and stay exactly as published; the segments
only say where one stops describing the same portfolio as the next.
"""

from datetime import date, datetime

BOOK_CHANGE = "book_change"


def _as_date(value):
    """A date from whatever the row carries, or None if it carries nothing."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            return None
    return None


def book_change_breaks(assignments):
    """The dates a strategy's history restarts, earliest first.

    Only a genuine move breaks anything. An assignment row with no
    ``from_portfolio_id`` is the strategy being placed in its first book, and a
    row whose from and to are the same book is a re-record of where it already
    was: neither changes the composition, so neither breaks the line.
    """
    breaks = {}
    for assignment in assignments or ():
        moved_from = assignment.get("from_portfolio_id")
        moved_to = assignment.get("to_portfolio_id")
        if not moved_from or not moved_to or moved_from == moved_to:
            continue

        when = _as_date(assignment.get("created_at"))
        if when is None:
            continue

        # Two moves on one day collapse to one break -- the reader cares that
        # the line stops describing the same book, not how many hops it took.
        # The last one written names the book the history continues into.
        breaks[when] = {
            "date": when.isoformat(),
            "fromPortfolioId": breaks.get(when, {}).get("fromPortfolioId", moved_from),
            "toPortfolioId": moved_to,
            "reason": BOOK_CHANGE,
        }

    return [breaks[when] for when in sorted(breaks)]


def split_at_breaks(points, breaks):
    """``points`` grouped into segments, one per uninterrupted stretch of book.

    A point dated on or after a break belongs to the segment the break opens:
    the move takes effect that day, so that day's equity is the first of the new
    book's history rather than the last of the old one's.

    Always returns at least one segment, so a caller can render the result
    without special-casing "no breaks" or "no points".
    """
    boundaries = [
        _as_date(entry.get("date")) for entry in (breaks or ()) if entry.get("date")
    ]
    boundaries = sorted(b for b in boundaries if b is not None)

    segments = [[] for _ in range(len(boundaries) + 1)]
    for point in points or ():
        when = _as_date(point.get("date"))
        index = 0
        if when is not None:
            while index < len(boundaries) and when >= boundaries[index]:
                index += 1
        segments[index].append(point)

    return segments


def latest_segment(points, breaks):
    """The most recent unbroken stretch: what a window figure may measure.

    A return quoted over a window that spans a book change is a return on two
    different portfolios added together, which is not a number about anything.
    Empty only when there are no points at all.
    """
    segments = split_at_breaks(points, breaks)
    for segment in reversed(segments):
        if segment:
            return segment
    return []
