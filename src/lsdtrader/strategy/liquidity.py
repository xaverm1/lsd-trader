"""M4 · Liquidity P′ (Strategy Spec §6)."""

from __future__ import annotations

from dataclasses import dataclass, field

from lsdtrader.core.bar import TickBar
from lsdtrader.core.config import StrategyConfig
from lsdtrader.strategy.structure import Bos
from lsdtrader.strategy.zones import Zone

# Furthest stage a sweep reached without finding a zone, in order.
NO_SETUP_REASONS = ("no_zone_below", "zone_not_left", "liq_before_zone", "too_far")
# (liq_rule="nearest" rejections are reported as "too_far" as well)


@dataclass(slots=True)
class Liquidity:
    liq_id: int
    idx: int  # bar of the swing low P′
    price: int
    bos_idx: int
    h2: int | None = None  # the level its BOS broke
    h2_idx: int | None = None
    # liq_source="swing_break": the swing lows (bar, price) of every break that made this one
    # liquidity; for a zone it counts only as the lowest of a group above the zone after O
    groups: list[list[tuple[int, int]]] = field(default_factory=list)


class LiquidityBook:
    def __init__(self) -> None:
        self._open: list[Liquidity] = []
        self._next_id = 0

    @property
    def open(self) -> list[Liquidity]:
        """Liquidity not yet swept (for inspection)."""
        return list(self._open)

    def add(
        self, bos: Bos, h2_idx: int | None = None, swing: tuple[int, int] | None = None
    ) -> Liquidity:
        """Liquidity from a BOS: its P, or another swing low (bar, price) the BOS validates."""
        idx, price = swing if swing is not None else (bos.p_idx, bos.p_low)
        liq = Liquidity(self._next_id, idx, price, bos.bos_idx, bos.h2, h2_idx)
        self._next_id += 1
        self._open.append(liq)
        return liq

    def add_break(
        self, h_idx: int, h_price: int, bos_idx: int, group: list[tuple[int, int]]
    ) -> list[Liquidity]:
        """liq_source="swing_break": the swing lows of one break (a close above the swing high
        at `h_idx`). `group` is shared, so candidates appended to it later count as well.
        A swing low already open is kept once and gets this group too; returns new ones."""
        return [
            x for cand in group if (x := self.add_to_break(h_idx, h_price, bos_idx, group, cand))
        ]

    def add_to_break(
        self,
        h_idx: int,
        h_price: int,
        bos_idx: int,
        group: list[tuple[int, int]],
        cand: tuple[int, int],
    ) -> Liquidity | None:
        """Register swing low `cand` of a break's `group` (appended if not in it yet)."""
        if cand not in group:
            group.append(cand)
        known = next((x for x in self._open if x.idx == cand[0]), None)
        if known is not None:
            if not any(g is group for g in known.groups):
                known.groups.append(group)
            return None
        liq = Liquidity(self._next_id, cand[0], cand[1], bos_idx, h_price, h_idx, [group])
        self._next_id += 1
        self._open.append(liq)
        return liq

    def swept_by(self, bar: TickBar) -> list[Liquidity]:
        """Liquidity whose price the bar trades below. Swept liquidity is gone for good."""
        swept = [liq for liq in self._open if bar.low < liq.price]
        self._open = [liq for liq in self._open if bar.low >= liq.price]
        return swept


def match_zones(
    liq: Liquidity,
    zones: list[Zone],
    atr: float | None,
    cfg: StrategyConfig,
    open_before: list[Liquidity] | None = None,
) -> tuple[list[Zone], str | None]:
    """Zones for which `liq` is valid liquidity, or the reason there are none.

    `open_before`: the liquidity that was unswept before this bar or minute (for
    liq_rule="nearest": another of these between the zone and `liq` makes `liq` too far).
    """
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
        if liq.groups and not any(lowest_for(g, z) == liq.idx for g in liq.groups):
            continue
        if cfg.liq_rule == "nearest" and any(
            o is not liq and o.idx > z.o_idx and z.top < o.price < liq.price
            for o in open_before or []
        ):
            continue
        matched.append(z)
    if matched:
        return matched, None
    return [], NO_SETUP_REASONS[stage]


def lowest_for(group: list[tuple[int, int]], z: Zone) -> int | None:
    """Bar of the lowest swing low of a break above zone `z` and after its origin (the latest
    one if several share the price)."""
    cands = [(price, -idx) for idx, price in group if price > z.top and idx > z.o_idx]
    return -min(cands)[1] if cands else None
