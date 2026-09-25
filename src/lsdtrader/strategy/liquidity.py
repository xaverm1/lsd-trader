"""M4 · Liquidity P′ (Strategy Spec §6)."""

from __future__ import annotations

from dataclasses import dataclass

from lsdtrader.core.bar import TickBar
from lsdtrader.core.config import StrategyConfig
from lsdtrader.strategy.structure import Bos
from lsdtrader.strategy.zones import Zone

# Furthest stage a sweep reached without finding a zone, in order.
NO_SETUP_REASONS = ("no_zone_below", "zone_not_left", "liq_before_zone", "too_far")


@dataclass(slots=True)
class Liquidity:
    liq_id: int
    idx: int  # bar of the swing low P′
    price: int
    bos_idx: int


class LiquidityBook:
    def __init__(self) -> None:
        self._open: list[Liquidity] = []
        self._next_id = 0

    def add(self, bos: Bos) -> Liquidity:
        liq = Liquidity(self._next_id, bos.p_idx, bos.p_low, bos.bos_idx)
        self._next_id += 1
        self._open.append(liq)
        return liq

    def swept_by(self, bar: TickBar) -> list[Liquidity]:
        """Liquidity whose price the bar trades below. Swept liquidity is gone for good."""
        swept = [liq for liq in self._open if bar.low < liq.price]
        self._open = [liq for liq in self._open if bar.low >= liq.price]
        return swept


def match_zones(
    liq: Liquidity, zones: list[Zone], atr: float | None, cfg: StrategyConfig
) -> tuple[list[Zone], str | None]:
    """Zones for which `liq` is valid liquidity, or the reason there are none."""
    stage = 0
    matched: list[Zone] = []
    for z in zones:
        if z.top >= liq.price:
            continue
        stage = max(stage, 1)
        if z.state != "left":
            continue
        stage = max(stage, 2)
        if z.o_idx >= liq.idx:
            continue
        stage = max(stage, 3)
        limit = cfg.liq_max_dist_atr
        if limit is not None and (atr is None or liq.price - z.top > limit * atr):
            continue
        matched.append(z)
    if matched:
        return matched, None
    return [], NO_SETUP_REASONS[stage]
