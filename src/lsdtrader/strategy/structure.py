"""M2 · Liquidity candidates P and break of structure (Strategy Spec §4)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from lsdtrader.core.bar import TickBar
from lsdtrader.core.config import StrategyConfig
from lsdtrader.core.events import EventLog
from lsdtrader.strategy.swings import Swing


@dataclass(frozen=True, slots=True)
class Bos:
    p_idx: int  # bar of the swing low P
    p_low: int
    l0_idx: int  # bar of L0, the last swing low at or below P
    h2: int  # highest high after L0 up to P: the level the BOS must break
    bos_idx: int  # bar that broke H2
    known_idx: int  # bar on which the engine learned about the BOS


@dataclass(frozen=True, slots=True)
class _Candidate:
    p_idx: int
    p_low: int
    l0_idx: int
    h2: int


class StructureTracker:
    def __init__(self, cfg: StrategyConfig, log: EventLog) -> None:
        self._cfg = cfg
        self._log = log
        # Swing lows with strictly increasing prices: the nearest earlier swing at or
        # below a new swing is always on top (monotonic stack).
        self._stack: list[Swing] = []
        self._candidates: list[_Candidate] = []

    @property
    def candidates(self) -> int:
        return len(self._candidates)

    def update(self, bars: Sequence[TickBar], new_swing: Swing | None) -> list[Bos]:
        """Process the newest bar; `new_swing` is the swing it confirmed, if any."""
        i = len(bars) - 1
        bar = bars[i]
        found: list[Bos] = []
        alive: list[_Candidate] = []
        for cand in self._candidates:
            if bar.low < cand.p_low:
                self._log.emit("cand_undercut", p_idx=cand.p_idx)
            elif self._breaks(bar, cand.h2):
                found.append(Bos(cand.p_idx, cand.p_low, cand.l0_idx, cand.h2, i, i))
            elif self._expired(cand, i):
                self._log.emit("cand_expired", p_idx=cand.p_idx)
            else:
                alive.append(cand)
        self._candidates = alive
        if new_swing is not None:
            bos = self._add(bars, new_swing)
            if bos is not None:
                found.append(bos)
        return found

    def _add(self, bars: Sequence[TickBar], swing: Swing) -> Bos | None:
        while self._stack and self._stack[-1].price > swing.price:
            self._stack.pop()
        l0 = self._stack[-1] if self._stack else None
        self._stack.append(swing)
        if l0 is None:
            self._log.emit("cand_no_lower_low", p_idx=swing.idx)
            return None
        h2 = max(b.high for b in bars[l0.idx + 1 : swing.idx + 1])
        cand = _Candidate(swing.idx, swing.price, l0.idx, h2)
        i = len(bars) - 1
        # Bars between P and its confirmation are part of the BOS check. Their lows are
        # strictly above P (swing definition), so P cannot have been undercut.
        for j in range(swing.idx + 1, i + 1):
            if self._breaks(bars[j], h2):
                return Bos(swing.idx, swing.price, l0.idx, h2, j, i)
            if self._expired(cand, j):
                self._log.emit("cand_expired", p_idx=swing.idx)
                return None
        self._candidates.append(cand)
        return None

    def _breaks(self, bar: TickBar, level: int) -> bool:
        if self._cfg.bos_confirm == "close":
            return bar.close > level
        return bar.high > level

    def _expired(self, cand: _Candidate, i: int) -> bool:
        limit = self._cfg.bos_max_bars
        return limit is not None and i - cand.p_idx >= limit
