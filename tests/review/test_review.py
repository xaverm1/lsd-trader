import json
import zipfile
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from lsdtrader.cli import main
from lsdtrader.core.bar import TickBar
from lsdtrader.core.instrument import get_instrument
from lsdtrader.review.inspect_at import inspect_at
from lsdtrader.review.review import (
    MAX_BARS,
    Rejection,
    _window,
    build_review,
    near_zone,
    rejections,
)
from tests.helpers import FULL_LONG, make_bars

SPX = get_instrument("SPXUSD")
BARS = FULL_LONG + make_bars((114, 120, 113, 119), (119, 131, 118, 130), start=17)


def histdata_zip(path: Path, bars: list[TickBar]) -> Path:
    """One HistData minute row per bar, so aggregation reproduces the bars exactly."""

    def price(ticks: int) -> Decimal:
        return SPX.to_price(ticks)

    rows = [
        # FULL_LONG is in January: file clock = UTC - 5 h
        f"{b.ts - timedelta(hours=5):%Y%m%d %H%M%S};{price(b.open)};{price(b.high)};"
        f"{price(b.low)};{price(b.close)};0"
        for b in bars
    ]
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("DAT_ASCII_SPXUSD_M1_2024.csv", "\n".join(rows) + "\n")
    return path


def test_short_window_is_shown_whole() -> None:
    assert _window(900, 950, 1000) == (900, 1000)


def event(bar: int, side: str, kind: str, **detail: object) -> dict[str, object]:
    return {"bar_index": bar, "side": side, "kind": kind, "detail": json.dumps(detail)}


START = {"zone_top": 111, "zone_bot": 106, "zone_o_idx": 6, "liq_idx": 11, "liq_price": 113}


def test_rejections_pair_start_and_end_events() -> None:
    events = [
        event(15, "long", "setup_started", setup_id=3, **START),
        event(18, "long", "no_tap", setup_id=3),
        event(18, "short", "no_tap", setup_id=3),  # other side, never started
    ]
    (r,) = rejections(events)
    assert (r.side, r.setup_id, r.kind, r.end_idx, r.start["sweep_idx"]) == (
        "long",
        3,
        "no_tap",
        18,
        15,
    )


def test_near_zone_filter() -> None:
    near = Rejection("long", 1, "no_tap", 20, dict(START, sweep_idx=15))
    far = Rejection("long", 2, "no_tap", 20, dict(START, liq_price=111 + 16, sweep_idx=15))
    assert near_zone(near) and not near_zone(far)  # height 5 -> max distance 15
    assert near_zone(Rejection("long", 3, "no_entry", 20, far.start))
    short = Rejection("short", 4, "no_tap", 20, dict(START, liq_price=106 - 10, sweep_idx=15))
    assert near_zone(short)


def test_inspect_at_shows_the_zone_and_the_entry() -> None:
    spec, lines = inspect_at(BARS, BARS[16].ts, before=16)
    assert any(b.top == 111 and b.bot == 106 for b in spec.boxes)
    assert any(" entry " in line for line in lines)
    assert spec.first == 0 and spec.last == 18


def test_inspect_at_before_data_is_an_error() -> None:
    with pytest.raises(ValueError):
        inspect_at(BARS, BARS[0].ts - timedelta(minutes=5))


def test_backtest_review_and_inspect_commands(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = histdata_zip(tmp_path / "spx.zip", BARS)
    assert main(["backtest", str(data), "--out", str(tmp_path / "runs")]) == 0
    (run,) = (tmp_path / "runs").iterdir()
    index = build_review(run, n=5, seed=1)
    html = index.read_text(encoding="utf-8")
    assert "trade_01.png" in html and (index.parent / "trade_01.png").exists()
    assert main(["review", str(run), "--n", "5", "--seed", "2"]) == 0
    out = tmp_path / "at.png"
    at = f"{BARS[16].ts.astimezone(ZoneInfo('Europe/Berlin')):%Y-%m-%d %H:%M}"  # Berlin time
    assert main(["inspect-at", str(data), "--at", at, "--out", str(out)]) == 0
    assert out.exists() and " entry " in out.with_suffix(".txt").read_text(encoding="utf-8")
    assert "(bar 16)" in capsys.readouterr().out  # --at is Berlin time


def test_window_keeps_the_setup_and_clips_the_aftermath() -> None:
    # Review finding: the cap kept the last bars and cut off zone origin and P'.
    assert _window(980, 1060, 1520) == (980, 980 + MAX_BARS)
    # a very old zone: the setup (liquidity to entry) must stay in view
    first, last = _window(-20, 2830, 2840)
    assert last - first == MAX_BARS and first <= 2780 and last >= 2830


def test_review_refuses_changed_data(tmp_path: Path) -> None:
    data = histdata_zip(tmp_path / "spx.zip", BARS)
    assert main(["backtest", str(data), "--out", str(tmp_path / "runs")]) == 0
    (run,) = (tmp_path / "runs").iterdir()
    histdata_zip(data, BARS[:-1])  # same file name, different content
    with pytest.raises(SystemExit):
        build_review(run)


def trade_row(bars: list[TickBar], side: str) -> dict[str, object]:
    s = 1 if side == "long" else -1
    return {
        "side": side,
        "setup_id": f"{side}-0",
        "entry_bar": 16,
        "zone_o_idx": 6,
        "liq_idx": 11,
        "sweep_idx": 15,
        "tap_idx": 15,
        "zone_top": 111 if s == 1 else -106,
        "zone_bot": 106 if s == 1 else -111,
        "liq_level": s * 113,
        "entry_signal": s * 114,
        "stop": s * 110,
        "target": s * 130,
        "exit_raw": s * 130,
        "exit_reason": "tp",
        "exit_ts": bars[18].ts,
        "entry_ts": bars[16].ts,
        "net_r": 3.9,
        "gross_r": 4.0,
        "cost_r": 0.1,
        "feat_zone_kind": "accuracy",
        "risk_ticks": 4,
    }


def test_trade_chart_marks_the_wicks_and_shows_the_position() -> None:
    from lsdtrader.review.review import trade_spec

    for bars, side, wick in [(BARS, "long", 110), ([b.mirrored() for b in BARS], "short", -110)]:
        times = [b.ts for b in bars]
        spec = trade_spec(trade_row(bars, side), times, SPX, bars)
        assert spec.position is not None and spec.position.target == (
            130 if side == "long" else -130
        )
        marks = {m.label: m for m in spec.markers}
        assert set(marks) == {"sweep", "tap", "entry", "exit (tp)"}
        assert marks["sweep"].price == wick  # at the wick, not at the liquidity level
        edge = 111 if side == "long" else -111  # zone top for a long, zone bottom for a short
        assert marks["tap"].price == edge  # at the touched zone edge, so it never hides the sweep
        assert any("RR 4.0" in line for line in spec.info)
