from collections.abc import Sequence

import pytest

from lsdtrader.core.bar import TickBar
from lsdtrader.core.config import StrategyConfig
from lsdtrader.core.events import EventLog
from lsdtrader.strategy.structure import Bos
from lsdtrader.strategy.zones import Zone, ZoneBook, find_origin
from tests.helpers import make_bars

O_BAR = (110, 112, 100, 104)  # bearish, body top 110, high 112, low 100


def bos_at(p_idx: int, bos_idx: int) -> Bos:
    return Bos(p_idx=p_idx, p_low=0, l0_idx=0, h2=0, bos_idx=bos_idx, known_idx=bos_idx)


def create(
    bars: Sequence[TickBar], p_idx: int = 0, cfg: StrategyConfig | None = None
) -> tuple[list[Zone], ZoneBook, EventLog]:
    log = EventLog()
    book = ZoneBook(cfg or StrategyConfig(), log)
    zones = book.create(bars, bos_at(p_idx, len(bars) - 1))
    return zones, book, log


def test_origin_is_p_when_p_is_bearish() -> None:
    # Scenario 6a
    bars = make_bars((100, 101, 95, 96), (96, 97, 90, 91), (91, 99, 91, 98))
    assert find_origin(bars, p_idx=1, lookback=20, doji_tol_ticks=0) == 1


def test_origin_is_bar_before_bullish_p() -> None:
    # Scenario 6b
    bars = make_bars((100, 101, 94, 95), (95, 97, 90, 96), (96, 99, 95, 98))
    assert find_origin(bars, p_idx=1, lookback=20, doji_tol_ticks=0) == 0


def test_origin_falls_back_to_p_and_doji_counts() -> None:
    bullish = make_bars((90, 95, 89, 94), (94, 97, 90, 96))
    assert find_origin(bullish, p_idx=1, lookback=20, doji_tol_ticks=0) == 1
    doji = make_bars((95, 96, 94, 95), (95, 97, 90, 96))
    assert find_origin(doji, p_idx=1, lookback=20, doji_tol_ticks=0) == 0


def test_overlapping_bearish_pullback_relocates_zone() -> None:
    # Scenario 6c
    bars = make_bars(O_BAR, (104, 106, 98, 99), (99, 120, 99, 119))
    (zone,), _, log = create(bars)
    assert zone.o_idx == 1
    assert "zone_relocation" in log.kinds()


@pytest.mark.parametrize(
    ("f_bar", "kind", "top", "bot"),
    [
        ((104, 114, 103, 113), "normal", 112, 100),  # F above O.high
        ((104, 114, 97, 113), "normal", 112, 100),  # normal stays on O even if F.low is lower
        ((104, 111, 102, 110), "accuracy", 110, 100),  # F.low above O.low -> O.low
        ((104, 111, 98, 110), "accuracy", 110, 98),  # F.low below O.low -> F.low
        ((104, 112, 102, 110), "accuracy", 110, 100),  # F.high == O.high -> accuracy
    ],
)
def test_geometry(f_bar: tuple[int, int, int, int], kind: str, top: int, bot: int) -> None:
    # Scenario 8
    (zone,), _, _ = create(make_bars(O_BAR, f_bar))
    assert (zone.kind, zone.top, zone.bot) == (kind, top, bot)


def test_zone_mode_normal_ignores_f() -> None:
    cfg = StrategyConfig(zone_mode="normal")
    (zone,), _, _ = create(make_bars(O_BAR, (104, 111, 98, 110)), cfg=cfg)
    assert (zone.kind, zone.top, zone.bot) == ("normal", 112, 100)


def test_zone_is_left_when_a_bar_trades_fully_above() -> None:
    (zone,), _, _ = create(make_bars(O_BAR, (104, 120, 104, 119), (119, 125, 115, 124)))
    assert zone.state == "left"


def test_close_below_during_build_kills_zone() -> None:
    (zone,), _, log = create(make_bars(O_BAR, (104, 114, 103, 113), (95, 99, 94, 98)))
    assert zone.state == "dead"
    assert "zone_died_building" in log.kinds()


LEFT = [O_BAR, (104, 120, 104, 119), (119, 125, 115, 124)]  # normal zone [100, 112], left


@pytest.mark.parametrize(
    ("bar", "state", "event"),
    [
        ((124, 124, 108, 114), "left", None),  # wick in, close above: valid tap
        ((124, 124, 108, 111), "destroyed", "zone_destroyed_close"),  # close inside
        ((124, 124, 108, 112), "destroyed", "zone_destroyed_close"),  # close on the top edge
        ((124, 124, 99, 114), "destroyed", "zone_destroyed_wick"),  # wick through
        ((124, 124, 95, 98), "destroyed", "zone_destroyed_close"),  # close below
    ],
)
def test_destruction(bar: tuple[int, int, int, int], state: str, event: str | None) -> None:
    # Scenario 9
    bars = make_bars(*LEFT)
    (zone,), book, log = create(bars)
    bars = make_bars(*LEFT, bar)
    book.update(bars)
    assert zone.state == state
    if event:
        assert event in log.kinds()


def test_close_beyond_variant_only_kills_on_close_below() -> None:
    cfg = StrategyConfig(zone_kill="close_beyond")
    (zone,), book, _ = create(make_bars(*LEFT), cfg=cfg)
    book.update(make_bars(*LEFT, (124, 124, 99, 105)))
    assert zone.state == "left"
    book.update(make_bars(*LEFT, (124, 124, 99, 105), (105, 106, 95, 98)))
    assert zone.state == "destroyed"


def test_consume_after_max_trades() -> None:
    (zone,), book, _ = create(make_bars(*LEFT))
    book.consume(zone)
    assert zone.state == "consumed"
    assert book.live() == []


EXTRA = [
    (110, 112, 100, 104),  # 0 P / O, zone [100, 112] (normal after F)
    (104, 116, 103, 115),  # 1 F
    (115, 118, 114, 116),  # 2
    (116, 117, 113, 114),  # 3 bearish, low 113 > 112: no overlap -> extra candidate
    (114, 122, 114, 121),  # 4
    (121, 123, 119, 120),  # 5 bearish, no overlap -> extra candidate
    (120, 130, 120, 129),  # 6 BOS bar
]


@pytest.mark.parametrize(("mode", "origins"), [("none", [0]), ("last", [0, 5]), ("all", [0, 3, 5])])
def test_extra_zones(mode: str, origins: list[int]) -> None:
    # Scenario 7
    cfg = StrategyConfig(extra_zones=mode)  # type: ignore[arg-type]
    zones, _, _ = create(make_bars(*EXTRA), cfg=cfg)
    assert sorted(z.o_idx for z in zones) == origins


def test_origin_search_respects_lookback() -> None:
    bars = make_bars((100, 101, 94, 95), (95, 97, 90, 96), (96, 99, 95, 98))
    assert find_origin(bars, p_idx=1, lookback=1, doji_tol_ticks=0) == 1
