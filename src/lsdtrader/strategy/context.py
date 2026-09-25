"""Context at the entry (RD-TREE v3 criteria, research features; they filter nothing).

Everything runs on the side's own bars (the short side sees mirrored bars), so "up" always
means "in the trade's direction": +1 with the trade, -1 against it, 0 unclear.

- `TrendTracker(n)`: market-structure trend from swings with `n` bars on each side. A close
  above the last confirmed swing high turns it up, a close below the last confirmed swing low
  turns it down; before the first break it is unclear. Small `n` = internal trend (the
  current leg), large `n` = external trend (the bigger structure).
- `hh_hl(bars, half)`: higher high and higher low of the last `half` bars against the `half`
  before them -> +1; lower high and lower low -> -1; anything else 0.
- `LevelBook(n)`: swing highs with `n` bars on each side that price has not traded through
  yet. The nearest one above the entry is the key level that can stop the move (potential).
"""

from __future__ import annotations

from collections.abc import Sequence

from lsdtrader.core.bar import TickBar
from lsdtrader.strategy.swings import is_swing_low


def is_swing_high(bars: Sequence[TickBar], c: int, n: int) -> bool:
    """Mirror of `is_swing_low`: left side may be equal, right side strictly lower."""
    if c - n < 0 or c + n >= len(bars):
        return False
    high = bars[c].high
    for k in range(1, n + 1):
        if bars[c - k].high > high or bars[c + k].high >= high:
            return False
    return True


class TrendTracker:
    def __init__(self, n: int) -> None:
        self.n = n
        self.state = 0
        self._high: int | None = None  # last confirmed swing high, not yet broken
        self._low: int | None = None

    def update(self, bars: Sequence[TickBar]) -> int:
        c = len(bars) - 1 - self.n
        if is_swing_high(bars, c, self.n):
            self._high = bars[c].high
        if is_swing_low(bars, c, self.n):
            self._low = bars[c].low
        close = bars[-1].close
        if self._high is not None and close > self._high:
            self.state, self._high = 1, None
        elif self._low is not None and close < self._low:
            self.state, self._low = -1, None
        return self.state


def hh_hl(bars: Sequence[TickBar], half: int) -> int:
    if len(bars) < 2 * half:
        return 0
    recent, before = bars[-half:], bars[-2 * half : -half]
    rh, rl = max(b.high for b in recent), min(b.low for b in recent)
    bh, bl = max(b.high for b in before), min(b.low for b in before)
    if rh > bh and rl > bl:
        return 1
    if rh < bh and rl < bl:
        return -1
    return 0


class LevelBook:
    def __init__(self, n: int) -> None:
        self.n = n
        self._levels: list[int] = []

    def update(self, bars: Sequence[TickBar]) -> None:
        c = len(bars) - 1 - self.n
        if is_swing_high(bars, c, self.n):
            self._levels.append(bars[c].high)
        # a level is used up once price trades through it (the bars between the swing and its
        # confirmation are lower by definition)
        high = bars[-1].high
        self._levels = [lv for lv in self._levels if lv > high]

    def nearest_above(self, price: int) -> int | None:
        above = [lv for lv in self._levels if lv > price]
        return min(above) if above else None
