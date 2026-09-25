"""Load bar data from any supported file type (shared by the CLI, review and inspection)."""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from lsdtrader.core.bar import TickBar
from lsdtrader.core.instrument import Instrument, get_instrument
from lsdtrader.data.aggregate import to_five_minute
from lsdtrader.data.minute_files import histdata_symbol, load_minute_files
from lsdtrader.data.tradingview import load_tradingview_json


@dataclasses.dataclass(frozen=True, slots=True)
class LoadedData:
    instrument: Instrument
    bars: list[TickBar]  # 5-minute
    minutes: dict[datetime, list[TickBar]] | None  # 1-minute bars per 5-minute bar
    minute_bars: list[TickBar]
    source: str
    duplicates_dropped: int = 0


def load_data(files: Sequence[Path], instrument: str | None) -> LoadedData:
    if len(files) == 1 and files[0].suffix.lower() == ".json":
        inst, bars = load_tradingview_json(files[0])
        return LoadedData(inst, bars, None, [], "tradingview 5m")
    symbols = {histdata_symbol(f) for f in files if f.suffix.lower() == ".zip"}
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
    bars, minutes = to_five_minute(minute_bars)
    return LoadedData(inst, bars, minutes, minute_bars, "1m files aggregated to 5m", dropped)
