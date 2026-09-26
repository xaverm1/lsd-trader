"""Build 5-minute (or longer) bars from 1-minute bars (Design §4.3).

Bars are aligned to multiples of their length from midnight UTC. A bar exists when at least
one minute exists in its window. The minutes of each bar are kept for the broker, which
resolves stop/target on them.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from lsdtrader.core.bar import TickBar


def five_minute_start(ts: datetime) -> datetime:
    return bar_start(ts, 5)


def bar_start(ts: datetime, bar_minutes: int) -> datetime:
    """Start of the `bar_minutes` bar containing `ts` (bar_minutes must divide a day)."""
    of_day = ts.hour * 60 + ts.minute
    start = of_day - of_day % bar_minutes
    return ts.replace(hour=start // 60, minute=start % 60, second=0, microsecond=0)


def to_five_minute(
    minutes: Sequence[TickBar],
) -> tuple[list[TickBar], dict[datetime, list[TickBar]]]:
    """Aggregate sorted 1-minute bars; returns (5-minute bars, minutes per 5-minute open)."""
    return to_bars(minutes, 5)


def to_bars(
    minutes: Sequence[TickBar], bar_minutes: int
) -> tuple[list[TickBar], dict[datetime, list[TickBar]]]:
    """Aggregate sorted 1-minute bars; returns (bars, minutes per bar open)."""
    if (24 * 60) % bar_minutes:
        raise ValueError(f"bar length {bar_minutes} min does not divide a day")
    groups: dict[datetime, list[TickBar]] = {}
    for m in minutes:
        groups.setdefault(bar_start(m.ts, bar_minutes), []).append(m)
    bars = [
        TickBar(
            start,
            group[0].open,
            max(m.high for m in group),
            min(m.low for m in group),
            group[-1].close,
            sum(m.volume for m in group),
        )
        for start, group in groups.items()
    ]
    return bars, groups
