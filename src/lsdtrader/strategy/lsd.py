"""The LSD strategy: M1–M5 composed, long side plus mirrored short side."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Literal

from lsdtrader.core.bar import TickBar
from lsdtrader.core.config import StrategyConfig
from lsdtrader.core.events import Event, EventLog
from lsdtrader.strategy.atr import Atr
from lsdtrader.strategy.liquidity import LiquidityBook, match_zones
from lsdtrader.strategy.setups import Entry, SetupTracker
from lsdtrader.strategy.structure import StructureTracker
from lsdtrader.strategy.swings import confirmed_swing_low
from lsdtrader.strategy.zones import ZoneBook

Side = Literal["long", "short"]


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

    def on_bar(self, bar: TickBar) -> list[Entry]:
        self.bars.append(bar)
        i = len(self.bars) - 1
        self.log.bar_index = i
        atr = self._atr.update(bar)
        self.zones.update(self.bars)
        swing = confirmed_swing_low(self.bars, self.cfg.piv_len)
        for bos in self.structure.update(self.bars, swing):
            self.log.emit("bos", p_idx=bos.p_idx, bos_idx=bos.bos_idx, h2=bos.h2)
            self.zones.create(self.bars, bos)
            self.liquidity.add(bos)
        for liq in self.liquidity.swept_by(bar):
            zones, reason = match_zones(liq, self.zones.live(), atr, self.cfg)
            if reason is not None:
                self.log.emit("sweep_no_setup", liq_idx=liq.idx, reason=reason)
            for z in zones:
                self.setups.start(z, liq, i, atr)
        return self.setups.update(self.bars)


class LsdStrategy:
    """One instance per instrument. Feed closed 5-minute bars in time order."""

    def __init__(self, cfg: StrategyConfig | None = None) -> None:
        self.cfg = cfg or StrategyConfig()
        self.long = SideEngine(self.cfg)
        self.short = SideEngine(self.cfg)
        self._last_ts: datetime | None = None

    def on_bar(self, bar: TickBar) -> list[Signal]:
        if self._last_ts is not None and bar.ts <= self._last_ts:
            raise ValueError(f"bar at {bar.ts} is not after {self._last_ts}")
        self._last_ts = bar.ts
        signals = [self._signal("long", e, bar) for e in self.long.on_bar(bar)]
        signals += [self._signal("short", e, bar) for e in self.short.on_bar(bar.mirrored())]
        return signals

    def drain_events(self) -> list[Event]:
        events = [replace(e, side="long") for e in self.long.log.drain()]
        events += [replace(e, side="short") for e in self.short.log.drain()]
        return sorted(events, key=lambda e: e.bar_index)

    @staticmethod
    def _signal(side: Side, e: Entry, bar: TickBar) -> Signal:
        s = 1 if side == "long" else -1
        top, bot = (e.zone_top, e.zone_bot) if s == 1 else (-e.zone_bot, -e.zone_top)
        return Signal(
            side,
            e.entry_idx,
            bar.ts,
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
