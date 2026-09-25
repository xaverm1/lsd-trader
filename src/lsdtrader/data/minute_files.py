"""Loaders for 1-minute bar files: HistData.com ASCII zips and Dukascopy CSV exports.

HistData:  zip containing DAT_ASCII_<SYMBOL>_M1_<YEAR>.csv, rows `YYYYMMDD HHMMSS;O;H;L;C;V`,
           bid prices. The file clock is Europe/Berlin time minus 6 hours: UTC-5 in
           European winter, UTC-4 in European summer (verified on SPXUSD 2020 against
           the daily 16:14 New York halt).
Dukascopy: CSV with header `Etc/UTC,Open,High,Low,Close,Volume`, ISO timestamps in UTC.
Both return 1-minute TickBars in UTC. `load_minute_files` merges files, sorts, and drops
repeated timestamps, returning how many it dropped so the data report can show it.
"""

from __future__ import annotations

import csv
import re
import zipfile
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from lsdtrader.core.bar import TickBar
from lsdtrader.core.instrument import Instrument

BERLIN = ZoneInfo("Europe/Berlin")
HISTDATA_SHIFT = timedelta(hours=6)  # file clock = Berlin time - 6 h
HISTDATA_NAME = re.compile(r"DAT_ASCII_([A-Z0-9]+)_M1_\d{4,6}\.csv$", re.IGNORECASE)


def histdata_symbol(path: Path) -> str:
    """Symbol from a HistData zip, e.g. SPXUSD."""
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            m = HISTDATA_NAME.search(name)
            if m:
                return m.group(1).upper()
    raise ValueError(f"{path.name}: no DAT_ASCII_*_M1_*.csv inside")


def _bar(inst: Instrument, ts: datetime, o: str, h: str, lo: str, c: str) -> TickBar:
    return TickBar(ts, inst.to_ticks(o), inst.to_ticks(h), inst.to_ticks(lo), inst.to_ticks(c))


def read_histdata_zip(path: Path, inst: Instrument) -> list[TickBar]:
    with zipfile.ZipFile(path) as z:
        (name,) = [n for n in z.namelist() if HISTDATA_NAME.search(n)]
        text = z.read(name).decode("ascii")
    bars = []
    for line in text.splitlines():
        if not line.strip():
            continue
        stamp, o, h, lo, c, _vol = line.split(";")
        berlin = (datetime.strptime(stamp, "%Y%m%d %H%M%S") + HISTDATA_SHIFT).replace(tzinfo=BERLIN)
        bars.append(_bar(inst, berlin.astimezone(UTC), o, h, lo, c))
    return bars


def read_dukascopy_csv(path: Path, inst: Instrument) -> list[TickBar]:
    with path.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.reader(fh))
    if not rows or rows[0][0] != "Etc/UTC":
        raise ValueError(f"{path.name}: expected a Dukascopy export with an 'Etc/UTC' header")
    return [
        _bar(inst, datetime.fromisoformat(ts).astimezone(UTC), o, h, lo, c)
        for ts, o, h, lo, c, *_ in rows[1:]
        if ts
    ]


def merge(chunks: Iterable[Sequence[TickBar]]) -> list[TickBar]:
    """Sort by time and drop repeated timestamps (first occurrence wins)."""
    seen: set[datetime] = set()
    out = []
    for bar in sorted((b for chunk in chunks for b in chunk), key=lambda b: b.ts):
        if bar.ts not in seen:
            seen.add(bar.ts)
            out.append(bar)
    return out


def load_minute_files(paths: Sequence[Path], inst: Instrument) -> tuple[list[TickBar], int]:
    """Merged 1-minute bars and the number of duplicate timestamps dropped."""
    chunks: list[list[TickBar]] = []
    for p in paths:
        if p.suffix.lower() == ".zip":
            chunks.append(read_histdata_zip(p, inst))
        elif p.suffix.lower() == ".csv":
            chunks.append(read_dukascopy_csv(p, inst))
        else:
            raise ValueError(f"{p.name}: unsupported minute file (expected .zip or .csv)")
    merged = merge(chunks)
    return merged, sum(len(c) for c in chunks) - len(merged)
