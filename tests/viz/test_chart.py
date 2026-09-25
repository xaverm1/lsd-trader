from pathlib import Path

from lsdtrader.core.instrument import get_instrument
from lsdtrader.viz.chart import Box, ChartSpec, Level, Marker, render
from tests.helpers import FULL_LONG

SPX = get_instrument("SPXUSD")


def test_render_writes_png(tmp_path: Path) -> None:
    spec = ChartSpec(
        first=0,
        last=16,
        title="t",
        boxes=[Box(6, 16, 111, 106, "#534AB7", "zone")],
        levels=[Level(11, 15, 113, "#BA7517", "P'", ":")],
        markers=[Marker(16, 114, "entry")],
        notes=["note"],
    )
    out = render(spec, FULL_LONG, SPX, tmp_path / "c.png")
    assert out.read_bytes()[:4] == b"\x89PNG"


def test_time_labels_are_berlin_time() -> None:
    from datetime import UTC, datetime

    from lsdtrader.viz.chart import berlin_label

    assert berlin_label(datetime(2025, 2, 27, 8, 5, tzinfo=UTC)) == "02-27 09:05"  # CET
    assert berlin_label(datetime(2025, 7, 1, 8, 5, tzinfo=UTC)) == "07-01 10:05"  # CEST


def test_position_box_is_wide_enough_to_read() -> None:
    from lsdtrader.viz.chart import MIN_POSITION_BARS, position_extent

    assert position_extent(10, 11) == (10, 10 + MIN_POSITION_BARS)
    assert position_extent(10, 60) == (10, 60)


def test_render_position_legend_and_info(tmp_path: Path) -> None:
    from lsdtrader.viz.chart import Position

    spec = ChartSpec(
        first=0,
        last=18,
        title="t",
        position=Position(16, 18, 114, 110, 130),
        markers=[Marker(15, 110, "sweep", shape="^"), Marker(16, 114, "entry", shape=">")],
        info=["LONG", "Entry 0.114"],
        vline=16,
    )
    out = render(spec, FULL_LONG, SPX, tmp_path / "p.png")
    assert out.read_bytes()[:4] == b"\x89PNG"


def test_markers_on_the_same_bar_are_spread_apart() -> None:
    from lsdtrader.viz.chart import marker_offsets

    marks = [Marker(15, 110, "sweep"), Marker(15, 111, "tap"), Marker(16, 114, "entry")]
    assert marker_offsets(marks) == [-0.35, 0.35, 0.0]
