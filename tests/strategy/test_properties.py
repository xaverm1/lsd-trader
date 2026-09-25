"""Whole-engine properties on long random price paths."""

import random
from dataclasses import astuple, replace
from datetime import timedelta

from lsdtrader.core.bar import TickBar
from lsdtrader.strategy.lsd import LsdStrategy, Signal
from tests.helpers import T0


def random_walk(n: int, seed: int) -> list[TickBar]:
    rng = random.Random(seed)
    bars, close = [], 10_000
    for i in range(n):
        o = close
        c = o + rng.randint(-8, 8)
        h = max(o, c) + rng.randint(0, 5)
        low = min(o, c) - rng.randint(0, 5)
        bars.append(TickBar(T0 + timedelta(minutes=5 * i), o, h, low, c))
        close = c
    return bars


def run(bars: list[TickBar]) -> list[Signal]:
    strat = LsdStrategy()
    return [s for bar in bars for s in strat.on_bar(bar)]


def mirror(sig: Signal) -> Signal:
    side = "short" if sig.side == "long" else "long"
    return replace(
        sig,
        side=side,
        entry=-sig.entry,
        stop=-sig.stop,
        target=-sig.target,
        zone_top=-sig.zone_bot,
        zone_bot=-sig.zone_top,
        liq_price=-sig.liq_price,
        setup_id=sig.setup_id.replace(sig.side, side),
        zone_id=sig.zone_id.replace(sig.side, side),
    )


BARS = random_walk(3000, seed=7)


def test_random_walk_produces_trades_on_both_sides() -> None:
    sides = {s.side for s in run(BARS)}
    assert sides == {"long", "short"}


def test_mirror_symmetry() -> None:
    original = sorted(astuple(mirror(s)) for s in run(BARS))
    mirrored = sorted(astuple(s) for s in run([b.mirrored() for b in BARS]))
    assert original == mirrored


def test_no_lookahead() -> None:
    """Decisions on bar k depend only on bars 0..k: a fresh engine fed bars[:k+1]
    must emit exactly the signals the full run emitted on bar k."""
    bars = BARS[:400]
    full = run(bars)
    for k in range(len(bars)):
        strat = LsdStrategy()
        last: list[Signal] = []
        for bar in bars[: k + 1]:
            last = strat.on_bar(bar)
        assert last == [s for s in full if s.bar_index == k]


def test_determinism_including_events() -> None:
    def full_run() -> tuple[list[Signal], list[object]]:
        strat = LsdStrategy()
        sigs = [s for bar in BARS for s in strat.on_bar(bar)]
        return sigs, list(strat.drain_events())

    assert full_run() == full_run()
