"""Data report (Design §4.4): coverage, gaps and price jumps. Reports, never repairs."""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from lsdtrader.core.bar import TickBar
from lsdtrader.core.instrument import Instrument

# Pauses shorter than this are ordinary thin trading.
GAP_LISTED = timedelta(minutes=15)
# A pause is an expected break (daily halt, weekend, holiday) only if trading resumes at the
# regular 18:00 New York reopen. Any other pause is listed, so data holes and a wrong time
# zone both show up.
NEW_YORK = ZoneInfo("America/New_York")
REOPEN = time(18, 0)
JUMP_FACTOR = 50  # a bar-to-bar jump this many times the median 1-minute range is listed


@dataclass(frozen=True, slots=True)
class Gap:
    after: datetime
    length: timedelta


@dataclass(frozen=True, slots=True)
class Jump:
    ts: datetime
    ticks: int


@dataclass(frozen=True, slots=True)
class DataReport:
    instrument: str
    first: datetime | None
    last: datetime | None
    n_minutes: int
    n_breaks: int  # pauses that end at the 18:00 New York reopen
    gaps: list[Gap]  # all other pauses of GAP_LISTED or more
    jumps: list[Jump]
    median_range_ticks: float
    duplicates_dropped: int = 0

    def to_markdown(self) -> str:
        lines = [
            f"# Data report {self.instrument}",
            "",
            f"- Range: {self.first} to {self.last}",
            f"- 1-minute bars: {self.n_minutes}",
            f"- Duplicate timestamps dropped while loading: {self.duplicates_dropped}",
            f"- Expected breaks (resume at 18:00 New York): {self.n_breaks}",
            f"- Median 1-minute range: {self.median_range_ticks:.1f} ticks",
            f"- Unexpected gaps ({GAP_LISTED} or longer): {len(self.gaps)}",
            f"- Price jumps over {JUMP_FACTOR}x median range: {len(self.jumps)}",
        ]
        if self.gaps:
            lines += ["", "## Largest gaps", "", "| After | Length |", "|---|---|"]
            for g in sorted(self.gaps, key=lambda g: g.length, reverse=True)[:20]:
                lines.append(f"| {g.after} | {g.length} |")
        if self.jumps:
            lines += ["", "## Price jumps", "", "| At | Ticks |", "|---|---|"]
            for j in sorted(self.jumps, key=lambda j: abs(j.ticks), reverse=True)[:20]:
                lines.append(f"| {j.ts} | {j.ticks:+d} |")
        return "\n".join(lines) + "\n"


def build_report(
    instrument: Instrument, minutes: Sequence[TickBar], duplicates_dropped: int = 0
) -> DataReport:
    if not minutes:
        return DataReport(instrument.root, None, None, 0, 0, [], [], 0.0, duplicates_dropped)
    median_range = statistics.median(m.high - m.low for m in minutes) or 1.0
    breaks, gaps, jumps = 0, [], []
    for prev, cur in zip(minutes, minutes[1:], strict=False):
        pause = cur.ts - prev.ts - timedelta(minutes=1)
        expected = pause >= GAP_LISTED and cur.ts.astimezone(NEW_YORK).time() == REOPEN
        if expected:
            breaks += 1
        elif pause >= GAP_LISTED:
            gaps.append(Gap(prev.ts, pause))
        jump = cur.open - prev.close
        if not expected and abs(jump) > JUMP_FACTOR * median_range:
            jumps.append(Jump(cur.ts, jump))
    return DataReport(
        instrument.root,
        minutes[0].ts,
        minutes[-1].ts,
        len(minutes),
        breaks,
        gaps,
        jumps,
        float(median_range),
        duplicates_dropped,
    )
