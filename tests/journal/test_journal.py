import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from lsdtrader.backtest.runner import run_backtest
from lsdtrader.core.instrument import Instrument
from lsdtrader.execution.broker import Trade
from lsdtrader.journal.summary import render_markdown, summarize
from lsdtrader.journal.writer import write_run
from tests.helpers import FULL_LONG, make_bars

INST = Instrument("TEST", Decimal("0.25"), tick_value=10.0, commission_per_side=1.0)
T = datetime(2024, 1, 8, 15, 0, tzinfo=UTC)
BASE = Trade(
    "TEST",
    "long",
    "s",
    "z",
    T,
    T,
    100,
    101,
    90,
    140,
    140,
    140,
    "tp",
    1.0,
    10,
    4.0,
    3.88,
    0.12,
    4.0,
    0.0,
    16,
    111,
    106,
    6,
    11,
    113,
    15,
    15,
)


def trade(net_r: float, minute: int) -> Trade:
    return replace(BASE, net_r=net_r, exit_ts=T + timedelta(minutes=minute))


def test_summary_statistics() -> None:
    trades = [trade(3.9, 1), trade(-1.2, 2), trade(-1.2, 3), trade(-1.2, 4), trade(3.9, 5)]
    s = summarize(trades)
    assert (s.n, s.wins, s.longest_losing_streak) == (5, 2, 3)
    assert s.win_rate == pytest.approx(0.4)
    assert s.total_net_r == pytest.approx(4.2)


def test_summary_of_nothing() -> None:
    s = summarize([])
    assert (s.n, s.win_rate, s.avg_net_r) == (0, 0.0, 0.0)
    assert "Trades (N) | 0" in render_markdown("x", s, 0, [])


def test_write_run_creates_a_complete_folder(tmp_path: Path) -> None:
    data = tmp_path / "bars.json"
    data.write_text("{}", encoding="utf-8")
    bars = FULL_LONG + make_bars((114, 120, 113, 119), (119, 131, 118, 130), start=17)
    folder = write_run(run_backtest(INST, bars), tmp_path / "runs", [data])
    assert sorted(p.name for p in folder.iterdir()) == [
        "events.parquet",
        "meta.json",
        "summary.md",
        "trades.parquet",
    ]
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    assert meta["strategy_config"]["rr"] == 4.0
    assert meta["instrument"]["tick_size"] == "0.25"
    assert len(meta["data"][0]["sha256"]) == 64
    trades = pq.read_table(folder / "trades.parquet").to_pylist()
    (long_trade,) = [t for t in trades if t["side"] == "long"]
    assert long_trade["exit_fill_price"] == 32.5  # 130 ticks * 0.25
    assert long_trade["feat_zone_kind"] == "accuracy"
    events = pq.read_table(folder / "events.parquet").to_pylist()
    assert any(e["kind"] == "entry" for e in events)


def test_same_input_same_journal_content(tmp_path: Path) -> None:
    bars = FULL_LONG + make_bars((114, 120, 113, 119), (119, 131, 118, 130), start=17)
    a = write_run(run_backtest(INST, bars), tmp_path / "a")
    b = write_run(run_backtest(INST, bars), tmp_path / "b")
    for name in ("trades.parquet", "events.parquet"):
        assert pq.read_table(a / name).equals(pq.read_table(b / name))
    fa = json.loads((a / "meta.json").read_text(encoding="utf-8"))["fingerprint"]
    fb = json.loads((b / "meta.json").read_text(encoding="utf-8"))["fingerprint"]
    assert fa == fb


def test_journal_rows_carry_times_instrument_and_geometry(tmp_path: Path) -> None:
    bars = FULL_LONG + make_bars((114, 120, 113, 119), (119, 131, 118, 130), start=17)
    folder = write_run(run_backtest(INST, bars), tmp_path / "runs")
    (t,) = [r for r in pq.read_table(folder / "trades.parquet").to_pylist() if r["side"] == "long"]
    assert t["zone_top_price"] == 27.75 and t["liq_level_price"] == 28.25
    assert t["entry_weekday"] == 1 and t["entry_time_ct"] == "09:50"  # Tue 2024-01-02, 15:50 UTC
    e = pq.read_table(folder / "events.parquet").to_pylist()[0]
    assert e["instrument"] == "TEST" and e["ts"] is not None
