"""Load bar data from any supported file type (shared by the CLI, review and inspection)."""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from lsdtrader.core.bar import TickBar
from lsdtrader.core.instrument import Instrument, get_instrument
from lsdtrader.data.aggregate import to_bars
from lsdtrader.data.minute_files import databento_symbol, histdata_symbol, load_minute_files
from lsdtrader.data.tradingview import load_tradingview_json


@dataclasses.dataclass(frozen=True, slots=True)
class LoadedData:
    instrument: Instrument
    bars: list[TickBar]  # 5-minute unless loaded with another bar length
    minutes: dict[datetime, list[TickBar]] | None  # 1-minute bars per bar
    minute_bars: list[TickBar]
    source: str
    duplicates_dropped: int = 0


def load_data(files: Sequence[Path], instrument: str | None, bar_minutes: int = 5) -> LoadedData:
    if len(files) == 1 and files[0].suffix.lower() == ".json":
        if bar_minutes != 5:
            raise SystemExit("TradingView exports are 5-minute bars only")
        inst, bars = load_tradingview_json(files[0])
        return LoadedData(inst, bars, None, [], "tradingview 5m")
    symbols = {histdata_symbol(f) for f in files if f.suffix.lower() == ".zip"}
    symbols |= {s for f in files if (s := databento_symbol(f))}
    if len(symbols) > 1:
        raise SystemExit(f"files are for different instruments: {sorted(symbols)}")
    if instrument is None:
        if not symbols:
            raise SystemExit("--instrument is required for Dukascopy CSV files")
        (instrument,) = symbols
    inst = get_instrument(instrument)
    if symbols and get_instrument(next(iter(symbols))) is not inst:
        raise SystemExit(f"--instrument {instrument} does not match the files ({symbols.pop()})")
    minute_bars, dropped = load_minute_files(files, inst)
    bars, minutes = to_bars(minute_bars, bar_minutes)
    source = f"1m files aggregated to {bar_minutes}m"
    return LoadedData(inst, bars, minutes, minute_bars, source, dropped)
