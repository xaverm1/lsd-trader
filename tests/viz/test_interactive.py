import json
from datetime import UTC, datetime
from pathlib import Path

from lsdtrader.cli import main
from lsdtrader.review.review import load_run
from lsdtrader.viz.interactive import assign_lanes, berlin_epoch, chart_data
from tests.review.test_review import BARS, histdata_zip


def test_berlin_epoch_shifts_to_wall_clock() -> None:
    winter = datetime(2025, 2, 27, 8, 5, tzinfo=UTC)
    summer = datetime(2025, 7, 1, 8, 5, tzinfo=UTC)
    assert berlin_epoch(winter) - int(winter.timestamp()) == 3600
    assert berlin_epoch(summer) - int(summer.timestamp()) == 7200


def test_lanes_never_overlap_and_leave_a_gap_bar() -> None:
    # a gap of one bar is needed for the whitespace point that breaks the line
    assert assign_lanes([(0, 5), (3, 8), (7, 9), (6, 6)]) == [0, 1, 0, 2]


def run_folder(tmp_path: Path) -> Path:
    data = histdata_zip(tmp_path / "spx.zip", BARS)
    assert main(["backtest", str(data), "--out", str(tmp_path / "runs")]) == 0
    (run,) = (tmp_path / "runs").iterdir()
    return run


def test_chart_data_has_candles_trades_and_broken_lines(tmp_path: Path) -> None:
    data = chart_data(load_run(run_folder(tmp_path)))
    assert len(data["candles"]) == len(BARS)
    (trade,) = [t for t in data["trades"] if t["side"] == "long"]
    assert (trade["entry_price"], trade["stop"], trade["target"]) == (0.114, 0.11, 0.13)
    assert (trade["zone_bot"], trade["zone_top"], trade["liq"]) == (0.106, 0.111, 0.113)
    entry_line = data["lanes"][0]["entry_price"]
    assert entry_line[0] == {"time": trade["entry_time"], "value": 0.114}
    times = [p["time"] for lane in data["lanes"] for p in lane["stop"]]
    assert times == sorted(times)


def test_chart_command_writes_self_contained_html(tmp_path: Path) -> None:
    run = run_folder(tmp_path)
    assert main(["chart", str(run)]) == 0
    page = (run / "chart.html").read_text(encoding="utf-8")
    assert "TradingView Lightweight Charts" in page  # library embedded, works offline
    data = json.loads(page.split("const D = ", 1)[1].split(";\n", 1)[0])
    assert data["instrument"] == "SPXUSD" and data["trades"]


def test_segments_end_in_a_transparent_point_so_trades_are_not_joined(tmp_path: Path) -> None:
    # Line series ignore whitespace; a segment takes the colour of its start point, so the
    # last point of every trade must be transparent to hide the link to the next trade.
    from lsdtrader.viz.interactive import TRANSPARENT

    data = chart_data(load_run(run_folder(tmp_path)))
    for lane in data["lanes"]:
        for points in lane.values():
            assert all("value" in p for p in points)
            assert points and points[-1].get("color") == TRANSPARENT


def test_position_lines_are_drawn_at_least_the_minimum_width(tmp_path: Path) -> None:
    from lsdtrader.viz.chart import MIN_POSITION_BARS

    data = chart_data(load_run(run_folder(tmp_path)))
    (trade,) = [t for t in data["trades"] if t["side"] == "long"]
    n = len(data["candles"])
    assert trade["pos_end"] == min(max(trade["exit"], trade["entry"] + MIN_POSITION_BARS), n - 1)
    assert data["lanes"][0]["target"][-1]["time"] == data["candles"][trade["pos_end"]]["time"]


def test_page_has_explicit_light_colours(tmp_path: Path) -> None:
    run = run_folder(tmp_path)
    assert main(["chart", str(run)]) == 0
    page = (run / "chart.html").read_text(encoding="utf-8")
    assert "background:#fff" in page and "color:#1a1a1a" in page
