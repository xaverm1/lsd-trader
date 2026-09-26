"""M5 · Sweep → tap → entry, plus stop and target (Strategy Spec §7, §8.1)."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from lsdtrader.core.bar import TickBar
from lsdtrader.core.config import StrategyConfig
from lsdtrader.core.events import EventLog
from lsdtrader.strategy.liquidity import Liquidity
from lsdtrader.strategy.zones import Zone, ZoneBook


@dataclass(slots=True)
class Setup:
    setup_id: int
    zone: Zone
    liq: Liquidity
    sweep_idx: int
    atr: float | None
    tap_idx: int | None = None
    low: int | None = None  # sweep_1m_cisd: lowest low since the sweep
    cisd: int | None = None  # sweep_1m_cisd: open of the bearish run that made `low`
    abs_high: int | None = None  # absorption_1m: armed absorption minute
    abs_low: int | None = None
    abs_ts: datetime | None = None
    abs_score: float | None = None
    sweep_ts: datetime | None = None  # 1-minute modes: minute of the sweep
    tap_ts: datetime | None = None  # 1-minute modes: minute of the tap


@dataclass(frozen=True, slots=True)
class Entry:
    setup_id: int
    entry_idx: int
    entry: int
    stop: int
    target: int
    zone_id: int
    zone_top: int
    zone_bot: int
    zone_o_idx: int
    liq_idx: int
    liq_price: int
    sweep_idx: int
    tap_idx: int
    features: dict[str, object] = field(default_factory=dict)
    ts: datetime | None = None  # 1-minute bar of a reclaim entry (None: the strategy bar)


class SetupTracker:
    def __init__(self, cfg: StrategyConfig, log: EventLog, zones: ZoneBook) -> None:
        self._cfg = cfg
        self._log = log
        self._zones = zones
        self._pending: list[Setup] = []
        self._next_id = 0

    @property
    def pending(self) -> list[Setup]:
        return list(self._pending)

    def start(
        self,
        zone: Zone,
        liq: Liquidity,
        sweep_idx: int,
        atr: float | None,
        sweep_ts: datetime | None = None,
    ) -> Setup | None:
        """Start a setup unless the zone already has one running."""
        if any(s.zone is zone for s in self._pending):
            self._log.emit("setup_already_running", zone_id=zone.zone_id, liq_idx=liq.idx)
            return None
        setup = Setup(self._next_id, zone, liq, sweep_idx, atr, sweep_ts=sweep_ts)
        self._next_id += 1
        self._pending.append(setup)
        self._log.emit(
            "setup_started",
            setup_id=setup.setup_id,
            zone_id=zone.zone_id,
            zone_top=zone.top,
            zone_bot=zone.bot,
            zone_o_idx=zone.o_idx,
            liq_idx=liq.idx,
            liq_price=liq.price,
        )
        return setup

    def update(self, bars: Sequence[TickBar]) -> list[Entry]:
        """Advance pending setups by the newest bar (zones must already be updated)."""
        i = len(bars) - 1
        entries: list[Entry] = []
        keep: list[Setup] = []
        for s in self._pending:
            result = self._advance(bars, s, i)
            if isinstance(result, Entry):
                entries.append(result)
            elif result:
                keep.append(s)
        self._pending = keep
        return entries

    def _advance(self, bars: Sequence[TickBar], s: Setup, i: int) -> Entry | bool:
        """Returns an Entry, True to keep waiting, or False to drop the setup."""
        cfg, bar, z = self._cfg, bars[i], s.zone
        if z.state != "left":
            self._log.emit("setup_zone_gone", setup_id=s.setup_id, zone_state=z.state)
            return False
        if cfg.entry_mode in ("sweep_1m_cisd", "absorption_1m"):  # tap and entry: on_minute
            if s.tap_idx is None and i - s.sweep_idx >= cfg.max_bars_sweep_to_tap:
                self._log.emit("no_tap", setup_id=s.setup_id)
                return False
            if s.tap_idx is not None and i - s.tap_idx >= cfg.max_bars_tap_to_entry:
                self._log.emit("no_entry", setup_id=s.setup_id)
                return False
            return True
        if s.tap_idx is None:
            if bar.low <= z.top + cfg.tap_tol_ticks:
                s.tap_idx = i
                self._log.emit("tap", setup_id=s.setup_id)
            elif i - s.sweep_idx >= cfg.max_bars_sweep_to_tap:
                self._log.emit("no_tap", setup_id=s.setup_id)
                return False
            else:
                return True
        if self._cfg.entry_mode == "reclaim_1m":
            pass  # entries come from minute_entries on the following bars
        elif self._triggered(bars, s, i):
            return self._enter(bars, s, i)
        if i - s.tap_idx >= cfg.max_bars_tap_to_entry:
            self._log.emit("no_entry", setup_id=s.setup_id)
            return False
        return True

    def minute_entries(self, bars: Sequence[TickBar], minutes: Sequence[TickBar]) -> list[Entry]:
        """Reclaim entries inside the next strategy bar (`bars` end with the bar before it).

        A setup whose tap bar has closed enters on the close of the first minute that closes
        above the swept liquidity; the stop is the lowest low since the sweep, to the minute.
        """
        i = len(bars)  # index the strategy bar of `minutes` will get
        entries: list[Entry] = []
        keep: list[Setup] = []
        for s in self._pending:
            if s.tap_idx is None or s.zone.state != "left":
                keep.append(s)
                continue
            low = min(b.low for b in bars[s.sweep_idx :])
            entry = None
            for m in minutes:
                low = min(low, m.low)
                if m.close > s.liq.price:
                    entry = self._enter(bars, s, i, m.close, low, m.ts)
                    break
            if entry is None:
                keep.append(s)
            else:
                entries.append(entry)
        self._pending = keep
        return entries

    def on_minute_absorption(
        self, bars: Sequence[TickBar], m: TickBar, score: float
    ) -> list[Entry]:
        """absorption_1m: advance setups by one minute (see StrategyConfig.entry_mode)."""
        cfg, i = self._cfg, len(bars)
        entries: list[Entry] = []
        keep: list[Setup] = []
        wait = timedelta(minutes=cfg.absorb_wait_min)
        for s in self._pending:
            z = s.zone
            self._zones.kill_by_minute(z, m)
            if z.state == "left":
                if s.low is None or m.low < s.low:
                    s.low = m.low
                    s.abs_high = None  # a lower low: the absorption failed
                if self._tap_too_late(s, m):
                    continue
                if s.tap_idx is None and m.low <= z.top + cfg.tap_tol_ticks:
                    s.tap_idx, s.tap_ts = i, m.ts
                    self._log.emit("tap", setup_id=s.setup_id)
                if s.tap_idx is not None:
                    if s.abs_high is not None and m.close > s.abs_high:
                        assert s.abs_low is not None
                        stop = s.low if cfg.stop_ref == "extreme" else s.abs_low
                        entry = self._enter(bars, s, i, m.close, stop, m.ts)
                        entry.features["abs_score"] = s.abs_score
                        entry.features["abs_ts"] = s.abs_ts  # absorption minute
                        entry.features["abs_high"] = s.abs_high  # side space: negated for shorts
                        entry.features["abs_low"] = s.abs_low
                        entries.append(entry)
                        continue
                    if s.abs_ts is not None and s.abs_high is not None and m.ts - s.abs_ts >= wait:
                        s.abs_high = None
                    lower_wick = m.high + m.low <= 2 * min(m.open, m.close)
                    if score >= cfg.absorb_min and lower_wick:
                        s.abs_high, s.abs_low, s.abs_ts, s.abs_score = m.high, m.low, m.ts, score
            keep.append(s)
        self._pending = keep
        return entries

    def on_minute(self, bars: Sequence[TickBar], m: TickBar, run_open: int | None) -> list[Entry]:
        """sweep_1m_cisd: advance setups by one minute of the strategy bar that will get index
        len(bars). `run_open` is the open of the latest run of bearish minutes (incl. `m`).

        CISD (change in state of delivery, bullish): a close above the open of the run of
        consecutive bearish candles that made the low. Entry on the first minute after the
        tap (the tapping minute included) that closes above both P' and that level.
        """
        i = len(bars)
        entries: list[Entry] = []
        keep: list[Setup] = []
        for s in self._pending:
            z = s.zone
            self._zones.kill_by_minute(z, m)
            if z.state == "left":
                if s.low is None or m.low < s.low:
                    s.low, s.cisd = m.low, run_open
                if self._tap_too_late(s, m):
                    continue
                if s.tap_idx is None and m.low <= z.top + self._cfg.tap_tol_ticks:
                    s.tap_idx, s.tap_ts = i, m.ts
                    self._log.emit("tap", setup_id=s.setup_id)
                level = max(s.liq.price, s.cisd if s.cisd is not None else s.liq.price)
                if s.tap_idx is not None and m.close > level:
                    entry = self._enter(bars, s, i, m.close, s.low, m.ts)
                    entry.features["cisd_level"] = s.cisd  # side space: negated for shorts
                    entries.append(entry)
                    continue
            keep.append(s)
        self._pending = keep
        return entries

    def _tap_too_late(self, s: Setup, m: TickBar) -> bool:
        """max_min_sweep_to_tap: no tap yet and the window since the sweep minute has passed."""
        limit = self._cfg.max_min_sweep_to_tap
        if limit is None or s.tap_idx is not None or s.sweep_ts is None:
            return False
        if m.ts - s.sweep_ts > timedelta(minutes=limit):
            self._log.emit("no_tap", setup_id=s.setup_id)
            return True
        return False

    def _triggered(self, bars: Sequence[TickBar], s: Setup, i: int) -> bool:
        bar = bars[i]
        if bar.close <= bar.open:
            return False
        trigger = self._cfg.entry_trigger
        if trigger == "above_tap_high":
            assert s.tap_idx is not None
            return bar.close > bars[s.tap_idx].high
        if trigger == "above_liq":
            return bar.close > s.liq.price
        if trigger == "min_body":
            return bar.close - bar.open >= self._cfg.min_body_ticks
        return True

    def _enter(
        self,
        bars: Sequence[TickBar],
        s: Setup,
        i: int,
        close: int | None = None,
        wick_low: int | None = None,
        ts: datetime | None = None,
    ) -> Entry:
        """Entry on bar `i` at its close, or at a minute's `close` (reclaim, with the lowest
        low since the sweep in `wick_low` and the minute in `ts`)."""
        cfg, z = self._cfg, s.zone
        assert s.tap_idx is not None
        entry = bars[i].close if close is None else close
        if cfg.sl_mode == "zone_bottom":
            stop = z.bot
        elif cfg.sl_mode == "zone_mid":
            stop = (z.top + z.bot) // 2
        elif wick_low is not None:
            stop = wick_low
        else:
            stop = min(b.low for b in bars[s.sweep_idx : i + 1])
        stop -= cfg.sl_buffer_ticks
        risk = entry - stop
        target = entry + math.ceil(cfg.rr * risk)
        dist = s.liq.price - z.top
        features: dict[str, object] = {
            "zone_height_ticks": z.top - z.bot,
            "zone_kind": z.kind,
            "liq_dist_ticks": dist,
            "liq_dist_atr": dist / s.atr if s.atr else None,
            "bars_sweep_to_tap": s.tap_idx - s.sweep_idx,
            "bars_tap_to_entry": i - s.tap_idx,
            "stop_ticks": risk,
        }
        if s.sweep_ts is not None and s.tap_ts is not None:
            features["min_sweep_to_tap"] = (s.tap_ts - s.sweep_ts).total_seconds() / 60
        result = Entry(
            s.setup_id,
            i,
            entry,
            stop,
            target,
            z.zone_id,
            z.top,
            z.bot,
            z.o_idx,
            s.liq.idx,
            s.liq.price,
            s.sweep_idx,
            s.tap_idx,
            features,
            ts,
        )
        self._zones.consume(z)
        self._log.emit("entry", setup_id=s.setup_id, zone_id=z.zone_id)
        return result
