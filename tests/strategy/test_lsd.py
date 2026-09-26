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


def test_untraded_touch_after_leaving_moves_the_zone() -> None:
    # Bar 10 becomes a bearish bar whose wick touches the zone top (111) with no liquidity
    # swept: the zone moves onto bar 10, so the original zone [106, 111] never trades.
    bars = (
        FULL_LONG[:10]
        + make_bars((120, 122, 111, 117), start=10)
        + [TickBar(b.ts, b.open, b.high, b.low, b.close) for b in FULL_LONG[11:]]
    )
    strat = LsdStrategy()
    signals = [s for bar in bars for s in strat.on_bar(bar)]
    assert not [s for s in signals if (s.zone_top, s.zone_bot) == (111, 106)]
    relocations = [
        e for e in strat.drain_events() if e.kind == "zone_relocation" and e.side == "long"
    ]
    assert any(e.bar_index == 10 and e.detail["o_idx"] == 10 for e in relocations)


def test_sweep_and_tap_on_the_same_bar_still_trades() -> None:
    # FULL_LONG bar 15 is bearish and touches the zone, but it also sweeps P': it is the tap.
    (sig,) = [s for s in run(FULL_LONG) if s.side == "long"]
    assert (sig.zone_top, sig.zone_bot, sig.tap_idx) == (111, 106, 15)


def test_a_tap_bar_can_become_a_new_zone() -> None:
    # Xaver: a tap can itself become a zone when all criteria are met. In FULL_LONG the tap
    # bar 15 is bearish and overlaps the still-building zone of P' (origin 11), which
    # relocates onto it; the BOS from the swing low at bar 15 (close 130 > H2 124 on bar 18)
    # then finds that zone already there instead of creating a copy.
    bars = FULL_LONG + make_bars((114, 120, 113, 119), (119, 131, 118, 130), start=17)
    strat = LsdStrategy()
    for bar in bars:
        strat.on_bar(bar)
    (zone,) = [z for z in strat.long.zones.history if z.o_idx == 15]
    assert zone.state == "left"  # a live zone on the tap bar, ready for a later setup
    kinds = [(e.bar_index, e.kind) for e in strat.drain_events() if e.side == "long"]
    assert (18, "bos") in kinds and (18, "zone_duplicate") in kinds


def test_all_before_bos_makes_every_unswept_swing_low_liquidity() -> None:
    from lsdtrader.strategy.lsd import SideEngine

    def open_prices(cfg: StrategyConfig) -> list[int]:
        eng = SideEngine(cfg)
        for b in FULL_LONG[:14]:
            eng.on_bar(b)
        return sorted(liq.price for liq in eng.liquidity.open)

    # BOS on bar 9 (P = 106 on bar 6), BOS on bar 13 (P' = 113 on bar 11); the swing low 100
    # on bar 1 (L0 of the first BOS) had no BOS of its own
    assert open_prices(StrategyConfig()) == [106, 113]
    assert open_prices(StrategyConfig(liq_source="all_before_bos")) == [100, 106, 113]
