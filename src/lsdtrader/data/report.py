"""Data report (Design §4.4): coverage, gaps and price jumps. Reports, never repairs."""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from lsdtrader.core.bar import TickBar
from lsdtrader.core.instrument import Instrument

# Pauses up to this length are ordinary thin trading; longer ones are listed.
GAP_LISTED = timedelta(minutes=15)
# Daily halts and weekends are expected; they are counted separately, not listed as problems.
EXPECTED_BREAK = timedelta(minutes=45)
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
    n_breaks: int  # pauses >= EXPECTED_BREAK (halts, weekends, holidays)
    gaps: list[Gap]  # GAP_LISTED <= pause < EXPECTED_BREAK
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
            f"- Breaks of {EXPECTED_BREAK} or more (halts, weekends, holidays): {self.n_breaks}",
            f"- Median 1-minute range: {self.median_range_ticks:.1f} ticks",
            f"- Unexpected gaps ({GAP_LISTED} to {EXPECTED_BREAK}): {len(self.gaps)}",
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
        if pause >= EXPECTED_BREAK:
            breaks += 1
        elif pause >= GAP_LISTED:
            gaps.append(Gap(prev.ts, pause))
        jump = cur.open - prev.close
        if pause < EXPECTED_BREAK and abs(jump) > JUMP_FACTOR * median_range:
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
