"""The QT desk's daily approval cutoff, in America/New_York (2026-10-09).

Every calendar day D (weekends and holidays included):

  * until 09:30  the desk edits, may request an override, and approves D;
  * 09:30        the engine e-mails every approved, unsent book;
  * 09:30-10:00  an approval is e-mailed at once;
  * 10:00        an unapproved day gets the model's book, published by the
                 engine (publish_source 'fallback') and e-mailed; D is frozen.

Approval is the desk's publish command (position_overrides kind 'publish').
From 10:00 New York on D, AlgoLens refuses to approve, save or override D:
the engine's fallback would discard any of it.

Pure rules: no database, no HTTP. Times are timezone-aware.
"""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

NEW_YORK_NAME = "America/New_York"
NEW_YORK = ZoneInfo(NEW_YORK_NAME)

APPROVE_BY = time(9, 30)
FALLBACK_AT = time(10, 0)

# trading.live_run_metadata.publish_source (trade-ngin migration 026).
SOURCE_DESK = "desk"
SOURCE_FALLBACK = "fallback"
SOURCE_MODEL_ONLY = "model-only"
PUBLISH_SOURCES = (SOURCE_DESK, SOURCE_FALLBACK, SOURCE_MODEL_ONLY)
# Derived only, for a day the engine published before 026 under another
# system:* name (e.g. the old non-trading-day auto-publish).
SOURCE_SYSTEM = "system"


def new_york_date(now: datetime) -> date:
    """The calendar date in New York at `now` (an aware datetime)."""
    return now.astimezone(NEW_YORK).date()


def _new_york(day: date, at: time) -> datetime:
    return datetime.combine(day, at, tzinfo=NEW_YORK)


def approve_by(day: date) -> datetime:
    """09:30 New York on `day`: approvals made before it are e-mailed then."""
    return _new_york(day, APPROVE_BY)


def fallback_at(day: date) -> datetime:
    """10:00 New York on `day`: the last moment to approve; the engine's
    fallback sends the model's book from then on."""
    return _new_york(day, FALLBACK_AT)


def approval_closed(day: date, now: datetime) -> bool:
    return now >= fallback_at(day)


def closed_message(day: date, action: str = "Approval") -> str:
    """Why `action` is refused on `day` after 10:00 New York (HTTP 409)."""
    return (
        f"{action} of the {day.isoformat()} book closed at 10:00 New York on "
        f"{day.isoformat()}; the model's book is sent instead (fallback)"
    )


def deadlines(day: date | None, now: datetime) -> dict:
    """The desk-state's clock block. `bookDate` is the desk's book date, or
    today (New York) while there is no book yet; `approveBy`/`fallbackAt`
    refer to it. The `today*` pair always refers to today in New York (the
    next book's deadlines while the desk still shows an older day)."""
    today = new_york_date(now)
    book_date = day if day is not None else today
    return {
        "timezone": NEW_YORK_NAME,
        "today": today.isoformat(),
        "bookDate": book_date.isoformat(),
        "approveBy": approve_by(book_date).isoformat(),
        "fallbackAt": fallback_at(book_date).isoformat(),
        "todayApproveBy": approve_by(today).isoformat(),
        "todayFallbackAt": fallback_at(today).isoformat(),
        "approvalClosed": approval_closed(book_date, now),
    }


def publish_source(column: str | None, published_by: str | None) -> str | None:
    """Who published the day: the 026 column when the engine set it, else
    read from published_by (a day published before 026, or a database
    without the column)."""
    if column in PUBLISH_SOURCES:
        return column
    if not published_by:
        return None
    if published_by.startswith("system:fallback"):
        return SOURCE_FALLBACK
    if published_by == "system:model-only":
        return SOURCE_MODEL_ONLY
    if published_by.startswith("system:"):
        return SOURCE_SYSTEM
    return SOURCE_DESK

