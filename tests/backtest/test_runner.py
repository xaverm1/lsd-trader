from datetime import timedelta
from decimal import Decimal

from lsdtrader.backtest.runner import run_backtest
from lsdtrader.core.bar import TickBar
from lsdtrader.core.config import StrategyConfig
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


def test_trade_records_the_run_up_without_take_profit() -> None:
    # The target 130 (4 R) is hit on bar 18, but price keeps running to 138 (6 R) and then
    # falls to the stop 110. Without a take profit the trade would have ended at -1 R.
    after = make_bars((130, 138, 129, 137), (137, 137, 109, 109), start=19)
    result = run_backtest(INST, FULL_LONG + TO_TARGET + after)
    (t,) = [t for t in result.trades if t.side == "long"]
    assert (t.exit_reason, t.mfe_r) == ("tp", 4.0)
    assert (t.mfe_free_r, t.exit_free_reason, t.exit_free_r) == (6.0, "sl", -1.0)
    assert t.mfe_free_ts == after[0].ts


def test_run_up_without_take_profit_ends_with_the_data() -> None:
    result = run_backtest(INST, FULL_LONG + TO_TARGET)
    (t,) = [t for t in result.trades if t.side == "long"]
    assert (t.mfe_free_r, t.exit_free_reason, t.exit_free_r) == (4.25, "end_of_data", 4.0)


def reclaim_minutes() -> tuple[TickBar, list[TickBar]]:
    """Bar 16 of FULL_LONG as 1-minute bars: dips to 109, closes back above the swept
    liquidity 113 in minute 2 (114), then runs through the target in minute 3."""
    t = FULL_LONG[15].ts + (FULL_LONG[15].ts - FULL_LONG[14].ts)
    mins = [
        TickBar(t, 112, 113, 109, 112),
        TickBar(t + timedelta(minutes=1), 112, 114, 112, 114),
        TickBar(t + timedelta(minutes=2), 114, 140, 114, 139),
    ]
    return TickBar(t, 112, 140, 109, 139), mins


def test_reclaim_entry_on_the_first_minute_back_above_the_liquidity() -> None:
    bar, mins = reclaim_minutes()
    minutes = {bar.ts: mins}
    cfg = StrategyConfig(entry_mode="reclaim_1m")
    result = run_backtest(INST, FULL_LONG[:16] + [bar], minutes, cfg)
    (t,) = [t for t in result.trades if t.side == "long"]
    # entry 114 at the close of minute 2, stop = lowest low since the sweep (109),
    # target 114 + 4 x 5 = 134, reached in minute 3 of the same bar
    assert (t.entry_signal, t.stop, t.target, t.entry_ts) == (114, 109, 134, mins[1].ts)
    assert (t.exit_reason, t.exit_ts) == ("tp", mins[2].ts)


def test_reclaim_needs_the_tap_bar_to_have_closed() -> None:
    # Without a bar after the tap bar there is no minute to reclaim on: no trade.
    cfg = StrategyConfig(entry_mode="reclaim_1m")
    result = run_backtest(INST, FULL_LONG[:16], None, cfg)
    assert [t for t in result.trades if t.side == "long"] == []


def test_sweep_tap_and_cisd_entry_inside_one_bar() -> None:
    # Bar 15 of FULL_LONG as minutes: after a bullish minute, a bearish run from 116 sweeps P'
    # 113 and taps the zone top 111 (low 110). Minute 3 closes above P' (114) but not above the
    # CISD level (116, the open of the bearish run): no entry. Minute 4 closes at 117: entry.
    t = FULL_LONG[15].ts
    mins = [
        TickBar(t, 115, 117, 114, 116),  # bullish: ends the bearish run of bar 14
        TickBar(t + timedelta(minutes=1), 116, 116, 112, 112),  # run opens at 116, sweep of 113
        TickBar(t + timedelta(minutes=2), 112, 112, 110, 110),  # tap of 111, low 110
        TickBar(t + timedelta(minutes=3), 110, 114, 110, 114),  # above P', below CISD
        TickBar(t + timedelta(minutes=4), 114, 117, 113, 117),  # CISD -> entry
    ]
    bar = TickBar(t, 115, 117, 110, 117)
    cfg = StrategyConfig(entry_mode="sweep_1m_cisd")
    result = run_backtest(INST, FULL_LONG[:15] + [bar], {t: mins}, cfg)
    (tr,) = [x for x in result.trades if x.side == "long"]
    assert (tr.entry_signal, tr.stop, tr.entry_ts) == (117, 110, mins[4].ts)
    assert (tr.sweep_idx, tr.tap_idx) == (15, 15)


def absorption_bar() -> tuple[TickBar, list[TickBar]]:
    # Bar 15 of FULL_LONG as minutes with volume: sweep of P' 113, tap of the zone top 111 with
    # a deep wick to 107, then an absorption minute (volume 100, long lower wick, low 108,
    # high 112) and a minute closing above its high (113).
    t = FULL_LONG[15].ts
    mins = [
        TickBar(t, 115, 117, 114, 116, 10),
        TickBar(t + timedelta(minutes=1), 116, 116, 112, 112, 10),  # sweep of 113
        TickBar(t + timedelta(minutes=2), 112, 112, 107, 109, 10),  # tap, deepest wick 107
        TickBar(t + timedelta(minutes=3), 111, 112, 108, 111, 100),  # absorption
        TickBar(t + timedelta(minutes=4), 111, 114, 111, 113, 10),  # close above 112 -> entry
    ]
    return TickBar(t, 115, 117, 107, 113, 140), mins


def test_absorption_entry_with_stop_at_the_deepest_wick() -> None:
    bar, mins = absorption_bar()
    cfg = StrategyConfig(entry_mode="absorption_1m")
    result = run_backtest(INST, FULL_LONG[:15] + [bar], {bar.ts: mins}, cfg)
    (tr,) = [x for x in result.trades if x.side == "long"]
    assert (tr.entry_signal, tr.stop, tr.entry_ts) == (113, 107, mins[4].ts)


def test_absorption_entry_with_stop_at_the_absorption_candle() -> None:
    bar, mins = absorption_bar()
    cfg = StrategyConfig(entry_mode="absorption_1m", stop_ref="absorption")
    result = run_backtest(INST, FULL_LONG[:15] + [bar], {bar.ts: mins}, cfg)
    (tr,) = [x for x in result.trades if x.side == "long"]
    assert (tr.entry_signal, tr.stop) == (113, 108)


def test_no_absorption_no_entry() -> None:
    bar, mins = absorption_bar()
    flat = [TickBar(m.ts, m.open, m.high, m.low, m.close, 0) for m in mins]  # no volume at all
    cfg = StrategyConfig(entry_mode="absorption_1m")
    result = run_backtest(INST, FULL_LONG[:15] + [bar], {bar.ts: flat}, cfg)
    assert [x for x in result.trades if x.side == "long"] == []


def test_absorption_zone_dies_on_a_minute_wick_below_it() -> None:
    # same minutes, but the tap wicks to 105, below the zone bottom 106
    bar, mins = absorption_bar()
    m = mins[2]
    mins[2] = TickBar(m.ts, m.open, m.high, 105, m.close, m.volume)
    bar = TickBar(bar.ts, bar.open, bar.high, 105, bar.close, bar.volume)
    kill = StrategyConfig(entry_mode="absorption_1m", zone_kill="wick_beyond")
    result = run_backtest(INST, FULL_LONG[:15] + [bar], {bar.ts: mins}, kill)
    assert [x for x in result.trades if x.side == "long"] == []
    default = StrategyConfig(entry_mode="absorption_1m")  # close_inside kills wicks too
    assert run_backtest(INST, FULL_LONG[:15] + [bar], {bar.ts: mins}, default).trades == []
    keep = StrategyConfig(entry_mode="absorption_1m", zone_kill="close_beyond")
    result = run_backtest(INST, FULL_LONG[:15] + [bar], {bar.ts: mins}, keep)
    assert len([x for x in result.trades if x.side == "long"]) == 1


def test_absorption_window_from_sweep_to_tap_in_minutes() -> None:
    bar, mins = absorption_bar()  # sweep in minute 1, tap in minute 2
    data = FULL_LONG[:15] + [bar]
    late = StrategyConfig(entry_mode="absorption_1m", max_min_sweep_to_tap=0)
    assert run_backtest(INST, data, {bar.ts: mins}, late).trades == []
    ok = StrategyConfig(entry_mode="absorption_1m", max_min_sweep_to_tap=1)
    (tr,) = run_backtest(INST, data, {bar.ts: mins}, ok).trades
    assert tr.features["min_sweep_to_tap"] == 1
