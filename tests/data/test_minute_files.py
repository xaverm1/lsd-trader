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
