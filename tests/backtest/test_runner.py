from decimal import Decimal

from lsdtrader.backtest.runner import run_backtest
from lsdtrader.core.instrument import Instrument
from tests.helpers import FULL_LONG, make_bars

INST = Instrument("TEST", Decimal("0.25"), tick_value=10.0, commission_per_side=1.0)

# FULL_LONG enters long at 114 (stop 110, target 130) on bar 16; these bars run to the target.
TO_TARGET = make_bars((114, 120, 113, 119), (119, 131, 118, 130), start=17)


def test_full_long_trade_reaches_target() -> None:
    result = run_backtest(INST, FULL_LONG + TO_TARGET)
    (t,) = [t for t in result.trades if t.side == "long"]
    assert (t.exit_reason, t.entry_fill, t.exit_fill) == ("tp", 115, 130)
    assert t.gross_r == 4.0
    assert result.n_bars == 19
    assert any(e.side == "broker" and e.kind == "order_filled" for e in result.events)


def test_open_position_closed_at_end_of_data() -> None:
    result = run_backtest(INST, FULL_LONG + TO_TARGET[:1])
    (t,) = [t for t in result.trades if t.side == "long"]
    assert t.exit_reason == "end_of_data"


def test_minute_bars_are_used_when_given() -> None:
    # The 5-minute bar 18 touches both 131 and 109; its minutes show the target first.
    five = make_bars((119, 131, 109, 110), start=18)
    minutes = {five[0].ts: make_bars((119, 131, 118, 130), (130, 130, 109, 110), start=18)}
    bars = FULL_LONG + TO_TARGET[:1] + five
    with_minutes = run_backtest(INST, bars, minutes)
    without = run_backtest(INST, bars)
    assert [t.exit_reason for t in with_minutes.trades if t.side == "long"] == ["tp"]
    assert [t.exit_reason for t in without.trades if t.side == "long"] == ["sl"]


def test_empty_input() -> None:
    result = run_backtest(INST, [])
    assert result.trades == [] and result.n_bars == 0


def test_incomplete_minutes_fall_back_to_the_five_minute_bar() -> None:
    # Review finding: minutes that do not reach the 5-minute low must not hide a stop.
    five = make_bars((114, 116, 105, 108), start=17)  # low 105 hits the stop at 110
    minutes = {five[0].ts: make_bars((114, 116, 112, 115), start=17)}  # low only 112
    result = run_backtest(INST, FULL_LONG + five, minutes)
    (t,) = [t for t in result.trades if t.side == "long"]
    assert t.exit_reason == "sl"
    assert any(e.kind == "minutes_incomplete" for e in result.events)


def test_long_gap_in_bars_is_treated_as_a_break() -> None:
    # Holiday early close: next bar starts hours later -> flat on the last bar before the gap.
    from datetime import timedelta

    later = make_bars((114, 118, 113, 117), start=17)
    gap = make_bars((117, 119, 116, 118), start=17 + 36)  # 3 hours later
    result = run_backtest(INST, FULL_LONG + later + gap)
    (t,) = [t for t in result.trades if t.side == "long"]
    assert (t.exit_reason, t.exit_ts) == ("flat_break", later[0].ts)
    assert gap[0].ts - later[0].ts == timedelta(hours=3)


def test_trade_records_setup_geometry_and_times() -> None:
    result = run_backtest(INST, FULL_LONG + TO_TARGET)
    (t,) = [t for t in result.trades if t.side == "long"]
    assert (t.zone_top, t.zone_bot, t.liq_level) == (111, 106, 113)
    assert (t.sweep_ts, t.tap_ts) == (FULL_LONG[15].ts, FULL_LONG[15].ts)
    assert result.bar_times[16] == FULL_LONG[16].ts
