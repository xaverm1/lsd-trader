"""Build 5-minute bars from 1-minute bars (Design §4.3).

Bars are aligned to multiples of 5 minutes of the clock. A 5-minute bar exists when at least
one minute exists in its window. The minutes of each 5-minute bar are kept for the broker,
which resolves stop/target on them.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from lsdtrader.core.bar import TickBar


def five_minute_start(ts: datetime) -> datetime:
    return ts.replace(minute=ts.minute - ts.minute % 5, second=0, microsecond=0)


def to_five_minute(
    minutes: Sequence[TickBar],
) -> tuple[list[TickBar], dict[datetime, list[TickBar]]]:
    """Aggregate sorted 1-minute bars; returns (5-minute bars, minutes per 5-minute open)."""
    groups: dict[datetime, list[TickBar]] = {}
    for m in minutes:
        groups.setdefault(five_minute_start(m.ts), []).append(m)
    bars = [
        TickBar(
            start,
            group[0].open,
            max(m.high for m in group),
            min(m.low for m in group),
            group[-1].close,
        )
        for start, group in groups.items()
    ]
    return bars, groups
