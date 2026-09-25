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
