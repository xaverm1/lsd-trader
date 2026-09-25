"""Backtest runner: data -> strategy -> broker, one instrument at a time (Design §3, §5.1)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime

from lsdtrader.core.bar import TickBar
from lsdtrader.core.config import StrategyConfig
from lsdtrader.core.events import Event, EventLog
from lsdtrader.core.instrument import Instrument
from lsdtrader.execution.broker import ExecutionConfig, SimBroker, Trade
from lsdtrader.strategy.lsd import LsdStrategy, Signal


@dataclass(frozen=True, slots=True)
class RunResult:
    instrument: Instrument
    strategy_config: StrategyConfig
    execution_config: ExecutionConfig
    n_bars: int
    signals: list[Signal]
    trades: list[Trade]
    events: list[Event]


def run_backtest(
    instrument: Instrument,
    bars: Sequence[TickBar],
    minutes: Mapping[datetime, Sequence[TickBar]] | None = None,
    cfg: StrategyConfig | None = None,
    exec_cfg: ExecutionConfig | None = None,
) -> RunResult:
    """Run the strategy over 5-minute `bars`.

    `minutes` maps a 5-minute bar's open time to its 1-minute bars (for exit resolution).
    Without it, or for a missing key, the 5-minute bar itself is used as the only minute.
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
        inner = minutes.get(bar.ts) if minutes is not None else None
        trades += broker.on_bar(bar, inner or [bar])
        new = strategy.on_bar(bar)
        signals += new
        broker.submit(new, bar)
    if bars:
        trades += broker.close_all(bars[-1])
    events = strategy.drain_events() + [replace(e, side="broker") for e in log.drain()]
    events.sort(key=lambda e: e.bar_index)
    return RunResult(instrument, cfg, exec_cfg, len(bars), signals, trades, events)
