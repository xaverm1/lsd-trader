"""Hand-built bar fixtures. Prices are in ticks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from lsdtrader.core.bar import TickBar

T0 = datetime(2024, 1, 2, 14, 30, tzinfo=UTC)


def make_bars(*ohlc: tuple[int, int, int, int], start: int = 0) -> list[TickBar]:
    """Bars 5 minutes apart from (open, high, low, close) tuples.

    `start` is the bar number of the first bar, so fixtures can be appended to others.
    """
    return [
        TickBar(T0 + timedelta(minutes=5 * (start + i)), o, h, lo, c)
        for i, (o, h, lo, c) in enumerate(ohlc)
    ]


def bars_from_lows(*lows: int) -> list[TickBar]:
    """Small bullish bars with the given lows (only lows matter for swing tests)."""
    return make_bars(*[(low + 1, low + 2, low, low + 1) for low in lows])


# Scenario 14 of the Strategy Spec: a complete long trade.
# L0 = bar 1 (100) · P = bar 6 (106), H2 = 118 · BOS bar 9 · zone [106, 111] accuracy
# P′ = bar 11 (113), H2′ = 122 · BOS bar 13 · sweep + tap bar 15 · entry bar 16 at 114
FULL_LONG = make_bars(
    (110, 112, 104, 105),  # 0
    (105, 106, 100, 101),  # 1  L0
    (101, 108, 101, 107),  # 2
    (107, 115, 106, 114),  # 3
    (114, 118, 113, 117),  # 4  H2
    (117, 117, 110, 111),  # 5
    (111, 112, 106, 107),  # 6  P, bearish -> zone origin O
    (107, 110, 107, 109),  # 7  F: high 110 <= O.high 112 -> accuracy [106, 111]
    (109, 116, 108, 115),  # 8
    (115, 121, 114, 120),  # 9  BOS (close 120 > 118), zone left (low 114 > 111)
    (120, 122, 116, 117),  # 10 H2'
    (117, 118, 113, 114),  # 11 P'
    (114, 119, 114, 118),  # 12
    (118, 124, 117, 123),  # 13 BOS of P' (close 123 > 122)
    (123, 123, 115, 116),  # 14
    (116, 117, 110, 112),  # 15 sweep of 113 and tap of 111
    (112, 115, 111, 114),  # 16 bullish close -> entry 114, stop 110, target 130
)
