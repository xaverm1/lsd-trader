"""The LSD strategy: M1–M5 composed, long side plus mirrored short side."""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Literal

from lsdtrader.core.bar import TickBar
from lsdtrader.core.config import StrategyConfig
from lsdtrader.core.events import Event, EventLog
from lsdtrader.strategy.atr import Atr
from lsdtrader.strategy.context import LevelBook, TrendTracker, hh_hl
from lsdtrader.strategy.liquidity import LiquidityBook, match_zones
from lsdtrader.strategy.setups import Entry, SetupTracker
from lsdtrader.strategy.structure import StructureTracker, strong_level
from lsdtrader.strategy.swings import confirmed_swing_low
from lsdtrader.strategy.zones import ZoneBook

Side = Literal["long", "short"]
TREND_PIVOTS = (1, 2, 5, 10, 20)  # swing size of the structure-trend candidates
HHHL_HALVES = (48, 144)  # 4 h and 12 h halves (5-minute bars)
LEVEL_PIVOTS = (5, 10, 20)  # swing size of the key-level candidates


@dataclass(frozen=True, slots=True)
class Signal:
    """An entry decision in real tick prices. The broker fills at `entry` (bar close)."""

    side: Side
    bar_index: int
    ts: datetime
    entry: int
    stop: int
    target: int
    setup_id: str
    zone_id: str
    zone_top: int
    zone_bot: int
    zone_o_idx: int
    liq_idx: int
    liq_price: int
    sweep_idx: int
    tap_idx: int
    features: dict[str, object] = field(default_factory=dict)


def unmirror_detail(detail: dict[str, object]) -> dict[str, object]:
    """Short side runs on mirrored bars: negate prices and swap zone top/bottom."""
    out = dict(detail)
    for key in ("liq_price", "h2"):
        value = out.get(key)
        if isinstance(value, int):
            out[key] = -value
    top, bot = out.get("zone_top"), out.get("zone_bot")
    if isinstance(top, int) and isinstance(bot, int):
        out["zone_top"], out["zone_bot"] = -bot, -top
    return out


class SideEngine:
    """Long-side rules. The short side is this same class fed with mirrored bars."""

    def __init__(self, cfg: StrategyConfig) -> None:
        self.cfg = cfg
        self.log = EventLog()
        self.bars: list[TickBar] = []
        self._atr = Atr(cfg.atr_len)
        self.structure = StructureTracker(cfg, self.log)
        self.zones = ZoneBook(cfg, self.log)
        self.liquidity = LiquidityBook()
        self.setups = SetupTracker(cfg, self.log, self.zones)
        # RD-TREE v3 context candidates (research features, filter nothing)
        self.trends = {n: TrendTracker(n) for n in TREND_PIVOTS}
        self.levels = {n: LevelBook(n) for n in LEVEL_PIVOTS}
        self._trend_state: dict[int, int] = {n: 0 for n in TREND_PIVOTS}
        self._last_atr: float | None = None
        self._run_open: int | None = None  # open of the latest run of bearish minutes
        self._bearish_run = False
        self._vols: deque[float] = deque(maxlen=cfg.absorb_len)
        self._vsum = 0.0
        self._vsq = 0.0

    def on_bar(self, bar: TickBar, minutes: Sequence[TickBar] | None = None) -> list[Entry]:
        """`minutes` (this bar's 1-minute bars, same side) feed reclaim entries."""
        early: list[Entry] = []
        by_minute = self.cfg.entry_mode in ("sweep_1m_cisd", "absorption_1m") and bool(minutes)
        if self.cfg.entry_mode == "reclaim_1m" and minutes:
            early = self.setups.minute_entries(self.bars, minutes)
        elif by_minute:
            assert minutes is not None
            early = self._minutes(minutes)
        for e in early:
            e.features.update(self._context(e, self._trend_state))
        self.bars.append(bar)
        i = len(self.bars) - 1
        self.log.bar_index = i
        atr = self._atr.update(bar)
        self._last_atr = atr
        self.zones.update(self.bars)
        swing = confirmed_swing_low(self.bars, self.cfg.piv_len)
        for bos in self.structure.update(self.bars, swing):
            self.log.emit("bos", p_idx=bos.p_idx, bos_idx=bos.bos_idx, h2=bos.h2)
            self.zones.create(self.bars, bos)
            n = self.cfg.liq_bos_pivot
            if n == 0 or strong_level(self.bars, bos, n):
                self.liquidity.add(bos)
            else:
                self.log.emit("liq_weak_bos", p_idx=bos.p_idx)
        before = self.liquidity.open
        for liq in [] if by_minute else self.liquidity.swept_by(bar):
            zones, reason = match_zones(liq, self.zones.live(), atr, self.cfg, before)
            if reason is not None:
                self.log.emit("sweep_no_setup", liq_idx=liq.idx, reason=reason)
            for z in zones:
                self.setups.start(z, liq, i, atr)
        trend = {n: t.update(self.bars) for n, t in self.trends.items()}
        self._trend_state = trend
        for book in self.levels.values():
            book.update(self.bars)
        entries = self.setups.update(self.bars)
        for e in entries:
            e.features.update(self._context(e, trend))
        entries = early + entries
        # an untraded touch by an opposing bar moves a left zone (Spec §5.2 amendment)
        running = {s.zone.zone_id for s in self.setups.pending}
        self.zones.relocate_touched(self.bars, running)
        return entries

    def _minutes(self, minutes: Sequence[TickBar]) -> list[Entry]:
        """sweep_1m_cisd: sweeps, taps and entries inside the coming strategy bar."""
        i = len(self.bars)
        self.log.bar_index = i
        entries: list[Entry] = []
        for m in minutes:
            if m.close < m.open:
                if not self._bearish_run:
                    self._run_open = m.open
                self._bearish_run = True
            else:
                self._bearish_run = False
            before = self.liquidity.open
            for liq in self.liquidity.swept_by(m):
                zones, reason = match_zones(
                    liq, self.zones.live(), self._last_atr, self.cfg, before
                )
                if reason is not None:
                    self.log.emit("sweep_no_setup", liq_idx=liq.idx, reason=reason)
                for z in zones:
                    self.setups.start(z, liq, i, self._last_atr, m.ts)
            score = self._volume_score(m.volume)
            if self.cfg.entry_mode == "absorption_1m":
                entries += self.setups.on_minute_absorption(self.bars, m, score)
            else:
                entries += self.setups.on_minute(self.bars, m, self._run_open)
        return entries

    def _volume_score(self, v: float) -> float:
        """Volume / population stdev of the last absorb_len minute volumes (incl. this one),
        as ta.stdev in the TradingView "Absorption Bubbles" indicator."""
        q = self._vols
        if len(q) == q.maxlen:
            old = q[0]
            self._vsum -= old
            self._vsq -= old * old
        q.append(v)
        self._vsum += v
        self._vsq += v * v
        n = len(q)
        var = max(self._vsq / n - (self._vsum / n) ** 2, 0.0)
        return v / math.sqrt(var) if var > 0 else 0.0

    def _context(self, e: Entry, trend: dict[int, int]) -> dict[str, object]:
        out: dict[str, object] = {f"trend_bos{n}": v for n, v in trend.items()}
        for half in HHHL_HALVES:
            out[f"trend_hhhl{half}"] = hh_hl(self.bars, half)
        risk = e.entry - e.stop
        for n, book in self.levels.items():
            level = book.nearest_above(e.entry)
            out[f"level{n}_r"] = (
                (level - e.entry) / risk if level is not None and risk > 0 else None
            )
        return out


class LsdStrategy:
    """One instance per instrument. Feed closed 5-minute bars in time order."""

    def __init__(self, cfg: StrategyConfig | None = None) -> None:
        self.cfg = cfg or StrategyConfig()
        self.long = SideEngine(self.cfg)
        self.short = SideEngine(self.cfg)
        self._last_ts: datetime | None = None

    def on_bar(self, bar: TickBar, minutes: Sequence[TickBar] | None = None) -> list[Signal]:
        """`minutes`: this bar's 1-minute bars (needed for entry_mode="reclaim_1m")."""
        if self._last_ts is not None and bar.ts <= self._last_ts:
            raise ValueError(f"bar at {bar.ts} is not after {self._last_ts}")
        self._last_ts = bar.ts
        mirrored = [m.mirrored() for m in minutes] if minutes else None
        signals = [self._signal("long", e, bar) for e in self.long.on_bar(bar, minutes)]
        signals += [
            self._signal("short", e, bar) for e in self.short.on_bar(bar.mirrored(), mirrored)
        ]
        return signals

    def drain_events(self) -> list[Event]:
        """Events of both sides; prices in short-side details are mapped back to real ticks."""
        events = [replace(e, side="long") for e in self.long.log.drain()]
        events += [
            replace(e, side="short", detail=unmirror_detail(e.detail))
            for e in self.short.log.drain()
        ]
        return sorted(events, key=lambda e: e.bar_index)

    @staticmethod
    def _signal(side: Side, e: Entry, bar: TickBar) -> Signal:
        s = 1 if side == "long" else -1
        top, bot = (e.zone_top, e.zone_bot) if s == 1 else (-e.zone_bot, -e.zone_top)
        return Signal(
            side,
            e.entry_idx,
            e.ts or bar.ts,
            s * e.entry,
            s * e.stop,
            s * e.target,
            f"{side}-{e.setup_id}",
            f"{side}-{e.zone_id}",
            top,
            bot,
            e.zone_o_idx,
            e.liq_idx,
            s * e.liq_price,
            e.sweep_idx,
            e.tap_idx,
            dict(e.features),
        )
