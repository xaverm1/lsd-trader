import pytest

from lsdtrader.core.bar import TickBar
from lsdtrader.core.config import StrategyConfig
from lsdtrader.strategy.lsd import LsdStrategy, Signal
from tests.helpers import FULL_LONG, make_bars


def run(bars: list[TickBar], cfg: StrategyConfig | None = None) -> list[Signal]:
    strat = LsdStrategy(cfg)
    return [s for bar in bars for s in strat.on_bar(bar)]


def test_full_long_trade() -> None:
    # Scenario 14
    (sig,) = [s for s in run(FULL_LONG) if s.side == "long"]
    assert (sig.bar_index, sig.entry, sig.stop, sig.target) == (16, 114, 110, 130)
    assert (sig.zone_top, sig.zone_bot, sig.zone_o_idx) == (111, 106, 6)
    assert (sig.liq_idx, sig.liq_price, sig.sweep_idx, sig.tap_idx) == (11, 113, 15, 15)
    assert sig.features["zone_kind"] == "accuracy"
    assert sig.features["stop_ticks"] == 4


def test_mirrored_bars_give_the_mirrored_short() -> None:
    # Scenario 17
    shorts = [s for s in run([b.mirrored() for b in FULL_LONG]) if s.side == "short"]
    (sig,) = shorts
    assert (sig.bar_index, sig.entry, sig.stop, sig.target) == (16, -114, -110, -130)
    assert (sig.zone_top, sig.zone_bot, sig.liq_price) == (-106, -111, -113)


def test_no_liquidity_no_setup() -> None:
    # Scenario 11: zone left, price returns and bounces, but no P′ was swept.
    bars = FULL_LONG[:10] + make_bars((120, 120, 110, 112), (112, 118, 111, 117), start=10)
    assert [s for s in run(bars) if s.side == "long"] == []


def test_events_explain_the_trade() -> None:
    strat = LsdStrategy()
    for bar in FULL_LONG:
        strat.on_bar(bar)
    kinds = [e.kind for e in strat.drain_events() if e.side == "long"]
    for kind in ("bos", "zone_created", "zone_left", "setup_started", "tap", "entry"):
        assert kind in kinds
    assert strat.drain_events() == []


def test_bars_must_arrive_in_time_order() -> None:
    strat = LsdStrategy()
    strat.on_bar(FULL_LONG[1])
    with pytest.raises(ValueError):
        strat.on_bar(FULL_LONG[0])


def test_setup_events_carry_geometry_in_real_prices_for_both_sides() -> None:
    for bars, side, top, bot, liq in [
        (FULL_LONG, "long", 111, 106, 113),
        ([b.mirrored() for b in FULL_LONG], "short", -106, -111, -113),
    ]:
        strat = LsdStrategy()
        for bar in bars:
            strat.on_bar(bar)
        (started,) = [
            e for e in strat.drain_events() if e.kind == "setup_started" and e.side == side
        ]
        d = started.detail
        assert (d["zone_top"], d["zone_bot"], d["liq_price"], d["zone_o_idx"]) == (top, bot, liq, 6)


def test_open_liquidity_is_visible_for_inspection() -> None:
    strat = LsdStrategy()
    for bar in FULL_LONG[:14]:
        strat.on_bar(bar)
    assert [liq.price for liq in strat.long.liquidity.open] == [106, 113]
