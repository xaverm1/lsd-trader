from lsdtrader.core.config import StrategyConfig
from lsdtrader.strategy.liquidity import Liquidity, LiquidityBook, match_zones
from lsdtrader.strategy.structure import Bos
from lsdtrader.strategy.zones import Zone
from tests.helpers import make_bars


def zone(o_idx: int = 0, top: int = 111, bot: int = 106, state: str = "left") -> Zone:
    return Zone(zone_id=1, o_idx=o_idx, top=top, bot=bot, p_idx=o_idx, created_idx=5, state=state)  # type: ignore[arg-type]


def liq(idx: int = 11, price: int = 113) -> Liquidity:
    return Liquidity(liq_id=0, idx=idx, price=price, bos_idx=13)


def test_sweep_needs_trading_below_and_is_final() -> None:
    book = LiquidityBook()
    book.add(Bos(p_idx=11, p_low=113, l0_idx=6, h2=122, bos_idx=13, known_idx=13))
    (touch,) = make_bars((116, 117, 113, 114))
    assert book.swept_by(touch) == []
    (below,) = make_bars((116, 117, 112, 114))
    assert [x.price for x in book.swept_by(below)] == [113]
    assert book.swept_by(below) == []


def test_valid_liquidity_matches_zone() -> None:
    assert match_zones(liq(), [zone()], atr=None, cfg=StrategyConfig()) == ([zone()], None)


def test_liquidity_formed_before_zone_bos_still_counts() -> None:
    # Scenario 10: Pa (idx 3) formed inside the impulse, before the zone's BOS (created_idx 5).
    matched, reason = match_zones(liq(idx=3), [zone(o_idx=0)], None, StrategyConfig())
    assert reason is None and len(matched) == 1


def test_reasons_report_the_furthest_stage() -> None:
    cfg = StrategyConfig()
    assert match_zones(liq(), [], None, cfg)[1] == "no_zone_below"
    assert match_zones(liq(), [zone(top=113)], None, cfg)[1] == "no_zone_below"
    assert match_zones(liq(), [zone(state="building")], None, cfg)[1] == "zone_not_left"
    assert match_zones(liq(idx=0), [zone(o_idx=0)], None, cfg)[1] == "liq_before_zone"


def test_atr_distance_filter() -> None:
    cfg = StrategyConfig(liq_max_dist_atr=1.0)
    assert match_zones(liq(price=113), [zone(top=111)], atr=2.0, cfg=cfg)[1] is None
    assert match_zones(liq(price=114), [zone(top=111)], atr=2.0, cfg=cfg)[1] == "too_far"
    assert match_zones(liq(price=113), [zone(top=111)], atr=None, cfg=cfg)[1] == "too_far"


def test_one_sweep_can_arm_stacked_zones() -> None:
    lower, upper = zone(o_idx=0, top=104, bot=100), zone(o_idx=2, top=111, bot=106)
    matched, reason = match_zones(liq(), [lower, upper], None, StrategyConfig())
    assert reason is None and matched == [lower, upper]


def test_nearest_rule_skips_liquidity_with_a_closer_swing_in_between() -> None:
    cfg = StrategyConfig(liq_rule="nearest")
    near, far = liq(idx=11, price=113), liq(idx=12, price=118)
    before = [near, far]
    assert match_zones(far, [zone()], None, cfg, before)[1] == "too_far"
    assert match_zones(near, [zone()], None, cfg, before) == ([zone()], None)
    # the far one counts once the near one is gone, or under the default rule
    assert match_zones(far, [zone()], None, cfg, [far])[1] is None
    assert match_zones(far, [zone()], None, StrategyConfig(), before)[1] is None


def test_nearest_rule_ignores_swings_older_than_the_zone() -> None:
    cfg = StrategyConfig(liq_rule="nearest")
    old, far = liq(idx=0, price=113), liq(idx=12, price=118)
    assert match_zones(far, [zone(o_idx=3)], None, cfg, [old, far])[1] is None
