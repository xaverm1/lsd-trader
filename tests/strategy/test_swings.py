from lsdtrader.strategy.swings import Swing, confirmed_swing_low, is_swing_low
from tests.helpers import bars_from_lows


def test_simple_swing_low_confirmed_one_bar_later() -> None:
    bars = bars_from_lows(5, 3, 5)
    assert confirmed_swing_low(bars[:2], 1) is None
    assert confirmed_swing_low(bars, 1) == Swing(1, 3)


def test_equal_lows_rightmost_bar_is_the_swing() -> None:
    # Scenario 1
    bars = bars_from_lows(5, 3, 3, 5)
    assert [c for c in range(len(bars)) if is_swing_low(bars, c, 1)] == [2]


def test_right_side_must_be_strictly_higher() -> None:
    assert confirmed_swing_low(bars_from_lows(5, 3, 3), 1) is None


def test_pivot_length_two() -> None:
    bars = bars_from_lows(6, 5, 3, 4, 5)
    assert confirmed_swing_low(bars, 2) == Swing(2, 3)
    assert not is_swing_low(bars_from_lows(6, 5, 3, 2, 5), 2, 2)


def test_not_enough_bars() -> None:
    assert confirmed_swing_low(bars_from_lows(3), 1) is None
