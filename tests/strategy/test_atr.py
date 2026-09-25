from lsdtrader.strategy.atr import Atr
from tests.helpers import make_bars


def test_wilder_atr() -> None:
    atr = Atr(3)
    bars = make_bars((10, 12, 9, 11), (11, 13, 10, 12), (12, 15, 12, 14), (14, 14, 8, 9))
    assert [atr.update(b) for b in bars] == [None, None, 3.0, 4.0]
