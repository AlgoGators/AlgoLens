"""Pure incubation lifecycle calculations."""

from dataclasses import dataclass
from datetime import datetime


# Incubation window: strategies are observed for 3-4 months
INCUBATION_WINDOW_DAYS = 120


@dataclass(frozen=True)
class IncubationWindow:
    days_elapsed: int
    window_days: int
    progress: float


def _align_datetime_awareness(started_at: datetime, now: datetime) -> datetime:
    start_is_aware = started_at.tzinfo is not None and started_at.utcoffset() is not None
    now_is_aware = now.tzinfo is not None and now.utcoffset() is not None
    if start_is_aware and now_is_aware:
        return now.astimezone(started_at.tzinfo)
    if start_is_aware and not now_is_aware:
        return now.replace(tzinfo=started_at.tzinfo)
    if not start_is_aware and now_is_aware:
        return now.replace(tzinfo=None)
    return now


def compute_incubation_window(
    incubation_started_at: datetime | None,
    now: datetime,
    window_days: int = INCUBATION_WINDOW_DAYS,
) -> IncubationWindow:
    if incubation_started_at is None:
        days_elapsed = 0
    else:
        comparable_now = _align_datetime_awareness(incubation_started_at, now)
        # Clamped at zero. `incubation_started_at` is stamped by the DATABASE
        # (`now()`), while this subtracts the APPLICATION host's clock, and the
        # two are never perfectly in step. timedelta.days floors toward negative
        # infinity, so a sub-second skew of the wrong sign turns into -1 -- which
        # is what a strategy incubated moments ago actually reported. A negative
        # elapsed count then renders as negative progress against the window.
        days_elapsed = max(0, (comparable_now - incubation_started_at).days)

    progress = min((days_elapsed / window_days) * 100, 100) if window_days > 0 else 0
    return IncubationWindow(
        days_elapsed=days_elapsed,
        window_days=window_days,
        progress=progress,
    )
