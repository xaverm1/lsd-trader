"""State of the strategy at any bar: zones, open liquidity and recent events (Design §8).

Answers "why was there no setup here?". The strategy is replayed from the first loaded bar
up to the requested one, so the state is exactly what a backtest over the same files had.
"""

from __future__ import annotations

import bisect
from collections.abc import Sequence
from datetime import datetime

from lsdtrader.core.bar import TickBar
from lsdtrader.core.config import StrategyConfig
from lsdtrader.strategy.lsd import LsdStrategy, SideEngine
from lsdtrader.viz.chart import Box, ChartSpec, Level

LIVE, ENDED = "#534AB7", "#888780"
CHART_EVENT_LINES = 8  # the full list goes to stdout / the .txt file
# Only objects inside the visible price range (plus this share of it) are drawn.
PRICE_MARGIN = 0.2
NOISY = ("zone_relocation", "setup_already_running")


def _zones(engine: SideEngine, side: str, first: int, idx: int) -> list[Box]:
    boxes = []
    for z in engine.zones.history:
        if z.created_idx > idx or (z.ended_idx is not None and z.ended_idx < first):
            continue
        ended = z.ended_idx is not None and z.ended_idx <= idx
        top, bot = (z.top, z.bot) if side == "long" else (-z.bot, -z.top)
        label = f"{side} zone {z.zone_id}" + (f" ({z.state})" if ended else "")
        end = z.ended_idx if ended and z.ended_idx is not None else idx
        boxes.append(Box(z.o_idx, end, top, bot, ENDED if ended else LIVE, label))
    return boxes


def _liquidity(engine: SideEngine, side: str, first: int, idx: int) -> list[Level]:
    sign = 1 if side == "long" else -1
    return [
        Level(max(liq.idx, first), idx, sign * liq.price, "#BA7517", f"{side} P' open", ":")
        for liq in engine.liquidity.open
        if liq.bos_idx <= idx
    ]


def inspect_at(
    bars: Sequence[TickBar],
    at: datetime,
    cfg: StrategyConfig | None = None,
    before: int = 120,
    after: int = 12,
) -> tuple[ChartSpec, list[str]]:
    """Chart spec and event lines for the bar that opened at or before `at`."""
    times = [b.ts for b in bars]
    idx = bisect.bisect_right(times, at) - 1
    if idx < 0:
        raise ValueError(f"{at} is before the first bar ({times[0] if times else 'no data'})")
    first = max(idx - before, 0)
    strategy = LsdStrategy(cfg)
    for bar in bars[: idx + 1]:
        strategy.on_bar(bar)
    events = [e for e in strategy.drain_events() if first <= e.bar_index <= idx]
    lines = [
        f"{times[e.bar_index]:%m-%d %H:%M} {e.side:<5} {e.kind:<22} "
        + " ".join(f"{k}={v}" for k, v in sorted(e.detail.items()))
        for e in events
    ]
    last = min(idx + after, len(bars) - 1)
    lo = min(b.low for b in bars[first : last + 1])
    hi = max(b.high for b in bars[first : last + 1])
    pad = int((hi - lo) * PRICE_MARGIN)
    lo, hi = lo - pad, hi + pad
    boxes = [
        b
        for b in _zones(strategy.long, "long", first, idx)
        + _zones(strategy.short, "short", first, idx)
        if b.top >= lo and b.bot <= hi
    ]
    levels = [
        lv
        for lv in _liquidity(strategy.long, "long", first, idx)
        + _liquidity(strategy.short, "short", first, idx)
        if lo <= lv.price <= hi
    ]
    chart_lines = [ln for e, ln in zip(events, lines, strict=True) if e.kind not in NOISY]
    spec = ChartSpec(
        first=first,
        last=last,
        title=f"State at {times[idx]:%Y-%m-%d %H:%M} UTC (bar {idx}); bars after it are not used",
        boxes=boxes,
        levels=[*levels, Level(idx, idx, bars[idx].close, "#444441", "now", "-")],
        notes=chart_lines[-CHART_EVENT_LINES:],
    )
    return spec, lines
