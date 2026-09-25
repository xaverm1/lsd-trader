from collections.abc import Sequence

from lsdtrader.core.bar import TickBar
from lsdtrader.core.config import StrategyConfig
from lsdtrader.core.events import EventLog
from lsdtrader.strategy.liquidity import Liquidity
from lsdtrader.strategy.setups import Entry, SetupTracker
from lsdtrader.strategy.zones import Zone, ZoneBook
from tests.helpers import make_bars

PRE = (120, 121, 118, 119)  # a bar before the sweep; the sweep is always bar index 1


def run(
    after: Sequence[tuple[int, int, int, int]], cfg: StrategyConfig | None = None
) -> tuple[list[Entry], EventLog, Zone]:
    """Zone [106, 111] (left), liquidity 113; bars[1] is the sweep bar."""
    cfg = cfg or StrategyConfig()
    log = EventLog()
    book = ZoneBook(cfg, log)
    z = Zone(
        zone_id=7,
        o_idx=0,
        top=111,
        bot=106,
        p_idx=0,
        created_idx=0,
        kind="accuracy",
        pending=False,
        state="left",
    )
    tracker = SetupTracker(cfg, log, book)
    liq = Liquidity(liq_id=0, idx=0, price=113, bos_idx=0)
    all_bars = make_bars(PRE, *after)
    entries: list[Entry] = []
    for i in range(1, len(all_bars)):
        log.bar_index = i
        if i == 1:
            tracker.start(z, liq, sweep_idx=1, atr=4.0)
        window: list[TickBar] = all_bars[: i + 1]
        entries += tracker.update(window)
    return entries, log, z


def test_sweep_tap_and_entry_on_one_bar() -> None:
    entries, _, z = run([(112, 117, 110, 115)])
    (e,) = entries
    assert (e.entry_idx, e.entry, e.stop, e.target) == (1, 115, 110, 135)
    assert (e.sweep_idx, e.tap_idx) == (1, 1)
    assert z.state == "consumed"


def test_touching_top_is_a_tap_stopping_short_is_not() -> None:
    # Scenario 12
    assert run([(112, 117, 111, 115)])[0]  # touches 111
    entries, log, _ = run(
        [(116, 117, 112, 115), (115, 116, 112, 114), (114, 115, 112, 113), (113, 114, 112, 113)]
    )
    assert entries == [] and "no_tap" in log.kinds()


def test_tap_tolerance_setting() -> None:
    assert run([(114, 117, 113, 115)], StrategyConfig(tap_tol_ticks=2))[0]


def test_bearish_tap_then_bullish_bar_within_three() -> None:
    # Scenario 13
    entries, _, _ = run([(116, 117, 110, 112), (112, 113, 111, 112), (112, 115, 111, 114)])
    (e,) = entries
    assert (e.tap_idx, e.entry_idx, e.entry, e.stop) == (1, 3, 114, 110)
    assert e.features["bars_tap_to_entry"] == 2


def test_no_bullish_bar_within_three_bars() -> None:
    entries, log, _ = run(
        [
            (116, 117, 110, 112),
            (112, 113, 111, 112),
            (112, 113, 111, 112),
            (112, 113, 111, 112),
            (112, 115, 111, 114),
        ]
    )
    assert entries == [] and "no_entry" in log.kinds()


def test_destroyed_zone_drops_setup() -> None:
    cfg = StrategyConfig()
    log = EventLog()
    book = ZoneBook(cfg, log)
    z = Zone(zone_id=7, o_idx=0, top=111, bot=106, p_idx=0, created_idx=0, state="left")
    tracker = SetupTracker(cfg, log, book)
    tracker.start(z, Liquidity(0, 0, 113, 0), sweep_idx=1, atr=None)
    z.state = "destroyed"
    assert tracker.update(make_bars(PRE, (112, 117, 110, 115))) == []
    assert "setup_zone_gone" in log.kinds()


def test_one_setup_per_zone() -> None:
    cfg = StrategyConfig()
    log = EventLog()
    tracker = SetupTracker(cfg, log, ZoneBook(cfg, log))
    z = Zone(zone_id=7, o_idx=0, top=111, bot=106, p_idx=0, created_idx=0, state="left")
    assert tracker.start(z, Liquidity(0, 0, 113, 0), 1, None) is not None
    assert tracker.start(z, Liquidity(1, 0, 115, 0), 1, None) is None


TAP_THEN_TWO = [(116, 117, 110, 112), (112, 115, 111, 114), (114, 119, 113, 118)]


def test_entry_trigger_variants() -> None:
    # bar 2: bullish, close 114 (body 2) · bar 3: bullish, close 118 (body 4) · tap high 117
    def first_entry(trigger: str) -> int:
        cfg = StrategyConfig(entry_trigger=trigger, min_body_ticks=3)  # type: ignore[arg-type]
        (e,) = run(TAP_THEN_TWO, cfg)[0]
        return e.entry_idx

    assert first_entry("bullish") == 2
    assert first_entry("above_liq") == 2  # 114 > 113
    assert first_entry("above_tap_high") == 3  # needs close > 117
    assert first_entry("min_body") == 3  # needs body >= 3


def test_stop_modes_and_buffer() -> None:
    bar = [(112, 117, 110, 115)]
    assert run(bar, StrategyConfig(sl_mode="zone_bottom"))[0][0].stop == 106
    assert run(bar, StrategyConfig(sl_mode="zone_mid"))[0][0].stop == 108
    assert run(bar, StrategyConfig(sl_buffer_ticks=2))[0][0].stop == 108


def test_target_uses_rr_and_rounds_away_from_entry() -> None:
    (e,) = run([(112, 117, 110, 115)], StrategyConfig(rr=2.5))[0]
    assert e.target == 115 + 13  # ceil(2.5 * 5)


def test_second_liquidity_for_a_running_setup_leaves_an_event() -> None:
    # Review finding: every rejected object must leave an event.
    cfg = StrategyConfig()
    log = EventLog()
    tracker = SetupTracker(cfg, log, ZoneBook(cfg, log))
    z = Zone(zone_id=7, o_idx=0, top=111, bot=106, p_idx=0, created_idx=0, state="left")
    tracker.start(z, Liquidity(0, 0, 113, 0), 1, None)
    tracker.start(z, Liquidity(1, 0, 115, 0), 1, None)
    assert "setup_already_running" in log.kinds()
