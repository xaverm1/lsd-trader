"""M3 · Demand zones (Strategy Spec §5): origin, relocation, geometry, destruction."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from lsdtrader.core.bar import TickBar
from lsdtrader.core.config import StrategyConfig
from lsdtrader.core.events import EventLog
from lsdtrader.strategy.structure import Bos

ZoneState = Literal["building", "left", "destroyed", "dead", "consumed"]


@dataclass(slots=True)
class Zone:
    zone_id: int
    o_idx: int  # origin bar O
    top: int
    bot: int
    p_idx: int  # swing low whose BOS created the zone
    created_idx: int
    kind: Literal["normal", "accuracy"] = "normal"
    pending: bool = True  # geometry waits for the follow-up bar F
    state: ZoneState = "building"
    trades: int = 0
    ended_idx: int | None = None  # bar on which the zone stopped being live

    @property
    def live(self) -> bool:
        return self.state in ("building", "left")

    def overlaps(self, bar: TickBar) -> bool:
        return bar.low <= self.top and bar.high >= self.bot


def is_opposing(bar: TickBar, doji_tol_ticks: int) -> bool:
    """Bearish or doji: the bar type that can form a demand zone."""
    return bar.close < bar.open or abs(bar.close - bar.open) <= doji_tol_ticks


def find_origin(bars: Sequence[TickBar], p_idx: int, lookback: int, doji_tol_ticks: int) -> int:
    """First opposing bar searching back from P (inclusive); P itself if none (§5.1)."""
    for k in range(p_idx, max(p_idx - lookback, -1), -1):
        if is_opposing(bars[k], doji_tol_ticks):
            return k
    return p_idx


class ZoneBook:
    def __init__(self, cfg: StrategyConfig, log: EventLog) -> None:
        self._cfg = cfg
        self._log = log
        self._zones: list[Zone] = []
        self._next_id = 0
        # Every bar any zone has ever used as origin. A zone starting on such a bar would
        # replay into an exact copy of the earlier zone (same bars, same rules).
        self._origins: set[int] = set()
        # Every zone ever created, kept for inspection (charts, "why no setup here?").
        self.history: list[Zone] = []
        self._current = -1

    def live(self) -> list[Zone]:
        return [z for z in self._zones if z.live]

    def create(self, bars: Sequence[TickBar], bos: Bos) -> list[Zone]:
        """Create the zone(s) for a BOS and replay them up to the newest bar."""
        o = find_origin(bars, bos.p_idx, self._cfg.zone_lookback, self._cfg.doji_tol_ticks)
        zone = self._new(bars, o, bos)
        created = [zone] if zone is not None else []
        if self._cfg.extra_zones != "none":
            created += self._extra(bars, bos, created)
        return created

    def update(self, bars: Sequence[TickBar]) -> None:
        """Advance every live zone by the newest bar, then drop finished zones."""
        k = len(bars) - 1
        self._current = k
        for z in self._zones:
            if z.live:
                self._step(bars, z, k)
                self._mark_end(z, k)
        self._zones = [z for z in self._zones if z.live]

    def relocate_touched(self, bars: Sequence[TickBar], running: set[int]) -> None:
        """Relocation after a zone was left (Strategy Spec §5.2 amendment).

        Call after setups have been processed for the newest bar: an opposing bar touching a
        left zone moves the zone onto it, unless a setup is running for that zone (then the
        touch is a tap). Destruction has already been applied by `update`.
        """
        k = len(bars) - 1
        bar = bars[k]
        if not is_opposing(bar, self._cfg.doji_tol_ticks):
            return
        for z in self._zones:
            if z.state == "left" and z.zone_id not in running and z.overlaps(bar):
                if self._relocate(z, k, bar):
                    z.state = "building"
                self._mark_end(z, k)

    def kill_by_minute(self, zone: Zone, minute: TickBar) -> None:
        """zone_kill=wick_beyond inside a strategy bar: a minute trading below the zone."""
        if self._cfg.zone_kill == "wick_beyond" and zone.live and minute.low < zone.bot:
            self._destroy(zone, "wick")
            self._mark_end(zone, self._current + 1)

    def consume(self, zone: Zone) -> None:
        zone.trades += 1
        if zone.trades >= self._cfg.max_trades_per_zone:
            zone.state = "consumed"
            self._mark_end(zone, self._current)

    # -- internals ---------------------------------------------------------

    @staticmethod
    def _mark_end(z: Zone, k: int) -> None:
        if not z.live and z.ended_idx is None:
            z.ended_idx = k

    def _new(self, bars: Sequence[TickBar], o: int, bos: Bos) -> Zone | None:
        if o in self._origins:
            self._log.emit("zone_duplicate", o_idx=o, p_idx=bos.p_idx)
            return None
        self._origins.add(o)
        ob = bars[o]
        zone = Zone(self._next_id, o, ob.high, ob.low, bos.p_idx, len(bars) - 1)
        self._next_id += 1
        self._log.emit("zone_created", zone_id=zone.zone_id, o_idx=o, p_idx=bos.p_idx)
        for k in range(o + 1, len(bars)):
            if not zone.live:
                break
            self._step(bars, zone, k)
            self._mark_end(zone, k)
        self._zones.append(zone)
        self.history.append(zone)
        return zone

    def _extra(self, bars: Sequence[TickBar], bos: Bos, created: list[Zone]) -> list[Zone]:
        """Non-overlapping opposing bars between P and the BOS bar (§5.5)."""
        tol = self._cfg.doji_tol_ticks
        ks = [k for k in range(bos.p_idx + 1, bos.bos_idx) if is_opposing(bars[k], tol)]
        if self._cfg.extra_zones == "last":
            ks.reverse()
        extra: list[Zone] = []
        for k in ks:
            if any(z.overlaps(bars[k]) or z.o_idx == k for z in created + extra):
                continue
            zone = self._new(bars, k, bos)
            if zone is not None:
                extra.append(zone)
            if self._cfg.extra_zones == "last":
                break
        return extra

    def _step(self, bars: Sequence[TickBar], z: Zone, k: int) -> None:
        if z.state == "building":
            self._build_step(bars, z, k)
        else:
            self._destroy_step(bars[k], z)

    def _relocate(self, z: Zone, k: int, bar: TickBar) -> bool:
        """Move the zone onto bar k; False (zone dead) if another zone already starts there."""
        if k in self._origins:
            # Another zone already starts on this bar; moving here would copy it.
            z.state = "dead"
            self._log.emit("zone_duplicate", zone_id=z.zone_id, o_idx=k)
            return False
        self._origins.add(k)
        z.o_idx, z.top, z.bot = k, bar.high, bar.low
        z.kind, z.pending = "normal", True
        self._log.emit("zone_relocation", zone_id=z.zone_id, o_idx=k)
        return True

    def _build_step(self, bars: Sequence[TickBar], z: Zone, k: int) -> None:
        bar = bars[k]
        if is_opposing(bar, self._cfg.doji_tol_ticks) and z.overlaps(bar):
            if not self._relocate(z, k, bar):
                return
        elif z.pending:
            self._fix_geometry(bars[z.o_idx], bar, z)
        if bar.close < z.bot:
            z.state = "dead"
            self._log.emit("zone_died_building", zone_id=z.zone_id)
        elif bar.low > z.top:
            z.state = "left"
            self._log.emit("zone_left", zone_id=z.zone_id)

    def _fix_geometry(self, o: TickBar, f: TickBar, z: Zone) -> None:
        if self._cfg.zone_mode == "normal" or f.high > o.high:
            z.kind, z.top, z.bot = "normal", o.high, o.low
        else:
            z.kind, z.top, z.bot = "accuracy", o.body_top, min(o.low, f.low)
        z.pending = False

    def _destroy_step(self, bar: TickBar, z: Zone) -> None:
        if self._cfg.zone_kill == "close_inside":
            if bar.close <= z.top:
                self._destroy(z, "close")
            elif bar.low < z.bot:
                self._destroy(z, "wick")
        elif self._cfg.zone_kill == "wick_beyond":
            if bar.low < z.bot:
                self._destroy(z, "close" if bar.close < z.bot else "wick")
        elif bar.close < z.bot:
            self._destroy(z, "close")

    def _destroy(self, z: Zone, reason: str) -> None:
        z.state = "destroyed"
        self._log.emit(f"zone_destroyed_{reason}", zone_id=z.zone_id)
