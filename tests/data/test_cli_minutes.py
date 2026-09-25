import json
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from lsdtrader.cli import main

START = datetime(2025, 1, 2, 9, 30)  # HistData clock (Berlin time - 6 h)


def histdata_zip(path: Path, n: int, symbol: str = "SPXUSD") -> Path:
    rows = [
        f"{START + timedelta(minutes=i):%Y%m%d %H%M%S};5000.000;5000.500;4999.500;5000.250;0"
        for i in range(n)
    ]
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(f"DAT_ASCII_{symbol}_M1_2025.csv", "\n".join(rows) + "\n")
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


def test_files_of_different_symbols_are_refused(tmp_path: Path) -> None:
    # Review finding: mixing instruments silently dropped one of them as "duplicates".
    spx = histdata_zip(tmp_path / "spx.zip", 5)
    nsx = histdata_zip(tmp_path / "nsx.zip", 5, "NSXUSD")
    with pytest.raises(SystemExit):
        main(["data-report", str(spx), str(nsx)])


def test_instrument_must_match_histdata_symbol(tmp_path: Path) -> None:
    spx = histdata_zip(tmp_path / "spx.zip", 5)
    with pytest.raises(SystemExit):
        main(["data-report", str(spx), "--instrument", "XAUUSD"])
    assert main(["data-report", str(spx), "--instrument", "USA500.IDX/USD"]) == 0
