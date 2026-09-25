"""Simulated broker (Strategy Spec §8.2-8.3, Design §6).

Prices are integer ticks. Exits are resolved on the 1-minute bars inside each 5-minute bar;
only when stop and target fall inside the same minute is the stop assumed first.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Literal
from zoneinfo import ZoneInfo

from lsdtrader.core.bar import TickBar
from lsdtrader.core.calendar import is_last_bar_before_break
from lsdtrader.core.events import EventLog
from lsdtrader.core.instrument import Instrument
from lsdtrader.strategy.lsd import Signal

ExitReason = Literal["tp", "sl", "flat_break", "end_of_data"]


@dataclass(frozen=True, slots=True)
class ExecutionConfig:
    sizing: Literal["research", "realistic"] = "research"
    risk_usd: float = 100.0
    max_open_positions: int | None = None
    # Prop-firm defaults (Topstep-style, spec amendment 2026-09-25), in exchange time (CT):
    # new entries only from the 17:00 reopen to 14:00, everything flat with the bar ending at
    # 15:10. A window with start > end wraps over midnight.
    session_window: tuple[time, time] | None = (time(17, 0), time(14, 0))
    session_tz: str = "America/Chicago"
    flat_before_break: bool = True
    flat_time: time = time(15, 10)  # CT; time(16, 0) = the CME halt itself

    def __post_init__(self) -> None:
        if self.risk_usd <= 0:
            raise ValueError("risk_usd must be > 0")
        if self.max_open_positions is not None and self.max_open_positions < 1:
            raise ValueError("max_open_positions must be >= 1 or None")


@dataclass(slots=True)
class Position:
    signal: Signal
    qty: float
    entry_fill: int
    risk_ticks: int
    best: int  # most favourable price seen since entry
    worst: int  # most adverse price seen since entry

    @property
    def d(self) -> int:
        return 1 if self.signal.side == "long" else -1


@dataclass(frozen=True, slots=True)
class Trade:
    instrument: str
    side: str
    setup_id: str
    zone_id: str
    entry_ts: datetime
    exit_ts: datetime
    entry_signal: int
    entry_fill: int
    stop: int
    target: int
    exit_raw: int  # exit price before slippage
    exit_fill: int
    exit_reason: ExitReason
    qty: float
    risk_ticks: int
    gross_r: float
    net_r: float
    cost_r: float
    mfe_r: float
    mae_r: float
    entry_bar: int
    zone_top: int
    zone_bot: int
    zone_o_idx: int
    liq_idx: int
    liq_level: int
    sweep_idx: int
    tap_idx: int
    features: dict[str, object] = field(default_factory=dict)
    sweep_ts: datetime | None = None  # filled in by the runner, which knows bar times
    tap_ts: datetime | None = None


class SimBroker:
    def __init__(self, instrument: Instrument, cfg: ExecutionConfig, log: EventLog) -> None:
        self.instrument = instrument
        self.cfg = cfg
        self._log = log
        self._tz = ZoneInfo(cfg.session_tz)
        self.positions: list[Position] = []

    # -- step 1 of every bar: manage open positions --------------------------

    def on_bar(
        self, bar: TickBar, minutes: Sequence[TickBar], last_before_break: bool | None = None
    ) -> list[Trade]:
        """`last_before_break` overrides the regular CME calendar (e.g. holiday early closes)."""
        brk = self._is_break(bar, last_before_break)
        closed: list[Trade] = []
        still_open: list[Position] = []
        for pos in self.positions:
            trade = self._resolve(pos, minutes)
            if trade is None and brk:
                trade = self._close(pos, bar.close, bar.ts, "flat_break", slip=True)
            if trade is None:
                still_open.append(pos)
            else:
                closed.append(trade)
        self.positions = still_open
        return closed

    def close_all(self, bar: TickBar) -> list[Trade]:
        """Close everything at the bar close (end of data)."""
        closed = [
            self._close(p, bar.close, bar.ts, "end_of_data", slip=True) for p in self.positions
        ]
        self.positions = []
        return closed

    # -- step 6 of every bar: open positions from signals ------------------

    def submit(
        self, signals: Sequence[Signal], bar: TickBar, last_before_break: bool | None = None
    ) -> None:
        brk = self._is_break(bar, last_before_break)
        for sig in signals:
            reason = self._reject_reason(bar, brk)
            risk_ticks = abs(sig.entry - sig.stop)
            qty = self._qty(risk_ticks)
            if reason is None and qty <= 0:
                reason = "qty_zero"
            if reason is not None:
                self._log.emit(reason, setup_id=sig.setup_id)
                continue
            d = 1 if sig.side == "long" else -1
            inst = self.instrument
            fill = sig.entry + d * (inst.slippage_ticks + inst.spread_ticks)
            self.positions.append(Position(sig, qty, fill, risk_ticks, sig.entry, sig.entry))
            self._log.emit("order_filled", setup_id=sig.setup_id, qty=qty)

    # -- internals ---------------------------------------------------------

    def _is_break(self, bar: TickBar, override: bool | None) -> bool:
        if not self.cfg.flat_before_break:
            return False
        if override is not None:
            return override
        return is_last_bar_before_break(bar.ts, flat_at=self.cfg.flat_time)

    def _reject_reason(self, bar: TickBar, brk: bool) -> str | None:
        cfg = self.cfg
        if brk:
            return "entry_before_break"
        if cfg.session_window is not None:
            start, end = cfg.session_window
            t = bar.ts.astimezone(self._tz).time()
            inside = start <= t < end if start <= end else (t >= start or t < end)
            if not inside:
                return "entry_outside_session"
        if cfg.max_open_positions is not None and len(self.positions) >= cfg.max_open_positions:
            return "max_open_positions"
        return None

    def _qty(self, risk_ticks: int) -> float:
        raw = self.cfg.risk_usd / (risk_ticks * self.instrument.tick_value)
        return raw if self.cfg.sizing == "research" else float(math.floor(raw))

    def _resolve(self, pos: Position, minutes: Sequence[TickBar]) -> Trade | None:
        d, sig = pos.d, pos.signal
        for m in minutes:
            if d * (m.open - sig.stop) <= 0:  # gapped through the stop
                pos.worst = min(pos.worst, m.open) if d == 1 else max(pos.worst, m.open)
                return self._close(pos, m.open, m.ts, "sl", slip=True)
            if d * (m.open - sig.target) >= 0:  # gapped through the target: limit fills at target
                pos.best = max(pos.best, m.open) if d == 1 else min(pos.best, m.open)
                return self._close(pos, sig.target, m.ts, "tp", slip=False)
            fav, adv = (m.high, m.low) if d == 1 else (m.low, m.high)
            hit_sl = d * (adv - sig.stop) <= 0
            hit_tp = d * (fav - sig.target) >= 0
            if not hit_sl:
                pos.best = max(pos.best, fav) if d == 1 else min(pos.best, fav)
            pos.worst = min(pos.worst, adv) if d == 1 else max(pos.worst, adv)
            if hit_sl:
                return self._close(pos, sig.stop, m.ts, "sl", slip=True)
            if hit_tp:
                return self._close(pos, sig.target, m.ts, "tp", slip=False)
        return None

    def _close(
        self, pos: Position, price: int, ts: datetime, reason: ExitReason, slip: bool
    ) -> Trade:
        inst, sig, d = self.instrument, pos.signal, pos.d
        fill = price - d * inst.slippage_ticks if slip else price
        risk = pos.risk_ticks
        pnl = d * (fill - pos.entry_fill) * inst.tick_value * pos.qty
        pnl -= 2 * inst.commission_per_side * pos.qty
        net_r = pnl / (risk * inst.tick_value * pos.qty)
        gross_r = d * (price - sig.entry) / risk
        # Excursions stop at the exit: favourable at the target, adverse at the stop
        # unless a gap filled beyond it.
        if d == 1:
            best, worst = min(pos.best, sig.target), max(pos.worst, min(sig.stop, price))
        else:
            best, worst = max(pos.best, sig.target), min(pos.worst, max(sig.stop, price))
        self._log.emit("exit", setup_id=sig.setup_id, reason=reason)
        return Trade(
            instrument=inst.root,
            side=sig.side,
            setup_id=sig.setup_id,
            zone_id=sig.zone_id,
            entry_ts=sig.ts,
            exit_ts=ts,
            entry_signal=sig.entry,
            entry_fill=pos.entry_fill,
            stop=sig.stop,
            target=sig.target,
            exit_raw=price,
            exit_fill=fill,
            exit_reason=reason,
            qty=pos.qty,
            risk_ticks=risk,
            gross_r=gross_r,
            net_r=net_r,
            cost_r=gross_r - net_r,
            mfe_r=d * (best - sig.entry) / risk,
            mae_r=d * (sig.entry - worst) / risk,
            entry_bar=sig.bar_index,
            zone_top=sig.zone_top,
            zone_bot=sig.zone_bot,
            zone_o_idx=sig.zone_o_idx,
            liq_idx=sig.liq_idx,
            liq_level=sig.liq_price,
            sweep_idx=sig.sweep_idx,
            tap_idx=sig.tap_idx,
            features=dict(sig.features),
        )
