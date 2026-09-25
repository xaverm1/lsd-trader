"""Loader for TradingView chart exports (the JSON files in lsd-bot/data).

Format: {"success": true, "result": "<json>"} where the inner JSON has
`sym` {name, minmov, pricescale, pointvalue, root?} and `bars` [[epoch_s, o, h, l, c], ...].
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from lsdtrader.core.bar import TickBar
from lsdtrader.core.instrument import INSTRUMENTS, Instrument


def load_tradingview_json(path: Path) -> tuple[Instrument, list[TickBar]]:
    outer = json.loads(path.read_text(encoding="utf-8"))
    inner = json.loads(outer["result"]) if isinstance(outer.get("result"), str) else outer
    sym = inner["sym"]
    tick = Decimal(sym["minmov"]) / Decimal(sym["pricescale"])
    root = str(sym.get("root") or sym["name"]).upper()
    known = INSTRUMENTS.get(root)
    if known is not None:
        if known.tick_size != tick:
            raise ValueError(
                f"{path.name}: tick {tick} does not match {root} spec {known.tick_size}"
            )
        inst = known
    else:
        inst = Instrument(root, tick, float(tick * Decimal(str(sym["pointvalue"]))), 0.0)
    bars = [
        TickBar(
            datetime.fromtimestamp(int(ts), UTC),
            inst.to_ticks(o),
            inst.to_ticks(h),
            inst.to_ticks(lo),
            inst.to_ticks(c),
        )
        for ts, o, h, lo, c in inner["bars"]
    ]
    return inst, bars
