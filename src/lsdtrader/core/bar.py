"""Price bars in integer ticks.

The strategy works on integer tick prices only, so equality checks
(doji, equal lows, "touches the zone top") are exact for every instrument.
Conversion from real prices to ticks happens in the data layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class TickBar:
    """A closed bar. Prices are integer multiples of the instrument's tick size."""

    ts: datetime
    open: int
    high: int
    low: int
    close: int
    volume: float = 0.0  # traded volume (0 where the data has none, e.g. HistData CFDs)

    def __post_init__(self) -> None:
        if not (self.low <= min(self.open, self.close) and self.high >= max(self.open, self.close)):
            raise ValueError(f"inconsistent bar {self}")

    @property
    def body_top(self) -> int:
        return max(self.open, self.close)

    @property
    def body_bot(self) -> int:
        return min(self.open, self.close)

    def mirrored(self) -> TickBar:
        """The same bar reflected at price 0: highs become lows, bullish becomes bearish.

        Running the long-side rules on mirrored bars yields exactly the short-side rules
        (Strategy Spec: "a short setup is the exact mirror").
        """
        return TickBar(self.ts, -self.open, -self.low, -self.high, -self.close, self.volume)
