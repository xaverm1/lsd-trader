from lsdtrader.core.bar import TickBar
from lsdtrader.strategy.context import LevelBook, TrendTracker, hh_hl, is_swing_high
from tests.helpers import make_bars


def bars_hl(*hl: tuple[int, int]) -> list[TickBar]:
    """Bars from (high, low); close in the middle."""
    return make_bars(*((lo, h, lo, (h + lo) // 2) for h, lo in hl))


def feed(tracker: TrendTracker, bars: list[TickBar]) -> list[int]:
    return [tracker.update(bars[: i + 1]) for i in range(len(bars))]


def test_swing_high() -> None:
    bars = bars_hl((10, 5), (12, 6), (11, 5))
    assert is_swing_high(bars, 1, 1) and not is_swing_high(bars, 0, 1)


def test_trend_turns_up_on_a_close_above_the_last_swing_high() -> None:
    bars = bars_hl((10, 5), (12, 6), (11, 5), (11, 4))
    bars += make_bars((11, 14, 11, 13), start=4)  # close 13 > swing high 12
    assert feed(TrendTracker(1), bars) == [0, 0, 0, 0, 1]


def test_trend_turns_down_on_a_close_below_the_last_swing_low() -> None:
    bars = bars_hl((10, 6), (9, 4), (10, 5), (10, 6))
    bars += make_bars((6, 6, 2, 3), start=4)  # close 3 < swing low 4
    assert feed(TrendTracker(1), bars) == [0, 0, 0, 0, -1]


def test_hh_hl() -> None:
    up = bars_hl((10, 5), (11, 6), (12, 7), (13, 8))
    assert hh_hl(up, 2) == 1
    assert hh_hl(list(reversed(up)), 2) == -1
    assert hh_hl(up[:3], 2) == 0  # not enough bars


def test_level_book_keeps_untouched_swing_highs() -> None:
    bars = bars_hl((10, 5), (20, 6), (11, 5), (15, 5), (12, 5))
    book = LevelBook(1)
    for i in range(len(bars)):
        book.update(bars[: i + 1])
    assert book.nearest_above(12) == 15  # swing highs 20 and 15, nearest first
    bars += make_bars((12, 16, 12, 15), start=5)  # trades through 15
    book.update(bars)
    assert book.nearest_above(12) == 20
