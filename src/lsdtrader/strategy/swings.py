"""M1 · Swing lows (Strategy Spec §3). Swing highs are swing lows of mirrored bars."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from lsdtrader.core.bar import TickBar


@dataclass(frozen=True, slots=True)
class Swing:
    idx: int
    price: int


def is_swing_low(bars: Sequence[TickBar], c: int, n: int) -> bool:
    """True if bar `c` is a swing low with `n` bars on each side.

    Left side may be equal, right side must be strictly higher, so in a run of
    identical lows only the rightmost bar is a swing.
    """
    if c - n < 0 or c + n >= len(bars):
        return False
    low = bars[c].low
    for k in range(1, n + 1):
        if bars[c - k].low < low or bars[c + k].low <= low:
            return False
    return True


def confirmed_swing_low(bars: Sequence[TickBar], n: int) -> Swing | None:
    """The swing low that the newest bar confirms, if any (it sits `n` bars back)."""
    c = len(bars) - 1 - n
    if is_swing_low(bars, c, n):
        return Swing(c, bars[c].low)
    return None
