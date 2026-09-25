# Minute Data, Aggregation & Data Report (Plan 2c) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Backtest on years of real 1-minute data: load HistData and Dukascopy files, build 5-minute bars, resolve exits on the minutes, report data problems, and cost CFD trades by their spread.

**Architecture:** `data/minute_files.py` turns files into UTC 1-minute `TickBar`s (merging years, counting dropped duplicates). `data/aggregate.py` builds 5-minute bars and keeps each bar's minutes for the broker. `data/report.py` lists gaps and jumps without repairing anything. CFD instruments get a `spread_ticks` cost paid on entry. The CLI picks the loader from the file type and records the data source and exit resolution in the run folder.

**Tech Stack:** Python ≥ 3.12, stdlib only for the new code (`zipfile`, `csv`); existing pyarrow/tzdata.

**Spec:** `docs/specs/2026-09-25-engine-backtester-design.md` §4.3, §4.4 and §12 (amendment: HistData CFD data first, futures later); `docs/specs/2026-09-25-lsd-strategy-v1.md` §8.3 (costs).

## Global Constraints

- All timestamps inside the engine are UTC. HistData stamps are EST without daylight saving (fixed UTC−5).
- Loaders never repair data silently: duplicates are dropped but counted, gaps and jumps are reported.
- 5-minute bars are aligned to clock multiples of 5 minutes; a bar exists when at least one minute exists.
- CFD instruments: tick 0.001, one unit per contract, commission 0, slippage 0, spread paid once on entry. Spread values are placeholders.
- `ruff check`, `ruff format --check`, `mypy` (strict) and `pytest` pass after every task; coverage stays ≥ 90 %.
- Work on branch `feat/minute-data` in `C:\Users\Xaver\lsd-trader`; commit after every task with the repo's `Co-Authored-By` line.

## Review Focus

- **Daylight-saving dates in HistData files** — timestamps must stay fixed UTC−5 all year; converting with a New-York zone would shift half the year by an hour (test in Task 2).
- **The same minute in two files** (year boundaries, re-downloads) — must appear once, and the report must say how many were dropped (tests in Tasks 2 and 3).
- **A spread that dwarfs tight stops** — with CFD spreads of hundreds of ticks, cost R can exceed gross R; the summary already separates gross, net and cost R, and the spread must be charged exactly once per trade on either side (test in Task 1).
- **Dukascopy files without a symbol in their content** — the CLI must refuse to guess and ask for `--instrument` (test in Task 4).
- **Very large inputs** (six years ≈ 2 million minutes) — must load and run in minutes, not hours; smoke run in Task 4.

---

### Task 1: CFD instruments and spread cost

**Files:**
- Modify: `src/lsdtrader/core/instrument.py`, `src/lsdtrader/execution/broker.py` (entry fill adds `spread_ticks`)
- Test: `tests/core/test_instrument_calendar.py`, `tests/execution/test_broker.py` (append the new tests shown)

**Interfaces:**
- Produces: `Instrument.spread_ticks: int = 0`; CFD specs `SPXUSD, NSXUSD, XAUUSD, XAGUSD, WTIUSD`; `ALIASES` (Dukascopy names → roots); `get_instrument` accepts `USA500.IDX/USD`-style names.

- [ ] **Step 1: Create the branch and append the failing tests**

```bash
cd /c/Users/Xaver/lsd-trader && source .venv/Scripts/activate
git checkout -b feat/minute-data
```

Append to `tests/core/test_instrument_calendar.py`:

```python
def test_cfd_specs_and_aliases() -> None:
    spx = get_instrument("SPXUSD")
    assert spx.tick_size == Decimal("0.001") and spx.spread_ticks == 400
    assert spx.commission_per_side == 0.0 and spx.slippage_ticks == 0
    assert get_instrument("USA500.IDX/USD") is spx
    assert get_instrument("usatechidxusd").root == "NSXUSD"
```

Append to `tests/execution/test_broker.py`:

```python
def test_cfd_spread_is_paid_on_entry() -> None:
    cfd = Instrument("CFD", Decimal("0.001"), 0.001, 0.0, slippage_ticks=0, spread_ticks=3)
    for side, stop, target, expected_fill in [("long", 90, 140, 103), ("short", 110, 60, 97)]:
        log = EventLog()
        broker = SimBroker(cfd, ExecutionConfig(), log)
        broker.submit([signal(side, 100, stop, target)], bar(100, 100, 100, 100, minute=0))
        assert broker.positions[0].entry_fill == expected_fill
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/core/test_instrument_calendar.py tests/execution/test_broker.py -v`
Expected: 2 failures (`KeyError: unknown instrument 'SPXUSD'`, `TypeError: ... unexpected keyword argument 'spread_ticks'`).

- [ ] **Step 3: Implement**

`src/lsdtrader/core/instrument.py` (full file):

```python
"""Contract specifications and price <-> tick conversion."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal


@dataclass(frozen=True, slots=True)
class Instrument:
    root: str
    tick_size: Decimal
    tick_value: float  # USD per tick per contract
    commission_per_side: float  # USD per contract per side
    slippage_ticks: int = 1
    spread_ticks: int = 0  # CFDs: bid/ask spread paid once per trade (bars are bid prices)

    def to_ticks(self, price: float | Decimal | str) -> int:
        """Exact tick count of a price; raises if the price is off the tick grid."""
        q = Decimal(str(price)) / self.tick_size
        ticks = q.to_integral_value(rounding=ROUND_HALF_EVEN)
        if abs(q - ticks) > Decimal("1e-6"):
            raise ValueError(f"{price} is not on the {self.tick_size} grid of {self.root}")
        return int(ticks)

    def to_price(self, ticks: int) -> Decimal:
        return ticks * self.tick_size


def _spec(root: str, tick: str, value: float, commission: float) -> Instrument:
    return Instrument(root, Decimal(tick), value, commission)


def _cfd(root: str, spread: str) -> Instrument:
    """CFD quoted to 0.001, one unit per 'contract', cost = spread only."""
    tick = Decimal("0.001")
    return Instrument(root, tick, float(tick), 0.0, 0, int(Decimal(spread) / tick))


# Commissions are PLACEHOLDERS until the prop firm / broker is chosen (Strategy Spec §12).
INSTRUMENTS: dict[str, Instrument] = {
    i.root: i
    for i in (
        _spec("ES", "0.25", 12.50, 2.50),
        _spec("NQ", "0.25", 5.00, 2.50),
        _spec("YM", "1", 5.00, 2.50),
        _spec("RTY", "0.1", 5.00, 2.50),
        _spec("GC", "0.1", 10.00, 2.50),
        _spec("SI", "0.005", 25.00, 2.50),
        _spec("CL", "0.01", 10.00, 2.50),
        _spec("MES", "0.25", 1.25, 1.24),
        _spec("MNQ", "0.25", 0.50, 1.24),
        _spec("MYM", "1", 0.50, 1.24),
        _spec("M2K", "0.1", 0.50, 1.24),
        _spec("MGC", "0.1", 1.00, 1.24),
        _spec("SIL", "0.005", 5.00, 1.24),
        _spec("MCL", "0.01", 1.00, 1.24),
        # CFDs (HistData / Dukascopy). Spreads are PLACEHOLDERS for typical retail quotes.
        _cfd("SPXUSD", "0.4"),
        _cfd("NSXUSD", "1.0"),
        _cfd("XAUUSD", "0.25"),
        _cfd("XAGUSD", "0.02"),
        _cfd("WTIUSD", "0.03"),
    )
}

# Other names for the same CFD (Dukascopy symbols).
ALIASES = {
    "USA500IDXUSD": "SPXUSD",
    "USATECHIDXUSD": "NSXUSD",
    "LIGHTCMDUSD": "WTIUSD",
}


def get_instrument(root: str) -> Instrument:
    try:
        key = root.upper().replace(".", "").replace("/", "")
        return INSTRUMENTS[ALIASES.get(key, key)]
    except KeyError:
        raise KeyError(f"unknown instrument {root!r}; known: {sorted(INSTRUMENTS)}") from None
```

In `src/lsdtrader/execution/broker.py`, `SimBroker.submit`, replace the fill line:

```python
            inst = self.instrument
            fill = sig.entry + d * (inst.slippage_ticks + inst.spread_ticks)
```

- [ ] **Step 4: Run tests and checks**

Run: `pytest tests/core/test_instrument_calendar.py tests/execution/test_broker.py -v && ruff check . && ruff format --check . && mypy`
Expected: 27 passed, checks clean.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "Add CFD instruments with spread cost

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Minute-file loaders

**Files:**
- Create: `src/lsdtrader/data/minute_files.py`
- Test: `tests/data/test_minute_files.py`

**Interfaces:**
- Consumes: `TickBar`, `Instrument`.
- Produces: `histdata_symbol(path) -> str`, `read_histdata_zip(path, inst) -> list[TickBar]`, `read_dukascopy_csv(path, inst) -> list[TickBar]`, `merge(chunks) -> list[TickBar]`, `load_minute_files(paths, inst) -> tuple[list[TickBar], int]` (bars, duplicates dropped).

- [ ] **Step 1: Write the failing tests**

`tests/data/test_minute_files.py`:

```python
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lsdtrader.core.instrument import get_instrument
from lsdtrader.data.minute_files import (
    histdata_symbol,
    load_minute_files,
    read_dukascopy_csv,
    read_histdata_zip,
)

SPX = get_instrument("SPXUSD")


def histdata_zip(path: Path, rows: list[str], symbol: str = "SPXUSD", year: int = 2025) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(f"DAT_ASCII_{symbol}_M1_{year}.csv", "\n".join(rows) + "\n")
        z.writestr(f"DAT_ASCII_{symbol}_M1_{year}.txt", "status report")
    return path


def test_histdata_timestamps_are_est_without_dst(tmp_path: Path) -> None:
    rows = [
        "20250102 093000;5898.434000;5898.434000;5892.620000;5894.623000;0",
        "20250702 093000;6200.000000;6201.500000;6199.250000;6200.750000;0",
    ]
    bars = read_histdata_zip(histdata_zip(tmp_path / "a.zip", rows), SPX)
    # 09:30 EST is 14:30 UTC, in winter and in summer alike (fixed UTC-5)
    assert bars[0].ts == datetime(2025, 1, 2, 14, 30, tzinfo=UTC)
    assert bars[1].ts == datetime(2025, 7, 2, 14, 30, tzinfo=UTC)
    assert (bars[0].open, bars[0].low) == (5898434, 5892620)


def test_histdata_symbol_from_zip(tmp_path: Path) -> None:
    assert histdata_symbol(histdata_zip(tmp_path / "x.zip", [], "XAUUSD")) == "XAUUSD"


def test_zip_without_histdata_csv_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "other.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("readme.txt", "x")
    with pytest.raises(ValueError):
        histdata_symbol(path)


def test_dukascopy_csv(tmp_path: Path) -> None:
    path = tmp_path / "d.csv"
    path.write_text(
        "Etc/UTC,Open,High,Low,Close,Volume\n"
        "2026-08-03T00:00:00+00:00,7523.242,7523.242,7517.983,7519.739,55440\n",
        encoding="utf-8",
    )
    (bar,) = read_dukascopy_csv(path, SPX)
    assert bar.ts == datetime(2026, 8, 3, tzinfo=UTC)
    assert bar.close == 7519739


def test_dukascopy_wrong_header(tmp_path: Path) -> None:
    path = tmp_path / "d.csv"
    path.write_text("time,open\n", encoding="utf-8")
    with pytest.raises(ValueError):
        read_dukascopy_csv(path, SPX)


def test_merge_sorts_and_counts_duplicates(tmp_path: Path) -> None:
    a = histdata_zip(tmp_path / "a.zip", ["20250102 093100;1;1;1;1;0", "20250102 093000;2;2;2;2;0"])
    b = histdata_zip(tmp_path / "b.zip", ["20250102 093100;3;3;3;3;0"])
    bars, dropped = load_minute_files([a, b], SPX)
    assert [bar.open for bar in bars] == [2000, 1000]
    assert dropped == 1


def test_unsupported_file_type(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        load_minute_files([tmp_path / "x.txt"], SPX)
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/data/test_minute_files.py -v`
Expected: `ModuleNotFoundError: No module named 'lsdtrader.data.minute_files'`.

- [ ] **Step 3: Implement**

`src/lsdtrader/data/minute_files.py`:

```python
"""Loaders for 1-minute bar files: HistData.com ASCII zips and Dukascopy CSV exports.

HistData:  zip containing DAT_ASCII_<SYMBOL>_M1_<YEAR>.csv, rows `YYYYMMDD HHMMSS;O;H;L;C;V`,
           timestamps in EST without daylight saving (fixed UTC-5), bid prices.
Dukascopy: CSV with header `Etc/UTC,Open,High,Low,Close,Volume`, ISO timestamps in UTC.
Both return 1-minute TickBars in UTC. `load_minute_files` merges files, sorts, and drops
repeated timestamps, returning how many it dropped so the data report can show it.
"""

from __future__ import annotations

import csv
import re
import zipfile
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from lsdtrader.core.bar import TickBar
from lsdtrader.core.instrument import Instrument

HISTDATA_TZ = timezone(timedelta(hours=-5))
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
        local = datetime.strptime(stamp, "%Y%m%d %H%M%S").replace(tzinfo=HISTDATA_TZ)
        bars.append(_bar(inst, local.astimezone(UTC), o, h, lo, c))
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
```

- [ ] **Step 4: Run tests and checks**

Run: `pytest tests/data/test_minute_files.py -v && ruff check . && ruff format --check . && mypy`
Expected: 7 passed, checks clean.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "Add HistData and Dukascopy 1-minute loaders

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: 5-minute aggregation and data report

**Files:**
- Create: `src/lsdtrader/data/aggregate.py`, `src/lsdtrader/data/report.py`
- Test: `tests/data/test_aggregate_report.py`

**Interfaces:**
- Produces: `five_minute_start(ts) -> datetime`; `to_five_minute(minutes) -> tuple[list[TickBar], dict[datetime, list[TickBar]]]`; `Gap`, `Jump`, `DataReport` (with `.to_markdown()`), `build_report(instrument, minutes, duplicates_dropped=0) -> DataReport`; constants `GAP_LISTED`, `EXPECTED_BREAK`, `JUMP_FACTOR`.

- [ ] **Step 1: Write the failing tests**

`tests/data/test_aggregate_report.py`:

```python
from datetime import UTC, datetime, timedelta

from lsdtrader.core.bar import TickBar
from lsdtrader.core.instrument import get_instrument
from lsdtrader.data.aggregate import five_minute_start, to_five_minute
from lsdtrader.data.report import build_report

T = datetime(2025, 1, 2, 14, 30, tzinfo=UTC)


def minute(i: int, o: int, h: int, lo: int, c: int) -> TickBar:
    return TickBar(T + timedelta(minutes=i), o, h, lo, c)


def test_five_minute_alignment() -> None:
    assert five_minute_start(datetime(2025, 1, 2, 14, 37, tzinfo=UTC)) == datetime(
        2025, 1, 2, 14, 35, tzinfo=UTC
    )


def test_aggregation_ohlc_and_minute_groups() -> None:
    minutes = [
        minute(0, 10, 12, 9, 11),
        minute(1, 11, 15, 10, 14),
        minute(4, 14, 14, 8, 9),
        minute(5, 9, 10, 7, 8),  # next 5-minute bar, only one minute
    ]
    bars, groups = to_five_minute(minutes)
    assert [(b.ts, b.open, b.high, b.low, b.close) for b in bars] == [
        (T, 10, 15, 8, 9),
        (T + timedelta(minutes=5), 9, 10, 7, 8),
    ]
    assert len(groups[T]) == 3 and len(groups[T + timedelta(minutes=5)]) == 1


def test_report_classifies_gaps_breaks_and_jumps() -> None:
    minutes = [minute(i, 100, 102, 99, 101) for i in range(10)]
    minutes.append(minute(30, 101, 103, 100, 102))  # 20-minute gap -> listed
    minutes.append(minute(120, 102, 104, 101, 103))  # 89-minute pause -> break
    minutes.append(minute(121, 900, 902, 899, 901))  # jump of 797 ticks > 50 x 3
    report = build_report(get_instrument("SPXUSD"), minutes, duplicates_dropped=2)
    assert report.n_minutes == 13 and report.n_breaks == 1
    assert [g.length for g in report.gaps] == [timedelta(minutes=20)]
    assert [j.ticks for j in report.jumps] == [797]
    text = report.to_markdown()
    assert "Duplicate timestamps dropped while loading: 2" in text
    assert "## Largest gaps" in text and "## Price jumps" in text


def test_report_of_nothing() -> None:
    report = build_report(get_instrument("SPXUSD"), [])
    assert report.n_minutes == 0 and report.first is None
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/data/test_aggregate_report.py -v`
Expected: `ModuleNotFoundError: No module named 'lsdtrader.data.aggregate'`.

- [ ] **Step 3: Implement**

`src/lsdtrader/data/aggregate.py`:

```python
"""Build 5-minute bars from 1-minute bars (Design §4.3).

Bars are aligned to multiples of 5 minutes of the clock. A 5-minute bar exists when at least
one minute exists in its window. The minutes of each 5-minute bar are kept for the broker,
which resolves stop/target on them.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from lsdtrader.core.bar import TickBar


def five_minute_start(ts: datetime) -> datetime:
    return ts.replace(minute=ts.minute - ts.minute % 5, second=0, microsecond=0)


def to_five_minute(
    minutes: Sequence[TickBar],
) -> tuple[list[TickBar], dict[datetime, list[TickBar]]]:
    """Aggregate sorted 1-minute bars; returns (5-minute bars, minutes per 5-minute open)."""
    groups: dict[datetime, list[TickBar]] = {}
    for m in minutes:
        groups.setdefault(five_minute_start(m.ts), []).append(m)
    bars = [
        TickBar(
            start,
            group[0].open,
            max(m.high for m in group),
            min(m.low for m in group),
            group[-1].close,
        )
        for start, group in groups.items()
    ]
    return bars, groups
```

`src/lsdtrader/data/report.py`:

```python
"""Data report (Design §4.4): coverage, gaps and price jumps. Reports, never repairs."""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from lsdtrader.core.bar import TickBar
from lsdtrader.core.instrument import Instrument

# Pauses up to this length are ordinary thin trading; longer ones are listed.
GAP_LISTED = timedelta(minutes=15)
# Daily halts and weekends are expected; they are counted separately, not listed as problems.
EXPECTED_BREAK = timedelta(minutes=45)
JUMP_FACTOR = 50  # a bar-to-bar jump this many times the median 1-minute range is listed


@dataclass(frozen=True, slots=True)
class Gap:
    after: datetime
    length: timedelta


@dataclass(frozen=True, slots=True)
class Jump:
    ts: datetime
    ticks: int


@dataclass(frozen=True, slots=True)
class DataReport:
    instrument: str
    first: datetime | None
    last: datetime | None
    n_minutes: int
    n_breaks: int  # pauses >= EXPECTED_BREAK (halts, weekends, holidays)
    gaps: list[Gap]  # GAP_LISTED <= pause < EXPECTED_BREAK
    jumps: list[Jump]
    median_range_ticks: float
    duplicates_dropped: int = 0

    def to_markdown(self) -> str:
        lines = [
            f"# Data report {self.instrument}",
            "",
            f"- Range: {self.first} to {self.last}",
            f"- 1-minute bars: {self.n_minutes}",
            f"- Duplicate timestamps dropped while loading: {self.duplicates_dropped}",
            f"- Breaks of {EXPECTED_BREAK} or more (halts, weekends, holidays): {self.n_breaks}",
            f"- Median 1-minute range: {self.median_range_ticks:.1f} ticks",
            f"- Unexpected gaps ({GAP_LISTED} to {EXPECTED_BREAK}): {len(self.gaps)}",
            f"- Price jumps over {JUMP_FACTOR}x median range: {len(self.jumps)}",
        ]
        if self.gaps:
            lines += ["", "## Largest gaps", "", "| After | Length |", "|---|---|"]
            for g in sorted(self.gaps, key=lambda g: g.length, reverse=True)[:20]:
                lines.append(f"| {g.after} | {g.length} |")
        if self.jumps:
            lines += ["", "## Price jumps", "", "| At | Ticks |", "|---|---|"]
            for j in sorted(self.jumps, key=lambda j: abs(j.ticks), reverse=True)[:20]:
                lines.append(f"| {j.ts} | {j.ticks:+d} |")
        return "\n".join(lines) + "\n"


def build_report(
    instrument: Instrument, minutes: Sequence[TickBar], duplicates_dropped: int = 0
) -> DataReport:
    if not minutes:
        return DataReport(instrument.root, None, None, 0, 0, [], [], 0.0, duplicates_dropped)
    median_range = statistics.median(m.high - m.low for m in minutes) or 1.0
    breaks, gaps, jumps = 0, [], []
    for prev, cur in zip(minutes, minutes[1:], strict=False):
        pause = cur.ts - prev.ts - timedelta(minutes=1)
        if pause >= EXPECTED_BREAK:
            breaks += 1
        elif pause >= GAP_LISTED:
            gaps.append(Gap(prev.ts, pause))
        jump = cur.open - prev.close
        if pause < EXPECTED_BREAK and abs(jump) > JUMP_FACTOR * median_range:
            jumps.append(Jump(cur.ts, jump))
    return DataReport(
        instrument.root,
        minutes[0].ts,
        minutes[-1].ts,
        len(minutes),
        breaks,
        gaps,
        jumps,
        float(median_range),
        duplicates_dropped,
    )
```

- [ ] **Step 4: Run tests and checks**

Run: `pytest tests/data/test_aggregate_report.py -v && ruff check . && ruff format --check . && mypy`
Expected: 4 passed, checks clean.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "Add 5-minute aggregation and data report

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Run notes, CLI for minute files, README

**Files:**
- Modify: `src/lsdtrader/journal/writer.py` (`notes` parameter), `src/lsdtrader/cli.py` (full rewrite below), `README.md`
- Test: `tests/data/test_cli_minutes.py`

**Interfaces:**
- Consumes: loaders, aggregation, report, `run_backtest`, `write_run`.
- Produces: `build_meta(result, data_files, notes=None)`, `write_run(result, out_dir, data_files=(), notes=None)` (notes land in `meta.json["notes"]` and a "Notes" section of `summary.md`); CLI `lsd backtest FILE... [--instrument]`, `lsd data-report FILE... [--instrument] [--out]`; `LoadedData`, `load_data(files, instrument)`.

- [ ] **Step 1: Write the failing tests**

`tests/data/test_cli_minutes.py`:

```python
import json
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from lsdtrader.cli import main

START = datetime(2025, 1, 2, 9, 30)  # EST


def histdata_zip(path: Path, n: int) -> Path:
    rows = [
        f"{START + timedelta(minutes=i):%Y%m%d %H%M%S};5000.000;5000.500;4999.500;5000.250;0"
        for i in range(n)
    ]
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("DAT_ASCII_SPXUSD_M1_2025.csv", "\n".join(rows) + "\n")
    return path


def test_backtest_on_histdata_zip(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    f = histdata_zip(tmp_path / "spx.zip", 60)
    assert main(["backtest", str(f), "--out", str(tmp_path / "runs")]) == 0
    assert "SPXUSD: 12 bars" in capsys.readouterr().out
    (folder,) = (tmp_path / "runs").iterdir()
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    assert meta["notes"]["exit_resolution"] == "1-minute bars"
    assert "exit_resolution: 1-minute bars" in (folder / "summary.md").read_text(encoding="utf-8")


def test_data_report_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    f = histdata_zip(tmp_path / "spx.zip", 30)
    assert main(["data-report", str(f)]) == 0
    assert "1-minute bars: 30" in capsys.readouterr().out
    out = tmp_path / "report.md"
    assert main(["data-report", str(f), "--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8").startswith("# Data report SPXUSD")


def test_dukascopy_needs_instrument(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    f = tmp_path / "d.csv"
    f.write_text(
        "Etc/UTC,Open,High,Low,Close,Volume\n"
        "2026-08-03T00:00:00+00:00,7523.242,7523.242,7517.983,7519.739,55440\n",
        encoding="utf-8",
    )
    with pytest.raises(SystemExit):
        main(["data-report", str(f)])
    assert main(["data-report", str(f), "--instrument", "USA500.IDX/USD"]) == 0
    assert "# Data report SPXUSD" in capsys.readouterr().out
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/data/test_cli_minutes.py -v`
Expected: failures — `lsd backtest` rejects a `.zip` (`KeyError` or JSON decode error) and `data-report` is an invalid choice.

- [ ] **Step 3: Implement**

`src/lsdtrader/journal/writer.py` (full file):

```python
"""Run folder: meta.json, trades.parquet, events.parquet, summary.md (Design §7)."""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

import lsdtrader
from lsdtrader.backtest.runner import RunResult
from lsdtrader.core.calendar import CHICAGO
from lsdtrader.journal.summary import render_markdown, summarize

PRICE_FIELDS = (
    "entry_signal",
    "entry_fill",
    "stop",
    "target",
    "exit_raw",
    "exit_fill",
    "zone_top",
    "zone_bot",
    "liq_level",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return out.stdout.strip()


def trade_rows(result: RunResult) -> list[dict[str, Any]]:
    inst = result.instrument
    rows = []
    for t in result.trades:
        row = {k: v for k, v in asdict(t).items() if k != "features"}
        for k in PRICE_FIELDS:
            row[f"{k}_price"] = float(inst.to_price(row[k]))
        local = t.entry_ts.astimezone(CHICAGO)
        row["entry_time_ct"] = f"{local:%H:%M}"
        row["entry_weekday"] = local.weekday()
        row.update({f"feat_{k}": v for k, v in t.features.items()})
        rows.append(row)
    return rows


def event_rows(result: RunResult) -> list[dict[str, Any]]:
    times = result.bar_times
    return [
        {
            "bar_index": e.bar_index,
            "ts": times[e.bar_index] if 0 <= e.bar_index < len(times) else None,
            "instrument": result.instrument.root,
            "side": e.side,
            "kind": e.kind,
            "detail": json.dumps(e.detail, sort_keys=True, default=str),
        }
        for e in result.events
    ]


def build_meta(
    result: RunResult, data_files: Sequence[Path], notes: Mapping[str, str] | None = None
) -> dict[str, Any]:
    inst = asdict(result.instrument)
    inst["tick_size"] = str(inst["tick_size"])
    return {
        "package_version": lsdtrader.__version__,
        "git_commit": git_commit(),
        "instrument": inst,
        "strategy_config": asdict(result.strategy_config),
        "execution_config": asdict(result.execution_config),
        "data": [{"path": str(p), "sha256": sha256_file(p)} for p in data_files],
        "n_bars": result.n_bars,
        "n_trades": len(result.trades),
        "notes": dict(notes or {}),
    }


def write_run(
    result: RunResult,
    out_dir: Path,
    data_files: Sequence[Path] = (),
    notes: Mapping[str, str] | None = None,
) -> Path:
    """`notes` (e.g. data source, exit resolution) go into meta.json and summary.md."""
    meta = build_meta(result, data_files, notes)
    fingerprint = hashlib.sha256(json.dumps(meta, sort_keys=True, default=str).encode()).hexdigest()
    now = datetime.now(UTC)
    folder = out_dir / f"{now:%Y%m%d-%H%M%S}_{result.instrument.root}_{fingerprint[:8]}"
    folder.mkdir(parents=True, exist_ok=False)
    meta["created_utc"] = now.isoformat()
    meta["fingerprint"] = fingerprint
    (folder / "meta.json").write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")
    pq.write_table(pa.Table.from_pylist(trade_rows(result)), folder / "trades.parquet")
    pq.write_table(pa.Table.from_pylist(event_rows(result)), folder / "events.parquet")
    title = f"Backtest {result.instrument.root}"
    summary = render_markdown(title, summarize(result.trades), result.n_bars, result.events)
    if notes:
        summary += "\n## Notes\n\n" + "".join(f"- {k}: {v}\n" for k, v in notes.items())
    (folder / "summary.md").write_text(summary, encoding="utf-8")
    return folder
```

`src/lsdtrader/cli.py` (full file):

```python
"""Command line.

    lsd backtest FILE... [--instrument ROOT] [--set name=value ...]
    lsd data-report FILE... [--instrument ROOT] [--out report.md]

FILE is a TradingView JSON export (5-minute bars) or one or more 1-minute files
(HistData .zip, Dukascopy .csv), which are merged and aggregated to 5 minutes.
"""

from __future__ import annotations

import argparse
import dataclasses
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from lsdtrader.backtest.runner import run_backtest
from lsdtrader.core.bar import TickBar
from lsdtrader.core.config import StrategyConfig
from lsdtrader.core.instrument import Instrument, get_instrument
from lsdtrader.data.aggregate import to_five_minute
from lsdtrader.data.minute_files import histdata_symbol, load_minute_files
from lsdtrader.data.report import build_report
from lsdtrader.data.tradingview import load_tradingview_json
from lsdtrader.execution.broker import ExecutionConfig
from lsdtrader.journal.summary import summarize
from lsdtrader.journal.writer import write_run


def parse_value(text: str) -> object:
    if text.lower() == "none":
        return None
    for cast in (int, float):
        try:
            return cast(text)
        except ValueError:
            pass
    return text


def parse_overrides(items: Sequence[str]) -> dict[str, object]:
    names = {f.name for f in dataclasses.fields(StrategyConfig)}
    out: dict[str, object] = {}
    for item in items:
        key, sep, value = item.partition("=")
        if not sep or key not in names:
            raise SystemExit(f"--set expects name=value with name in {sorted(names)}; got {item!r}")
        out[key] = parse_value(value)
    return out


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
    root = instrument
    if root is None:
        zips = [f for f in files if f.suffix.lower() == ".zip"]
        if not zips:
            raise SystemExit("--instrument is required for Dukascopy CSV files")
        root = histdata_symbol(zips[0])
    inst = get_instrument(root)
    minute_bars, dropped = load_minute_files(files, inst)
    bars, minutes = to_five_minute(minute_bars)
    return LoadedData(inst, bars, minutes, minute_bars, "1m files aggregated to 5m", dropped)


def cmd_backtest(args: argparse.Namespace) -> int:
    cfg = StrategyConfig(**parse_overrides(args.set))  # type: ignore[arg-type]
    exec_cfg = ExecutionConfig(sizing=args.sizing, risk_usd=args.risk)
    data = load_data(args.files, args.instrument)
    result = run_backtest(data.instrument, data.bars, data.minutes, cfg, exec_cfg)
    notes = {
        "data_source": data.source,
        "exit_resolution": "1-minute bars" if data.minutes else "5-minute bars (stop first)",
    }
    folder = write_run(result, args.out, args.files, notes)
    s = summarize(result.trades)
    print(
        f"{data.instrument.root}: {result.n_bars} bars, {s.n} trades, "
        f"win rate {s.win_rate:.1%}, avg net R {s.avg_net_r:+.3f}, total {s.total_net_r:+.2f}R"
    )
    print(f"run folder: {folder}")
    return 0


def cmd_data_report(args: argparse.Namespace) -> int:
    data = load_data(args.files, args.instrument)
    if not data.minute_bars:
        raise SystemExit("data-report needs 1-minute files (HistData .zip or Dukascopy .csv)")
    report = build_report(data.instrument, data.minute_bars, data.duplicates_dropped)
    text = report.to_markdown()
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"report written to {args.out}")
    else:
        print(text, end="")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lsd", description="LSD strategy engine")
    sub = parser.add_subparsers(dest="command", required=True)

    bt = sub.add_parser("backtest", help="run a backtest")
    bt.add_argument("files", type=Path, nargs="+")
    bt.add_argument("--instrument", help="instrument root, e.g. SPXUSD (default: from the file)")
    bt.add_argument("--set", action="append", default=[], metavar="NAME=VALUE")
    bt.add_argument("--sizing", choices=["research", "realistic"], default="research")
    bt.add_argument("--risk", type=float, default=100.0, help="USD risk per trade (1R)")
    bt.add_argument("--out", type=Path, default=Path("runs"))
    bt.set_defaults(func=cmd_backtest)

    dr = sub.add_parser("data-report", help="gaps and price jumps in 1-minute files")
    dr.add_argument("files", type=Path, nargs="+")
    dr.add_argument("--instrument")
    dr.add_argument("--out", type=Path)
    dr.set_defaults(func=cmd_data_report)

    args = parser.parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
```

`README.md` (full file):

````markdown
# lsd-trader

[![CI](https://github.com/xaverm1/lsd-trader/actions/workflows/ci.yml/badge.svg)](https://github.com/xaverm1/lsd-trader/actions/workflows/ci.yml)

Backtest and (later) live engine for the LSD 5-minute futures strategy.

- Strategy rules: [docs/specs/2026-09-25-lsd-strategy-v1.md](docs/specs/2026-09-25-lsd-strategy-v1.md)
- Engine design: [docs/specs/2026-09-25-engine-backtester-design.md](docs/specs/2026-09-25-engine-backtester-design.md)

## Development

```bash
python -m venv .venv
source .venv/Scripts/activate   # Windows Git Bash; on Linux/macOS: source .venv/bin/activate
python -m pip install -e ".[dev]"
pytest
```

## Data

The engine reads 1-minute bars and builds 5-minute bars from them; the broker resolves stops
and targets on the 1-minute bars.

- **HistData.com** ASCII 1-minute zips (free CFD data: SPX/USD, NSX/USD, XAU/USD, XAG/USD,
  WTI/USD). Timestamps are EST without daylight saving and are converted to UTC.
- **Dukascopy** CSV exports (header `Etc/UTC,...`); pass `--instrument`, e.g. `USA500.IDX/USD`.
- **TradingView** JSON chart exports (5-minute bars only).

Put data files under `data/` (git-ignored). Check them before backtesting:

```bash
lsd data-report data/histdata/HISTDATA_COM_ASCII_SPXUSD_M1_2025.zip
```

CFD costs are modelled as a fixed spread paid once per trade (placeholder values per
instrument in `src/lsdtrader/core/instrument.py`).

## Backtest

```bash
lsd backtest data/histdata/HISTDATA_COM_ASCII_SPXUSD_M1_202*.zip --set rr=3 --out runs
lsd backtest path/to/tradingview_export.json
```

Each run writes `runs/<timestamp>_<instrument>_<fingerprint>/` with `meta.json` (config, data
checksums, git commit), `trades.parquet`, `events.parquet` and a descriptive `summary.md`.
Results are in R, net of commission and slippage. A backtest summary is not a verdict on the
strategy; that needs the out-of-sample methodology of sub-project 3.
````

- [ ] **Step 4: Run the whole suite with coverage and all checks**

Run: `pytest --cov=lsdtrader --cov-fail-under=90 && ruff check . && ruff format --check . && mypy`
Expected: 132 passed (116 + 16 new), coverage ≥ 90 % (prototype: 99 %), checks clean.

- [ ] **Step 5: Smoke runs on real data**

Run: `lsd data-report data/histdata/HISTDATA_COM_ASCII_SPXUSD_M1_2025.zip`
Expected: `# Data report SPXUSD`, about 339,000 1-minute bars, a few dozen duplicates dropped, a handful of listed gaps.

Run: `lsd backtest data/histdata/HISTDATA_COM_ASCII_SPXUSD_M1_2025.zip --out runs`
Expected: a line `SPXUSD: 68242 bars, … trades, …` within about a minute, and a run folder whose `summary.md` ends with the notes `data_source: 1m files aggregated to 5m` and `exit_resolution: 1-minute bars`. Numbers are descriptive only.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Backtest and data-report on 1-minute files; record data source in runs

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
