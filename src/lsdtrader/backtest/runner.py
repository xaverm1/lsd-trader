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

BAR = timedelta(minutes=5)
# A pause this long between bars is a closure (holiday or early close), not thin trading.
BREAK_GAP = timedelta(minutes=60)


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
    signals: list[Signal] = []
    trades: list[Trade] = []
    for i, bar in enumerate(bars):
        log.bar_index = i
        brk = None
        if i + 1 < len(bars) and bars[i + 1].ts - (bar.ts + BAR) >= BREAK_GAP:
            brk = True
        trades += broker.on_bar(bar, _exit_minutes(bar, minutes, log), brk)
        new = strategy.on_bar(bar)
        signals += new
        broker.submit(new, bar, brk)
    if bars:
        trades += broker.close_all(bars[-1])
    times = [b.ts for b in bars]
    trades = [replace(t, sweep_ts=times[t.sweep_idx], tap_ts=times[t.tap_idx]) for t in trades]
    events = strategy.drain_events() + [replace(e, side="broker") for e in log.drain()]
    events.sort(key=lambda e: e.bar_index)
    return RunResult(instrument, cfg, exec_cfg, len(bars), signals, trades, events, times)


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
