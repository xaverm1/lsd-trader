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
