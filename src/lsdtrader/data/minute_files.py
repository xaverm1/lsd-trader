"""Loaders for 1-minute bar files: HistData.com ASCII zips and Dukascopy CSV exports.

HistData:  zip containing DAT_ASCII_<SYMBOL>_M1_<YEAR>.csv, rows `YYYYMMDD HHMMSS;O;H;L;C;V`,
           bid prices. The file clock depends on the year (see `histdata_clock`); the two
           clocks differ only in the weeks where US and EU daylight saving differ.
Dukascopy: CSV with header `Etc/UTC,Open,High,Low,Close,Volume`, ISO timestamps in UTC.
Databento: `<ROOT>_ohlcv1m_<YEAR>.csv.gz` (scripts/databento_download.py), header
           `ts_event,open,high,low,close,volume,instrument_id`, UTC, with real futures volume.
Both return 1-minute TickBars in UTC. `load_minute_files` merges files, sorts, and drops
repeated timestamps, returning how many it dropped so the data report can show it.
"""

from __future__ import annotations

import csv
import gzip
import re
import zipfile
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from lsdtrader.core.bar import TickBar
from lsdtrader.core.instrument import Instrument

BERLIN = ZoneInfo("Europe/Berlin")
NEW_YORK = ZoneInfo("America/New_York")
HISTDATA_SHIFT = timedelta(hours=6)  # 2019+: file clock = Berlin time - 6 h
# Up to 2018 the file clock is New York local time (UTC-5 / UTC-4 with US daylight saving).
# Verified on XAUUSD 2009-2025: up to 2018 the CME reopen is stamped 18:00/18:01 also in the
# US/EU daylight-saving mismatch weeks, from 2019 it is stamped 17:00 there (SPXUSD 2020: the
# 16:14 New York halt shows as 15:14); payrolls at 08:30 New York sit at 08:30 in the 2018
# file and at 07:30 in the 2019 file. `lsd data-report` re-checks this for every load.
LAST_NEW_YORK_CLOCK_YEAR = 2018
HISTDATA_NAME = re.compile(r"DAT_ASCII_([A-Z0-9]+)_M1_(\d{4})\d{0,2}\.csv$", re.IGNORECASE)


def histdata_clock(year: int) -> str:
    """Clock of a HistData file of this year."""
    return "America/New_York" if year <= LAST_NEW_YORK_CLOCK_YEAR else "Europe/Berlin - 6 h"


def histdata_to_utc(stamp: datetime, year: int) -> datetime:
    """UTC time of a naive HistData file stamp."""
    if year <= LAST_NEW_YORK_CLOCK_YEAR:
        return stamp.replace(tzinfo=NEW_YORK).astimezone(UTC)
    return (stamp + HISTDATA_SHIFT).replace(tzinfo=BERLIN).astimezone(UTC)


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
    m = HISTDATA_NAME.search(name)
    assert m is not None
    year = int(m.group(2))
    bars = []
    for line in text.splitlines():
        if not line.strip():
            continue
        stamp, o, h, lo, c, _vol = line.split(";")
        ts = histdata_to_utc(datetime.strptime(stamp, "%Y%m%d %H%M%S"), year)
        bars.append(_bar(inst, ts, o, h, lo, c))
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


DATABENTO_NAME = re.compile(r"^([A-Z0-9]+)_ohlcv1m_\d{4}\.csv\.gz$")


def databento_symbol(path: Path) -> str | None:
    """Instrument root of a Databento download, e.g. ES, or None for other files."""
    m = DATABENTO_NAME.match(path.name)
    return m.group(1) if m else None


def read_databento_csv(path: Path, inst: Instrument) -> list[TickBar]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
        rows = csv.reader(fh)
        header = next(rows)
        if header[:6] != ["ts_event", "open", "high", "low", "close", "volume"]:
            raise ValueError(f"{path.name}: unexpected Databento header {header}")
        return [
            TickBar(
                datetime.fromisoformat(ts).astimezone(UTC),
                inst.to_ticks(o),
                inst.to_ticks(h),
                inst.to_ticks(lo),
                inst.to_ticks(c),
                float(v),
            )
            for ts, o, h, lo, c, v, *_ in rows
        ]


def load_minute_files(paths: Sequence[Path], inst: Instrument) -> tuple[list[TickBar], int]:
    """Merged 1-minute bars and the number of duplicate timestamps dropped."""
    chunks: list[list[TickBar]] = []
    for p in paths:
        if databento_symbol(p):
            chunks.append(read_databento_csv(p, inst))
        elif p.suffix.lower() == ".zip":
            chunks.append(read_histdata_zip(p, inst))
        elif p.suffix.lower() == ".csv":
            chunks.append(read_dukascopy_csv(p, inst))
        else:
            raise ValueError(f"{p.name}: unsupported minute file (expected .zip or .csv)")
    merged = merge(chunks)
    return merged, sum(len(c) for c in chunks) - len(merged)
