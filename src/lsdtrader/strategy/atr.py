"""Average true range in ticks, Wilder smoothing (same as TradingView `ta.atr`)."""

from __future__ import annotations

from lsdtrader.core.bar import TickBar


class Atr:
    def __init__(self, length: int) -> None:
        self._length = length
        self._prev_close: int | None = None
        self._seed: list[int] = []
        self.value: float | None = None

    def update(self, bar: TickBar) -> float | None:
        if self._prev_close is None:
            tr = bar.high - bar.low
        else:
            tr = max(
                bar.high - bar.low,
                abs(bar.high - self._prev_close),
                abs(bar.low - self._prev_close),
            )
        self._prev_close = bar.close
        if self.value is None:
            self._seed.append(tr)
            if len(self._seed) == self._length:
                self.value = sum(self._seed) / self._length
        else:
            self.value = (self.value * (self._length - 1) + tr) / self._length
        return self.value
