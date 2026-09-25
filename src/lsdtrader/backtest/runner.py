"""Backtest runner: data -> strategy -> broker, one instrument at a time (Design §3, §5.1)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from lsdtrader.core.bar import TickBar
from lsdtrader.core.config import StrategyConfig
from lsdtrader.core.events import Event, EventLog
from lsdtrader.core.instrument import Instrument
from lsdtrader.execution.broker import ExecutionConfig, SimBroker, Trade
from lsdtrader.strategy.lsd import LsdStrategy, Signal

# A pause this long between bars is a closure (holiday or early close), not thin trading.
BREAK_GAP = timedelta(minutes=60)
# Target of the shadow broker: never reached, so its trades end at the stop or the flat time.
NO_TARGET = 10**15


@dataclass(frozen=True, slots=True)
class RunResult:
    instrument: Instrument
    strategy_config: StrategyConfig
    execution_config: ExecutionConfig
    n_bars: int
    signals: list[Signal]
    trades: list[Trade]
    events: list[Event]
    bar_times: list[datetime]


def run_backtest(
    instrument: Instrument,
    bars: Sequence[TickBar],
    minutes: Mapping[datetime, Sequence[TickBar]] | None = None,
    cfg: StrategyConfig | None = None,
    exec_cfg: ExecutionConfig | None = None,
) -> RunResult:
    """Run the strategy over 5-minute `bars`.

    `minutes` maps a 5-minute bar's open time to its 1-minute bars (for exit resolution).
    Without it, for a missing key, or when the minutes do not reach the 5-minute bar's
    high and low, the 5-minute bar itself is used as the only minute.
    A bar is the last before a break if the CME calendar says so or the next bar starts at
    least BREAK_GAP after this one ends (holiday closures, early closes).
    """
    cfg = cfg or StrategyConfig()
    exec_cfg = exec_cfg or ExecutionConfig()
    strategy = LsdStrategy(cfg)
    log = EventLog()
    broker = SimBroker(instrument, exec_cfg, log)
    # Shadow broker: the same signals without take profit (exact as long as the positions
    # do not limit each other, i.e. max_open_positions is off).
    shadow = SimBroker(instrument, exec_cfg, EventLog())
    free: list[Trade] = []
    signals: list[Signal] = []
    trades: list[Trade] = []
    bar_len = timedelta(minutes=exec_cfg.bar_minutes)
    for i, bar in enumerate(bars):
        log.bar_index = i
        brk = None
        if i + 1 < len(bars) and bars[i + 1].ts - (bar.ts + bar_len) >= BREAK_GAP:
            brk = True
        exit_minutes = _exit_minutes(bar, minutes, log)
        trades += broker.on_bar(bar, exit_minutes, brk)
        free += shadow.on_bar(bar, exit_minutes, brk)
        new = strategy.on_bar(bar)
        signals += new
        broker.submit(new, bar, brk)
        shadow.submit([_without_target(s) for s in new], bar, brk)
    if bars:
        trades += broker.close_all(bars[-1])
        free += shadow.close_all(bars[-1])
    times = [b.ts for b in bars]
    by_setup = {f.setup_id: f for f in free}
    trades = [
        _with_free_run(replace(t, sweep_ts=times[t.sweep_idx], tap_ts=times[t.tap_idx]), by_setup)
        for t in trades
    ]
    events = strategy.drain_events() + [replace(e, side="broker") for e in log.drain()]
    events.sort(key=lambda e: e.bar_index)
    return RunResult(instrument, cfg, exec_cfg, len(bars), signals, trades, events, times)


def _without_target(sig: Signal) -> Signal:
    return replace(sig, target=sig.entry + (NO_TARGET if sig.side == "long" else -NO_TARGET))


def _with_free_run(t: Trade, free: Mapping[str, Trade]) -> Trade:
    f = free.get(t.setup_id)
    if f is None:
        return t
    return replace(
        t,
        mfe_free_r=f.mfe_r,
        mfe_free_ts=f.mfe_ts,
        exit_free_reason=f.exit_reason,
        exit_free_r=f.gross_r,
    )


def _exit_minutes(
    bar: TickBar, minutes: Mapping[datetime, Sequence[TickBar]] | None, log: EventLog
) -> Sequence[TickBar]:
    inner = minutes.get(bar.ts) if minutes is not None else None
    if not inner:
        return [bar]
    if min(m.low for m in inner) != bar.low or max(m.high for m in inner) != bar.high:
        log.emit("minutes_incomplete", minutes=len(inner))
        return [bar]
    return inner
