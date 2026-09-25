import json
from pathlib import Path

import pytest

from lsdtrader.cli import main, parse_overrides
from lsdtrader.data.tradingview import load_tradingview_json

MES_SYM = {"name": "MES1!", "minmov": 25, "pricescale": 100, "pointvalue": 5, "root": "MES"}


def write_export(path: Path, sym: dict[str, object], bars: list[list[float]]) -> Path:
    inner = json.dumps({"sym": sym, "bars": bars})
    path.write_text(json.dumps({"success": True, "result": inner}), encoding="utf-8")
    return path


def test_loads_known_futures_in_ticks(tmp_path: Path) -> None:
    f = write_export(
        tmp_path / "mes.json",
        MES_SYM,
        [
            [1785708000, 7618, 7626.5, 7613.75, 7620],
            [1785708300, 7620.5, 7622.25, 7617.75, 7621.75],
        ],
    )
    inst, bars = load_tradingview_json(f)
    assert inst.root == "MES" and inst.tick_value == 1.25
    assert (bars[0].open, bars[0].high, bars[0].low) == (30472, 30506, 30455)
    assert bars[1].ts.timestamp() == 1785708300


def test_unknown_symbol_builds_its_own_spec(tmp_path: Path) -> None:
    sym = {"name": "NAS100", "minmov": 1, "pricescale": 10, "pointvalue": 1}
    inst, bars = load_tradingview_json(
        write_export(tmp_path / "n.json", sym, [[0, 1.1, 1.2, 1.0, 1.1]])
    )
    assert inst.root == "NAS100" and inst.commission_per_side == 0.0
    assert bars[0].high == 12


def test_tick_mismatch_is_rejected(tmp_path: Path) -> None:
    bad = dict(MES_SYM, minmov=1)
    with pytest.raises(ValueError):
        load_tradingview_json(write_export(tmp_path / "bad.json", bad, []))


def test_cli_backtest_writes_run_folder(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rows = [[1785708000 + 300 * i, 7618, 7619, 7617, 7618.25] for i in range(30)]
    f = write_export(tmp_path / "mes.json", MES_SYM, rows)
    assert main(["backtest", str(f), "--out", str(tmp_path / "runs"), "--set", "rr=3"]) == 0
    assert "MES: 30 bars" in capsys.readouterr().out
    (folder,) = (tmp_path / "runs").iterdir()
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    assert meta["strategy_config"]["rr"] == 3


def test_parse_overrides() -> None:
    assert parse_overrides(["rr=3", "bos_max_bars=none", "zone_mode=normal"]) == {
        "rr": 3,
        "bos_max_bars": None,
        "zone_mode": "normal",
    }
    with pytest.raises(SystemExit):
        parse_overrides(["nope=1"])
