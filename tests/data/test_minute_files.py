import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lsdtrader.core.instrument import get_instrument
from lsdtrader.data.minute_files import (
    histdata_clock,
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


def test_histdata_clock_is_berlin_time_minus_six_hours(tmp_path: Path) -> None:
    # Review finding (verified on SPXUSD 2020): the daily CFD halt starts 16:14 New York time
    # every day, but the file shows 15:14 in the weeks where US and EU daylight saving differ.
    rows = [
        "20200115 161400;1;1;1;1;0",  # winter: file = UTC-5
        "20200310 151400;1;1;1;1;0",  # US summer, EU winter: file = UTC-5
        "20200331 161400;1;1;1;1;0",  # both summer: file = UTC-4
        "20201028 151400;1;1;1;1;0",  # EU winter again, US still summer: file = UTC-5
    ]
    bars = read_histdata_zip(histdata_zip(tmp_path / "a.zip", rows), SPX)
    assert [b.ts for b in bars] == [
        datetime(2020, 1, 15, 21, 14, tzinfo=UTC),
        datetime(2020, 3, 10, 20, 14, tzinfo=UTC),
        datetime(2020, 3, 31, 20, 14, tzinfo=UTC),
        datetime(2020, 10, 28, 20, 14, tzinfo=UTC),
    ]


def test_histdata_files_before_2019_use_new_york_clock(tmp_path: Path) -> None:
    # Verified on XAUUSD 2009-2025: up to 2018 the daily reopen is stamped 18:00/18:01 in every
    # week, also where US and EU daylight saving differ (file = New York time); from 2019 it is
    # stamped 17:00 in those weeks (file = Berlin - 6 h). Non-farm payrolls (08:30 New York)
    # confirm it: 2018-11-02 at 08:30 in the file, 2019-11-01 at 07:30.
    rows = [
        "20180115 180100;1;1;1;1;0",  # winter: both clocks agree (UTC-5)
        "20180313 180100;1;1;1;1;0",  # US summer, EU winter: New York clock -> UTC-4
        "20180702 180100;1;1;1;1;0",  # both summer: both clocks agree (UTC-4)
        "20181102 083000;1;1;1;1;0",  # EU winter, US still summer -> UTC-4
    ]
    bars = read_histdata_zip(histdata_zip(tmp_path / "a.zip", rows, "XAUUSD", 2018), SPX)
    assert [b.ts for b in bars] == [
        datetime(2018, 1, 15, 23, 1, tzinfo=UTC),
        datetime(2018, 3, 13, 22, 1, tzinfo=UTC),
        datetime(2018, 7, 2, 22, 1, tzinfo=UTC),
        datetime(2018, 11, 2, 12, 30, tzinfo=UTC),
    ]


def test_histdata_clock_by_year() -> None:
    assert histdata_clock(2009) == histdata_clock(2018) == "America/New_York"
    assert histdata_clock(2019) == histdata_clock(2026) == "Europe/Berlin - 6 h"


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


def test_databento_csv_gz(tmp_path: Path) -> None:
    import gzip

    from lsdtrader.data.minute_files import databento_symbol, read_databento_csv

    path = tmp_path / "ES_ohlcv1m_2020.csv.gz"
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        fh.write("ts_event,open,high,low,close,volume,instrument_id\n")
        fh.write("2020-01-02 14:30:00+00:00,3240.25,3241.0,3239.75,3240.5,1234,1\n")
    assert databento_symbol(path) == "ES" and databento_symbol(tmp_path / "x.csv") is None
    (bar,) = read_databento_csv(path, get_instrument("ES"))
    assert bar.ts == datetime(2020, 1, 2, 14, 30, tzinfo=UTC)
    assert (bar.open, bar.high, bar.low, bar.close, bar.volume) == (
        12961,
        12964,
        12959,
        12962,
        1234.0,
    )
