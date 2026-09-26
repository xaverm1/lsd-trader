"""CME Globex regular schedule (America/Chicago).

Trading runs Sunday 17:00 to Friday 16:00 CT with a daily halt 16:00-17:00 CT, the same for
the equity index, metals and crude futures used here. Holiday closures are not modelled:
a position still open across one is closed by the broker's gap handling at the next open.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

CHICAGO = ZoneInfo("America/Chicago")
HALT_START = time(16, 0)
SESSION_OPEN = time(17, 0)


def is_last_bar_before_break(
    bar_start: datetime, bar_minutes: int = 5, flat_at: time = HALT_START
) -> bool:
    """True if the bar ends exactly at `flat_at` CT on a weekday: by default the daily halt
    and the weekend close (16:00 CT), or an earlier prop-firm flat time."""
    end = (bar_start + timedelta(minutes=bar_minutes)).astimezone(CHICAGO)
    return end.weekday() < 5 and end.time() == flat_at


def session_day(ts: datetime) -> date:
    """Trading day a moment belongs to: a session opening at 17:00 CT is the next day's."""
    t = ts.astimezone(CHICAGO)
    return t.date() + timedelta(days=1) if t.time() >= SESSION_OPEN else t.date()


def trading_days_between(start: datetime, end: datetime) -> int:
    """Weekdays from the trading day of `start` up to (not including) that of `end`: 0 on
    the same day, 1 from Friday to Monday. Holidays count as trading days."""
    a, b = session_day(start), session_day(end)
    return sum(1 for k in range((b - a).days) if (a + timedelta(days=k)).weekday() < 5)
