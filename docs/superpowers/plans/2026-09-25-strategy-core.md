# Strategy Core (Plan 2a) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the LSD strategy rules M1–M5 (plus stop/target) as a pure, tested Python state machine: closed 5-minute bars in, entry signals and rule events out.

**Architecture:** Prices are integer ticks (`TickBar`), so every equality in the rules is exact. The long-side rules live in small modules (swings → structure → zones → liquidity → setups) composed by `SideEngine`; the short side is the same `SideEngine` fed with mirrored bars, which makes long/short symmetry true by construction. `LsdStrategy` runs both sides per instrument and knows nothing about clocks, costs or brokers (those are Plan 2b).

**Tech Stack:** Python ≥ 3.12, no runtime dependencies; dev: pytest, pytest-cov, ruff, mypy (strict), hatchling build, GitHub Actions.

**Spec:** `docs/specs/2026-09-25-lsd-strategy-v1.md` (rules) and `docs/specs/2026-09-25-engine-backtester-design.md` (§3 layout, §5 strategy core, §9 testing). Read both before starting.

**Part of:** Sub-project 2, split into Plan 2a (this: strategy core), 2b (SimBroker, backtest runner, journal), 2c (Databento data, roll, 1m→5m), 2d (`lsd inspect`, acceptance). Plan 2a ships a standalone, fully tested library.

## Global Constraints

- Python `>=3.12`; zero runtime dependencies in this plan.
- All strategy prices are `int` ticks; no floats in price comparisons (ATR is the only float).
- Strategy code must not read clocks, costs, sizing or broker state.
- Long rules only; short = long on `TickBar.mirrored()` bars. Never write a separate short branch.
- Every rule that rejects or kills an object emits a named event via `EventLog.emit`.
- Parameters and defaults exactly as `StrategyConfig` below (Strategy Spec §9).
- `ruff check`, `ruff format --check`, `mypy` (strict, `src/`) and `pytest` must pass after every task; line length 100.
- Commit after every task; messages end with the `Co-Authored-By` line used in this repo.
- Work in `C:\Users\Xaver\lsd-trader` (git repo, branch `main`). Commands are for Git Bash; the venv is activated with `source .venv/Scripts/activate`.

## Review Focus

- **Bars fed out of time order or duplicated** — a live feed can resend bars; `LsdStrategy.on_bar` must raise `ValueError` instead of silently corrupting state (test in Task 7).
- **One bar undercuts P and closes above H2** — the undercut must win (Spec §4.2 rule 3); otherwise the engine books a BOS from a low that no longer exists (test in Task 3).
- **Stacked zones swept by one move** — one sweep must arm every valid zone below it, each with its own setup (test in Task 5).
- **Origin search at the start of the data or with a short lookback** — must stay inside `zoneLookback` and never index before bar 0 (test in Task 4).
- **Fixtures appended to other fixtures** — timestamps must keep increasing (`make_bars(..., start=n)`), or the time-order guard fires in tests that concatenate bar lists (used in Tasks 3 and 7).

---

### Task 1: Project scaffold and core types

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `README.md`, `.github/workflows/ci.yml`
- Create: `src/lsdtrader/__init__.py`, `src/lsdtrader/core/__init__.py`, `src/lsdtrader/strategy/__init__.py` (the last two empty)
- Create: `src/lsdtrader/core/bar.py`, `src/lsdtrader/core/config.py`, `src/lsdtrader/core/events.py`
- Create: `tests/__init__.py`, `tests/core/__init__.py`, `tests/strategy/__init__.py` (empty), `tests/helpers.py`
- Test: `tests/core/test_bar_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `TickBar(ts: datetime, open: int, high: int, low: int, close: int)` with `.body_top`, `.body_bot`, `.mirrored() -> TickBar`; raises `ValueError` if high/low do not contain open/close.
  - `StrategyConfig` (frozen dataclass, fields and defaults below; invalid values raise `ValueError`).
  - `Event(bar_index: int, kind: str, detail: dict[str, object], side: str = "")`; `EventLog` with `.events`, `.bar_index`, `.emit(kind, **detail)`, `.kinds() -> list[str]`, `.drain() -> list[Event]`.
  - Test helpers `T0`, `make_bars(*ohlc, start=0)`, `bars_from_lows(*lows)`, fixture `FULL_LONG`.

- [ ] **Step 1: Write the build and tooling files**

`pyproject.toml`:

```toml
[build-system]
requires = ["hatchling>=1.25"]
build-backend = "hatchling.build"

[project]
name = "lsdtrader"
version = "0.1.0"
description = "Backtest and live engine for the LSD 5-minute futures strategy"
readme = "README.md"
requires-python = ">=3.12"
dependencies = []

[project.optional-dependencies]
dev = ["pytest>=8", "pytest-cov>=5", "ruff>=0.6", "mypy>=1.11"]

[tool.hatch.build.targets.wheel]
packages = ["src/lsdtrader"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src", "."]
addopts = "-q"

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "SIM"]
ignore = ["SIM110"]  # explicit loops read better in rule code

[tool.mypy]
strict = true
files = ["src"]
```

`.gitignore`:

```text
.venv/
__pycache__/
*.egg-info/
.pytest_cache/
.mypy_cache/
.ruff_cache/
.coverage
htmlcov/
data/
runs/
.env
```

`README.md`:

````markdown
# lsd-trader

Backtest and (later) live engine for the LSD 5-minute futures strategy.

- Strategy rules: [docs/specs/2026-09-25-lsd-strategy-v1.md](docs/specs/2026-09-25-lsd-strategy-v1.md)
- Engine design: [docs/specs/2026-09-25-engine-backtester-design.md](docs/specs/2026-09-25-engine-backtester-design.md)

## Development

```bash
python -m venv .venv
source .venv/Scripts/activate   # Windows Git Bash; on Linux/macOS: source .venv/bin/activate
python -m pip install -e ".[dev]"
pytest
```
````

`.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.12", "3.13"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - run: python -m pip install -e ".[dev]"
      - run: ruff check .
      - run: ruff format --check .
      - run: mypy
      - run: pytest --cov=lsdtrader --cov-report=term-missing --cov-fail-under=90
```

`src/lsdtrader/__init__.py`:

```python
"""Backtest and live engine for the LSD 5-minute futures strategy."""
```

Create the other `__init__.py` files listed above as empty files.

- [ ] **Step 2: Create the venv and install**

Run:
```bash
cd /c/Users/Xaver/lsd-trader
python -m venv .venv
source .venv/Scripts/activate
python -m pip install -e ".[dev]"
```
Expected: install finishes without errors.

- [ ] **Step 3: Write the test helpers and the failing tests**

`tests/helpers.py`:

```python
"""Hand-built bar fixtures. Prices are in ticks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from lsdtrader.core.bar import TickBar

T0 = datetime(2024, 1, 2, 14, 30, tzinfo=UTC)


def make_bars(*ohlc: tuple[int, int, int, int], start: int = 0) -> list[TickBar]:
    """Bars 5 minutes apart from (open, high, low, close) tuples.

    `start` is the bar number of the first bar, so fixtures can be appended to others.
    """
    return [
        TickBar(T0 + timedelta(minutes=5 * (start + i)), o, h, lo, c)
        for i, (o, h, lo, c) in enumerate(ohlc)
    ]


def bars_from_lows(*lows: int) -> list[TickBar]:
    """Small bullish bars with the given lows (only lows matter for swing tests)."""
    return make_bars(*[(low + 1, low + 2, low, low + 1) for low in lows])


# Scenario 14 of the Strategy Spec: a complete long trade.
# L0 = bar 1 (100) · P = bar 6 (106), H2 = 118 · BOS bar 9 · zone [106, 111] accuracy
# P′ = bar 11 (113), H2′ = 122 · BOS bar 13 · sweep + tap bar 15 · entry bar 16 at 114
FULL_LONG = make_bars(
    (110, 112, 104, 105),  # 0
    (105, 106, 100, 101),  # 1  L0
    (101, 108, 101, 107),  # 2
    (107, 115, 106, 114),  # 3
    (114, 118, 113, 117),  # 4  H2
    (117, 117, 110, 111),  # 5
    (111, 112, 106, 107),  # 6  P, bearish -> zone origin O
    (107, 110, 107, 109),  # 7  F: high 110 <= O.high 112 -> accuracy [106, 111]
    (109, 116, 108, 115),  # 8
    (115, 121, 114, 120),  # 9  BOS (close 120 > 118), zone left (low 114 > 111)
    (120, 122, 116, 117),  # 10 H2'
    (117, 118, 113, 114),  # 11 P'
    (114, 119, 114, 118),  # 12
    (118, 124, 117, 123),  # 13 BOS of P' (close 123 > 122)
    (123, 123, 115, 116),  # 14
    (116, 117, 110, 112),  # 15 sweep of 113 and tap of 111
    (112, 115, 111, 114),  # 16 bullish close -> entry 114, stop 110, target 130
)
```

`tests/core/test_bar_config.py`:

```python
import pytest

from lsdtrader.core.bar import TickBar
from lsdtrader.core.config import StrategyConfig
from tests.helpers import T0


def test_body_edges_and_mirror() -> None:
    bar = TickBar(T0, 110, 112, 100, 104)
    assert (bar.body_top, bar.body_bot) == (110, 104)
    m = bar.mirrored()
    assert (m.open, m.high, m.low, m.close) == (-110, -100, -112, -104)
    assert m.mirrored() == bar


def test_inconsistent_bar_rejected() -> None:
    with pytest.raises(ValueError):
        TickBar(T0, 110, 109, 100, 104)


def test_config_defaults_match_spec() -> None:
    cfg = StrategyConfig()
    assert cfg.piv_len == 1
    assert cfg.bos_confirm == "close"
    assert cfg.bos_max_bars is None
    assert cfg.extra_zones == "none"
    assert cfg.max_bars_sweep_to_tap == 3
    assert cfg.tap_tol_ticks == 0
    assert cfg.max_bars_tap_to_entry == 3
    assert cfg.sl_buffer_ticks == 0
    assert cfg.rr == 4.0
    assert cfg.max_trades_per_zone == 1


@pytest.mark.parametrize(
    "kwargs",
    [
        {"piv_len": 0},
        {"rr": 0},
        {"tap_tol_ticks": -1},
        {"bos_max_bars": 0},
        {"liq_max_dist_atr": 0},
        {"max_trades_per_zone": 0},
    ],
)
def test_config_rejects_invalid(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        StrategyConfig(**kwargs)  # type: ignore[arg-type]
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `pytest tests/core -v`
Expected: collection error `ModuleNotFoundError: No module named 'lsdtrader.core.bar'`.

- [ ] **Step 5: Implement the core types**

`src/lsdtrader/core/bar.py`:

```python
"""Price bars in integer ticks.

The strategy works on integer tick prices only, so equality checks
(doji, equal lows, "touches the zone top") are exact for every instrument.
Conversion from real prices to ticks happens in the data layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class TickBar:
    """A closed bar. Prices are integer multiples of the instrument's tick size."""

    ts: datetime
    open: int
    high: int
    low: int
    close: int

    def __post_init__(self) -> None:
        if not (self.low <= min(self.open, self.close) and self.high >= max(self.open, self.close)):
            raise ValueError(f"inconsistent bar {self}")

    @property
    def body_top(self) -> int:
        return max(self.open, self.close)

    @property
    def body_bot(self) -> int:
        return min(self.open, self.close)

    def mirrored(self) -> TickBar:
        """The same bar reflected at price 0: highs become lows, bullish becomes bearish.

        Running the long-side rules on mirrored bars yields exactly the short-side rules
        (Strategy Spec: "a short setup is the exact mirror").
        """
        return TickBar(self.ts, -self.open, -self.low, -self.high, -self.close)
```

`src/lsdtrader/core/config.py`:

```python
"""Strategy parameters (Strategy Spec §9). Defaults are the primary hypothesis."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class StrategyConfig:
    piv_len: int = 1
    bos_confirm: Literal["close", "wick"] = "close"
    bos_max_bars: int | None = None
    zone_lookback: int = 20
    doji_tol_ticks: int = 0
    zone_mode: Literal["auto", "normal"] = "auto"
    extra_zones: Literal["none", "last", "all"] = "none"
    zone_kill: Literal["close_inside", "close_beyond"] = "close_inside"
    liq_max_dist_atr: float | None = None
    atr_len: int = 14
    max_bars_sweep_to_tap: int = 3
    tap_tol_ticks: int = 0
    max_bars_tap_to_entry: int = 3
    entry_trigger: Literal["bullish", "above_tap_high", "above_liq", "min_body"] = "bullish"
    min_body_ticks: int = 1
    sl_buffer_ticks: int = 0
    sl_mode: Literal["wick", "zone_bottom", "zone_mid"] = "wick"
    rr: float = 4.0
    max_trades_per_zone: int = 1

    def __post_init__(self) -> None:
        if self.piv_len < 1:
            raise ValueError("piv_len must be >= 1")
        if self.bos_max_bars is not None and self.bos_max_bars < 1:
            raise ValueError("bos_max_bars must be >= 1 or None")
        if self.zone_lookback < 1:
            raise ValueError("zone_lookback must be >= 1")
        if self.atr_len < 1:
            raise ValueError("atr_len must be >= 1")
        if self.liq_max_dist_atr is not None and self.liq_max_dist_atr <= 0:
            raise ValueError("liq_max_dist_atr must be > 0 or None")
        for name in (
            "doji_tol_ticks",
            "max_bars_sweep_to_tap",
            "tap_tol_ticks",
            "max_bars_tap_to_entry",
            "sl_buffer_ticks",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be >= 0")
        if self.min_body_ticks < 1:
            raise ValueError("min_body_ticks must be >= 1")
        if self.rr <= 0:
            raise ValueError("rr must be > 0")
        if self.max_trades_per_zone < 1:
            raise ValueError("max_trades_per_zone must be >= 1")
```

`src/lsdtrader/core/events.py`:

```python
"""Named rule events: every rejected or killed object leaves one."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Event:
    bar_index: int
    kind: str
    detail: dict[str, object] = field(default_factory=dict)
    side: str = ""


class EventLog:
    """Collects events; the engine sets `bar_index` before processing each bar."""

    def __init__(self) -> None:
        self.events: list[Event] = []
        self.bar_index = -1

    def emit(self, kind: str, **detail: object) -> None:
        self.events.append(Event(self.bar_index, kind, dict(detail)))

    def kinds(self) -> list[str]:
        return [e.kind for e in self.events]

    def drain(self) -> list[Event]:
        out, self.events = self.events, []
        return out
```

- [ ] **Step 6: Run tests and all checks**

Run: `pytest tests/core -v && ruff check . && ruff format --check . && mypy`
Expected: 9 passed; `All checks passed!`; `Success: no issues found`.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Scaffold package with tick bars, config and event log

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: M1 swing lows

**Files:**
- Create: `src/lsdtrader/strategy/swings.py`
- Test: `tests/strategy/test_swings.py`

**Interfaces:**
- Consumes: `TickBar`, test helper `bars_from_lows`.
- Produces: `Swing(idx: int, price: int)`; `is_swing_low(bars, c, n) -> bool`; `confirmed_swing_low(bars, n) -> Swing | None` (the swing confirmed by the newest bar, sitting `n` bars back).

- [ ] **Step 1: Write the failing tests**

`tests/strategy/test_swings.py`:

```python
from lsdtrader.strategy.swings import Swing, confirmed_swing_low, is_swing_low
from tests.helpers import bars_from_lows


def test_simple_swing_low_confirmed_one_bar_later() -> None:
    bars = bars_from_lows(5, 3, 5)
    assert confirmed_swing_low(bars[:2], 1) is None
    assert confirmed_swing_low(bars, 1) == Swing(1, 3)


def test_equal_lows_rightmost_bar_is_the_swing() -> None:
    # Scenario 1
    bars = bars_from_lows(5, 3, 3, 5)
    assert [c for c in range(len(bars)) if is_swing_low(bars, c, 1)] == [2]


def test_right_side_must_be_strictly_higher() -> None:
    assert confirmed_swing_low(bars_from_lows(5, 3, 3), 1) is None


def test_pivot_length_two() -> None:
    bars = bars_from_lows(6, 5, 3, 4, 5)
    assert confirmed_swing_low(bars, 2) == Swing(2, 3)
    assert not is_swing_low(bars_from_lows(6, 5, 3, 2, 5), 2, 2)


def test_not_enough_bars() -> None:
    assert confirmed_swing_low(bars_from_lows(3), 1) is None
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/strategy/test_swings.py -v`
Expected: `ModuleNotFoundError: No module named 'lsdtrader.strategy.swings'`.

- [ ] **Step 3: Implement**

`src/lsdtrader/strategy/swings.py`:

```python
"""M1 · Swing lows (Strategy Spec §3). Swing highs are swing lows of mirrored bars."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from lsdtrader.core.bar import TickBar


@dataclass(frozen=True, slots=True)
class Swing:
    idx: int
    price: int


def is_swing_low(bars: Sequence[TickBar], c: int, n: int) -> bool:
    """True if bar `c` is a swing low with `n` bars on each side.

    Left side may be equal, right side must be strictly higher, so in a run of
    identical lows only the rightmost bar is a swing.
    """
    if c - n < 0 or c + n >= len(bars):
        return False
    low = bars[c].low
    for k in range(1, n + 1):
        if bars[c - k].low < low or bars[c + k].low <= low:
            return False
    return True


def confirmed_swing_low(bars: Sequence[TickBar], n: int) -> Swing | None:
    """The swing low that the newest bar confirms, if any (it sits `n` bars back)."""
    c = len(bars) - 1 - n
    if is_swing_low(bars, c, n):
        return Swing(c, bars[c].low)
    return None
```

- [ ] **Step 4: Run tests and checks**

Run: `pytest tests/strategy/test_swings.py -v && ruff check . && mypy`
Expected: 5 passed, checks clean.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "Add M1 swing low detection

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: M2 candidates P, L0, H2 and BOS

**Files:**
- Create: `src/lsdtrader/strategy/structure.py`
- Test: `tests/strategy/test_structure.py`

**Interfaces:**
- Consumes: `TickBar`, `StrategyConfig` (`bos_confirm`, `bos_max_bars`), `EventLog`, `Swing`, `confirmed_swing_low`.
- Produces: `Bos(p_idx, p_low, l0_idx, h2, bos_idx, known_idx)` (all `int`); `StructureTracker(cfg, log)` with `.update(bars, new_swing: Swing | None) -> list[Bos]` called once per newest bar, and `.candidates -> int`. Events: `cand_undercut`, `cand_expired`, `cand_no_lower_low`.

Rules implemented (Strategy Spec §4): L0 is the nearest earlier swing low **at or below** P (equal low counts; found with a monotonic stack); H2 is the highest high of the bars **after** L0 up to P; existing candidates are checked undercut first, then BOS, then expiry; a newly confirmed swing is BOS-checked on the bars between P and its confirmation.

- [ ] **Step 1: Write the failing tests**

`tests/strategy/test_structure.py`:

```python
from collections.abc import Sequence

from lsdtrader.core.bar import TickBar
from lsdtrader.core.config import StrategyConfig
from lsdtrader.core.events import EventLog
from lsdtrader.strategy.structure import Bos, StructureTracker
from lsdtrader.strategy.swings import confirmed_swing_low
from tests.helpers import make_bars


def run(bars: Sequence[TickBar], cfg: StrategyConfig | None = None) -> tuple[list[Bos], EventLog]:
    cfg = cfg or StrategyConfig()
    log = EventLog()
    tracker = StructureTracker(cfg, log)
    found: list[Bos] = []
    for i in range(len(bars)):
        log.bar_index = i
        window = bars[: i + 1]
        found += tracker.update(window, confirmed_swing_low(window, cfg.piv_len))
    return found, log


# Scenario 2 + 5: zigzag inside the leg down, P undercuts the zigzag low.
ZIGZAG = make_bars(
    (105, 106, 102, 103),  # 0
    (103, 104, 100, 101),  # 1 L0 = 100
    (101, 120, 101, 119),  # 2
    (119, 130, 118, 128),  # 3 H2 = 130
    (128, 129, 115, 116),  # 4 l = 115 (swing, candidate with H2 130)
    (117, 122, 117, 121),  # 5 h = 122
    (121, 121, 108, 109),  # 6 P = 108, undercuts l
    (110, 125, 110, 124),  # 7 close above h but not above H2
    (124, 133, 123, 131),  # 8 close above H2 -> BOS for P
)


def test_bos_level_is_h2_not_the_zigzag_high() -> None:
    found, _ = run(ZIGZAG)
    assert found == [Bos(p_idx=6, p_low=108, l0_idx=1, h2=130, bos_idx=8, known_idx=8)]


def test_undercut_candidate_dies_and_new_low_takes_over() -> None:
    _, log = run(ZIGZAG)
    undercuts = [e for e in log.events if e.kind == "cand_undercut"]
    assert [(e.bar_index, e.detail["p_idx"]) for e in undercuts] == [(6, 4)]


def test_no_lower_low_means_no_candidate() -> None:
    # Scenario 3
    bars = make_bars(
        (110, 111, 105, 106), (106, 107, 100, 101), (102, 108, 102, 107), (107, 200, 106, 199)
    )
    found, log = run(bars)
    assert found == []
    assert "cand_no_lower_low" in log.kinds()


def test_equal_low_counts_as_higher_low() -> None:
    # Scenario 4: P equals L0 -> L0 is the equal swing, BOS over the bounce high (120), not 139.
    bars = make_bars(
        (100, 101, 96, 97),  # 0
        (97, 98, 95, 96),  # 1 L-1 = 95
        (101, 140, 101, 139),  # 2 H1 = 140
        (139, 139, 100, 101),  # 3 L0 = 100
        (102, 120, 102, 119),  # 4 H2 = 120
        (119, 119, 100, 101),  # 5 P = 100 (equal low)
        (102, 121, 102, 120),  # 6 close == 120, not above
        (120, 125, 119, 124),  # 7 BOS
    )
    found, _ = run(bars)
    assert Bos(p_idx=5, p_low=100, l0_idx=3, h2=120, bos_idx=7, known_idx=7) in found


def test_wick_mode_breaks_on_high() -> None:
    bars = ZIGZAG[:8] + make_bars((124, 131, 123, 129), start=8)
    assert run(bars)[0] == []
    found, _ = run(bars, StrategyConfig(bos_confirm="wick"))
    assert [b.p_idx for b in found] == [6]


def test_bos_max_bars_expires_candidate() -> None:
    found, log = run(ZIGZAG, StrategyConfig(bos_max_bars=1))
    assert found == []
    assert "cand_expired" in log.kinds()


def test_same_bar_undercut_and_close_above_h2_is_no_bos() -> None:
    # Spec §4.2 rule 3: the undercut wins.
    bars = ZIGZAG[:8] + make_bars((110, 135, 107, 134), start=8)
    found, log = run(bars)
    assert all(b.p_idx != 6 for b in found)
    assert any(e.kind == "cand_undercut" and e.detail["p_idx"] == 6 for e in log.events)
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/strategy/test_structure.py -v`
Expected: `ModuleNotFoundError: No module named 'lsdtrader.strategy.structure'`.

- [ ] **Step 3: Implement**

`src/lsdtrader/strategy/structure.py`:

```python
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
```

- [ ] **Step 4: Run tests and checks**

Run: `pytest tests/strategy/test_structure.py -v && ruff check . && mypy`
Expected: 7 passed, checks clean.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "Add M2 structure tracking: P candidates, L0, H2 and BOS

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: M3 zones

**Files:**
- Create: `src/lsdtrader/strategy/zones.py`
- Test: `tests/strategy/test_zones.py`

**Interfaces:**
- Consumes: `TickBar`, `StrategyConfig` (`zone_lookback`, `doji_tol_ticks`, `zone_mode`, `extra_zones`, `zone_kill`, `max_trades_per_zone`), `EventLog`, `Bos`.
- Produces:
  - `Zone` (mutable dataclass: `zone_id, o_idx, top, bot, p_idx, created_idx, kind, pending, state, trades`; `.live`; `.overlaps(bar)`), `ZoneState = Literal["building", "left", "destroyed", "dead", "consumed"]`.
  - `is_opposing(bar, doji_tol_ticks) -> bool`, `find_origin(bars, p_idx, lookback, doji_tol_ticks) -> int`.
  - `ZoneBook(cfg, log)` with `.create(bars, bos) -> list[Zone]` (replays new zones up to the newest bar), `.update(bars)` (advance live zones by the newest bar), `.live() -> list[Zone]`, `.consume(zone)`.
  - Events: `zone_created`, `zone_relocation`, `zone_died_building`, `zone_left`, `zone_destroyed_close`, `zone_destroyed_wick`.

Order inside one build step (Spec §5.2): relocation, else fix geometry with F, then death (`close < bot`), then "left" (`low > top`). After the zone is left only destruction applies (Spec §5.4).

- [ ] **Step 1: Write the failing tests**

`tests/strategy/test_zones.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/strategy/test_zones.py -v`
Expected: `ModuleNotFoundError: No module named 'lsdtrader.strategy.zones'`.

- [ ] **Step 3: Implement**

`src/lsdtrader/strategy/zones.py`:

```python
"""M3 · Demand zones (Strategy Spec §5): origin, relocation, geometry, destruction."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from lsdtrader.core.bar import TickBar
from lsdtrader.core.config import StrategyConfig
from lsdtrader.core.events import EventLog
from lsdtrader.strategy.structure import Bos

ZoneState = Literal["building", "left", "destroyed", "dead", "consumed"]


@dataclass(slots=True)
class Zone:
    zone_id: int
    o_idx: int  # origin bar O
    top: int
    bot: int
    p_idx: int  # swing low whose BOS created the zone
    created_idx: int
    kind: Literal["normal", "accuracy"] = "normal"
    pending: bool = True  # geometry waits for the follow-up bar F
    state: ZoneState = "building"
    trades: int = 0

    @property
    def live(self) -> bool:
        return self.state in ("building", "left")

    def overlaps(self, bar: TickBar) -> bool:
        return bar.low <= self.top and bar.high >= self.bot


def is_opposing(bar: TickBar, doji_tol_ticks: int) -> bool:
    """Bearish or doji: the bar type that can form a demand zone."""
    return bar.close < bar.open or abs(bar.close - bar.open) <= doji_tol_ticks


def find_origin(bars: Sequence[TickBar], p_idx: int, lookback: int, doji_tol_ticks: int) -> int:
    """First opposing bar searching back from P (inclusive); P itself if none (§5.1)."""
    for k in range(p_idx, max(p_idx - lookback, -1), -1):
        if is_opposing(bars[k], doji_tol_ticks):
            return k
    return p_idx


class ZoneBook:
    def __init__(self, cfg: StrategyConfig, log: EventLog) -> None:
        self._cfg = cfg
        self._log = log
        self._zones: list[Zone] = []
        self._next_id = 0

    def live(self) -> list[Zone]:
        return [z for z in self._zones if z.live]

    def create(self, bars: Sequence[TickBar], bos: Bos) -> list[Zone]:
        """Create the zone(s) for a BOS and replay them up to the newest bar."""
        o = find_origin(bars, bos.p_idx, self._cfg.zone_lookback, self._cfg.doji_tol_ticks)
        created = [self._new(bars, o, bos)]
        if self._cfg.extra_zones != "none":
            created += self._extra(bars, bos, created)
        return created

    def update(self, bars: Sequence[TickBar]) -> None:
        """Advance every live zone by the newest bar, then drop finished zones."""
        k = len(bars) - 1
        for z in self._zones:
            if z.live:
                self._step(bars, z, k)
        self._zones = [z for z in self._zones if z.live]

    def consume(self, zone: Zone) -> None:
        zone.trades += 1
        if zone.trades >= self._cfg.max_trades_per_zone:
            zone.state = "consumed"

    # -- internals ---------------------------------------------------------

    def _new(self, bars: Sequence[TickBar], o: int, bos: Bos) -> Zone:
        ob = bars[o]
        zone = Zone(self._next_id, o, ob.high, ob.low, bos.p_idx, len(bars) - 1)
        self._next_id += 1
        self._log.emit("zone_created", zone_id=zone.zone_id, o_idx=o, p_idx=bos.p_idx)
        for k in range(o + 1, len(bars)):
            if not zone.live:
                break
            self._step(bars, zone, k)
        self._zones.append(zone)
        return zone

    def _extra(self, bars: Sequence[TickBar], bos: Bos, created: list[Zone]) -> list[Zone]:
        """Non-overlapping opposing bars between P and the BOS bar (§5.5)."""
        tol = self._cfg.doji_tol_ticks
        ks = [k for k in range(bos.p_idx + 1, bos.bos_idx) if is_opposing(bars[k], tol)]
        if self._cfg.extra_zones == "last":
            ks.reverse()
        extra: list[Zone] = []
        for k in ks:
            if any(z.overlaps(bars[k]) or z.o_idx == k for z in created + extra):
                continue
            extra.append(self._new(bars, k, bos))
            if self._cfg.extra_zones == "last":
                break
        return extra

    def _step(self, bars: Sequence[TickBar], z: Zone, k: int) -> None:
        if z.state == "building":
            self._build_step(bars, z, k)
        else:
            self._destroy_step(bars[k], z)

    def _build_step(self, bars: Sequence[TickBar], z: Zone, k: int) -> None:
        bar = bars[k]
        if is_opposing(bar, self._cfg.doji_tol_ticks) and z.overlaps(bar):
            z.o_idx, z.top, z.bot = k, bar.high, bar.low
            z.kind, z.pending = "normal", True
            self._log.emit("zone_relocation", zone_id=z.zone_id, o_idx=k)
        elif z.pending:
            self._fix_geometry(bars[z.o_idx], bar, z)
        if bar.close < z.bot:
            z.state = "dead"
            self._log.emit("zone_died_building", zone_id=z.zone_id)
        elif bar.low > z.top:
            z.state = "left"
            self._log.emit("zone_left", zone_id=z.zone_id)

    def _fix_geometry(self, o: TickBar, f: TickBar, z: Zone) -> None:
        if self._cfg.zone_mode == "normal" or f.high > o.high:
            z.kind, z.top, z.bot = "normal", o.high, o.low
        else:
            z.kind, z.top, z.bot = "accuracy", o.body_top, min(o.low, f.low)
        z.pending = False

    def _destroy_step(self, bar: TickBar, z: Zone) -> None:
        if self._cfg.zone_kill == "close_inside":
            if bar.close <= z.top:
                self._destroy(z, "close")
            elif bar.low < z.bot:
                self._destroy(z, "wick")
        elif bar.close < z.bot:
            self._destroy(z, "close")

    def _destroy(self, z: Zone, reason: str) -> None:
        z.state = "destroyed"
        self._log.emit(f"zone_destroyed_{reason}", zone_id=z.zone_id)
```

- [ ] **Step 4: Run tests and checks**

Run: `pytest tests/strategy/test_zones.py -v && ruff check . && mypy`
Expected: 23 passed, checks clean.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "Add M3 zones: origin, relocation, geometry, destruction, extra zones

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: M4 liquidity

**Files:**
- Create: `src/lsdtrader/strategy/liquidity.py`
- Test: `tests/strategy/test_liquidity.py`

**Interfaces:**
- Consumes: `TickBar`, `StrategyConfig` (`liq_max_dist_atr`), `Bos`, `Zone`.
- Produces: `Liquidity(liq_id, idx, price, bos_idx)`; `LiquidityBook` with `.add(bos) -> Liquidity` and `.swept_by(bar) -> list[Liquidity]` (removes swept liquidity for good); `match_zones(liq, zones, atr, cfg) -> tuple[list[Zone], str | None]`; `NO_SETUP_REASONS = ("no_zone_below", "zone_not_left", "liq_before_zone", "too_far")`.

- [ ] **Step 1: Write the failing tests**

`tests/strategy/test_liquidity.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/strategy/test_liquidity.py -v`
Expected: `ModuleNotFoundError: No module named 'lsdtrader.strategy.liquidity'`.

- [ ] **Step 3: Implement**

`src/lsdtrader/strategy/liquidity.py`:

```python
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
```

- [ ] **Step 4: Run tests and checks**

Run: `pytest tests/strategy/test_liquidity.py -v && ruff check . && mypy`
Expected: 6 passed, checks clean.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "Add M4 liquidity book and zone matching

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: ATR and M5 setups (sweep → tap → entry, stop, target)

**Files:**
- Create: `src/lsdtrader/strategy/atr.py`, `src/lsdtrader/strategy/setups.py`
- Test: `tests/strategy/test_atr.py`, `tests/strategy/test_setups.py`

**Interfaces:**
- Consumes: `TickBar`, `StrategyConfig` (`max_bars_sweep_to_tap`, `tap_tol_ticks`, `max_bars_tap_to_entry`, `entry_trigger`, `min_body_ticks`, `sl_buffer_ticks`, `sl_mode`, `rr`), `EventLog`, `Liquidity`, `Zone`, `ZoneBook.consume`.
- Produces:
  - `Atr(length)` with `.update(bar) -> float | None` (Wilder, `None` until `length` bars).
  - `Setup` (mutable), `Entry` (frozen: `setup_id, entry_idx, entry, stop, target, zone_id, zone_top, zone_bot, zone_o_idx, liq_idx, liq_price, sweep_idx, tap_idx, features`).
  - `SetupTracker(cfg, log, zones)` with `.start(zone, liq, sweep_idx, atr) -> Setup | None` (one running setup per zone) and `.update(bars) -> list[Entry]` (call after zones were updated for the newest bar).
  - Events: `setup_started`, `tap`, `no_tap`, `no_entry`, `setup_zone_gone`, `entry`.
  - `features` keys: `zone_height_ticks, zone_kind, liq_dist_ticks, liq_dist_atr, bars_sweep_to_tap, bars_tap_to_entry, stop_ticks`.

- [ ] **Step 1: Write the failing tests**

`tests/strategy/test_atr.py`:

```python
from lsdtrader.strategy.atr import Atr
from tests.helpers import make_bars


def test_wilder_atr() -> None:
    atr = Atr(3)
    bars = make_bars((10, 12, 9, 11), (11, 13, 10, 12), (12, 15, 12, 14), (14, 14, 8, 9))
    assert [atr.update(b) for b in bars] == [None, None, 3.0, 4.0]
```

`tests/strategy/test_setups.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/strategy/test_atr.py tests/strategy/test_setups.py -v`
Expected: `ModuleNotFoundError` for `lsdtrader.strategy.atr` and `lsdtrader.strategy.setups`.

- [ ] **Step 3: Implement**

`src/lsdtrader/strategy/atr.py`:

```python
"""Average true range in ticks, Wilder smoothing (same as TradingView `ta.atr`)."""

from __future__ import annotations

from lsdtrader.core.bar import TickBar


class Atr:
    def __init__(self, length: int) -> None:
        self._length = length
        self._prev_close: int | None = None
        self._seed: list[int] = []
        self.value: float | None = None

    def update(self, bar: TickBar) -> float | None:
        if self._prev_close is None:
            tr = bar.high - bar.low
        else:
            tr = max(
                bar.high - bar.low,
                abs(bar.high - self._prev_close),
                abs(bar.low - self._prev_close),
            )
        self._prev_close = bar.close
        if self.value is None:
            self._seed.append(tr)
            if len(self._seed) == self._length:
                self.value = sum(self._seed) / self._length
        else:
            self.value = (self.value * (self._length - 1) + tr) / self._length
        return self.value
```

`src/lsdtrader/strategy/setups.py`:

```python
"""M5 · Sweep → tap → entry, plus stop and target (Strategy Spec §7, §8.1)."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

from lsdtrader.core.bar import TickBar
from lsdtrader.core.config import StrategyConfig
from lsdtrader.core.events import EventLog
from lsdtrader.strategy.liquidity import Liquidity
from lsdtrader.strategy.zones import Zone, ZoneBook


@dataclass(slots=True)
class Setup:
    setup_id: int
    zone: Zone
    liq: Liquidity
    sweep_idx: int
    atr: float | None
    tap_idx: int | None = None


@dataclass(frozen=True, slots=True)
class Entry:
    setup_id: int
    entry_idx: int
    entry: int
    stop: int
    target: int
    zone_id: int
    zone_top: int
    zone_bot: int
    zone_o_idx: int
    liq_idx: int
    liq_price: int
    sweep_idx: int
    tap_idx: int
    features: dict[str, object] = field(default_factory=dict)


class SetupTracker:
    def __init__(self, cfg: StrategyConfig, log: EventLog, zones: ZoneBook) -> None:
        self._cfg = cfg
        self._log = log
        self._zones = zones
        self._pending: list[Setup] = []
        self._next_id = 0

    @property
    def pending(self) -> list[Setup]:
        return list(self._pending)

    def start(self, zone: Zone, liq: Liquidity, sweep_idx: int, atr: float | None) -> Setup | None:
        """Start a setup unless the zone already has one running."""
        if any(s.zone is zone for s in self._pending):
            return None
        setup = Setup(self._next_id, zone, liq, sweep_idx, atr)
        self._next_id += 1
        self._pending.append(setup)
        self._log.emit(
            "setup_started", setup_id=setup.setup_id, zone_id=zone.zone_id, liq_idx=liq.idx
        )
        return setup

    def update(self, bars: Sequence[TickBar]) -> list[Entry]:
        """Advance pending setups by the newest bar (zones must already be updated)."""
        i = len(bars) - 1
        entries: list[Entry] = []
        keep: list[Setup] = []
        for s in self._pending:
            result = self._advance(bars, s, i)
            if isinstance(result, Entry):
                entries.append(result)
            elif result:
                keep.append(s)
        self._pending = keep
        return entries

    def _advance(self, bars: Sequence[TickBar], s: Setup, i: int) -> Entry | bool:
        """Returns an Entry, True to keep waiting, or False to drop the setup."""
        cfg, bar, z = self._cfg, bars[i], s.zone
        if z.state != "left":
            self._log.emit("setup_zone_gone", setup_id=s.setup_id, zone_state=z.state)
            return False
        if s.tap_idx is None:
            if bar.low <= z.top + cfg.tap_tol_ticks:
                s.tap_idx = i
                self._log.emit("tap", setup_id=s.setup_id)
            elif i - s.sweep_idx >= cfg.max_bars_sweep_to_tap:
                self._log.emit("no_tap", setup_id=s.setup_id)
                return False
            else:
                return True
        if self._triggered(bars, s, i):
            return self._enter(bars, s, i)
        if i - s.tap_idx >= cfg.max_bars_tap_to_entry:
            self._log.emit("no_entry", setup_id=s.setup_id)
            return False
        return True

    def _triggered(self, bars: Sequence[TickBar], s: Setup, i: int) -> bool:
        bar = bars[i]
        if bar.close <= bar.open:
            return False
        trigger = self._cfg.entry_trigger
        if trigger == "above_tap_high":
            assert s.tap_idx is not None
            return bar.close > bars[s.tap_idx].high
        if trigger == "above_liq":
            return bar.close > s.liq.price
        if trigger == "min_body":
            return bar.close - bar.open >= self._cfg.min_body_ticks
        return True

    def _enter(self, bars: Sequence[TickBar], s: Setup, i: int) -> Entry:
        cfg, z = self._cfg, s.zone
        assert s.tap_idx is not None
        entry = bars[i].close
        if cfg.sl_mode == "zone_bottom":
            stop = z.bot
        elif cfg.sl_mode == "zone_mid":
            stop = (z.top + z.bot) // 2
        else:
            stop = min(b.low for b in bars[s.sweep_idx : i + 1])
        stop -= cfg.sl_buffer_ticks
        risk = entry - stop
        target = entry + math.ceil(cfg.rr * risk)
        dist = s.liq.price - z.top
        features: dict[str, object] = {
            "zone_height_ticks": z.top - z.bot,
            "zone_kind": z.kind,
            "liq_dist_ticks": dist,
            "liq_dist_atr": dist / s.atr if s.atr else None,
            "bars_sweep_to_tap": s.tap_idx - s.sweep_idx,
            "bars_tap_to_entry": i - s.tap_idx,
            "stop_ticks": risk,
        }
        result = Entry(
            s.setup_id,
            i,
            entry,
            stop,
            target,
            z.zone_id,
            z.top,
            z.bot,
            z.o_idx,
            s.liq.idx,
            s.liq.price,
            s.sweep_idx,
            s.tap_idx,
            features,
        )
        self._zones.consume(z)
        self._log.emit("entry", setup_id=s.setup_id, zone_id=z.zone_id)
        return result
```

- [ ] **Step 4: Run tests and checks**

Run: `pytest tests/strategy/test_atr.py tests/strategy/test_setups.py -v && ruff check . && mypy`
Expected: 11 passed, checks clean.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "Add ATR and M5 setups with stop and target

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: LsdStrategy composition, mirror, no-lookahead, determinism

**Files:**
- Create: `src/lsdtrader/strategy/lsd.py`
- Test: `tests/strategy/test_lsd.py`, `tests/strategy/test_properties.py`

**Interfaces:**
- Consumes: everything above.
- Produces (used by Plan 2b):
  - `Signal` (frozen: `side, bar_index, ts, entry, stop, target, setup_id, zone_id, zone_top, zone_bot, zone_o_idx, liq_idx, liq_price, sweep_idx, tap_idx, features`), prices in real ticks for both sides.
  - `SideEngine(cfg)` with `.on_bar(bar) -> list[Entry]` and public `.log, .bars, .structure, .zones, .liquidity, .setups` (for `lsd inspect` in Plan 2d).
  - `LsdStrategy(cfg: StrategyConfig | None = None)` with `.on_bar(bar: TickBar) -> list[Signal]` (raises `ValueError` if `bar.ts` is not after the previous bar) and `.drain_events() -> list[Event]` (events tagged `side="long"`/`"short"`, sorted by bar index).

Per-bar order in `SideEngine.on_bar` (Design §5.1; the broker step comes in Plan 2b): ATR → zone lifecycle → swing confirmation → structure/BOS → create zones + register liquidity → sweeps → setups.

- [ ] **Step 1: Write the failing tests**

`tests/strategy/test_lsd.py`:

```python
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
```

`tests/strategy/test_properties.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/strategy/test_lsd.py tests/strategy/test_properties.py -v`
Expected: `ModuleNotFoundError: No module named 'lsdtrader.strategy.lsd'`.

- [ ] **Step 3: Implement**

`src/lsdtrader/strategy/lsd.py`:

```python
"""The LSD strategy: M1–M5 composed, long side plus mirrored short side."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Literal

from lsdtrader.core.bar import TickBar
from lsdtrader.core.config import StrategyConfig
from lsdtrader.core.events import Event, EventLog
from lsdtrader.strategy.atr import Atr
from lsdtrader.strategy.liquidity import LiquidityBook, match_zones
from lsdtrader.strategy.setups import Entry, SetupTracker
from lsdtrader.strategy.structure import StructureTracker
from lsdtrader.strategy.swings import confirmed_swing_low
from lsdtrader.strategy.zones import ZoneBook

Side = Literal["long", "short"]


@dataclass(frozen=True, slots=True)
class Signal:
    """An entry decision in real tick prices. The broker fills at `entry` (bar close)."""

    side: Side
    bar_index: int
    ts: datetime
    entry: int
    stop: int
    target: int
    setup_id: str
    zone_id: str
    zone_top: int
    zone_bot: int
    zone_o_idx: int
    liq_idx: int
    liq_price: int
    sweep_idx: int
    tap_idx: int
    features: dict[str, object] = field(default_factory=dict)


class SideEngine:
    """Long-side rules. The short side is this same class fed with mirrored bars."""

    def __init__(self, cfg: StrategyConfig) -> None:
        self.cfg = cfg
        self.log = EventLog()
        self.bars: list[TickBar] = []
        self._atr = Atr(cfg.atr_len)
        self.structure = StructureTracker(cfg, self.log)
        self.zones = ZoneBook(cfg, self.log)
        self.liquidity = LiquidityBook()
        self.setups = SetupTracker(cfg, self.log, self.zones)

    def on_bar(self, bar: TickBar) -> list[Entry]:
        self.bars.append(bar)
        i = len(self.bars) - 1
        self.log.bar_index = i
        atr = self._atr.update(bar)
        self.zones.update(self.bars)
        swing = confirmed_swing_low(self.bars, self.cfg.piv_len)
        for bos in self.structure.update(self.bars, swing):
            self.log.emit("bos", p_idx=bos.p_idx, bos_idx=bos.bos_idx, h2=bos.h2)
            self.zones.create(self.bars, bos)
            self.liquidity.add(bos)
        for liq in self.liquidity.swept_by(bar):
            zones, reason = match_zones(liq, self.zones.live(), atr, self.cfg)
            if reason is not None:
                self.log.emit("sweep_no_setup", liq_idx=liq.idx, reason=reason)
            for z in zones:
                self.setups.start(z, liq, i, atr)
        return self.setups.update(self.bars)


class LsdStrategy:
    """One instance per instrument. Feed closed 5-minute bars in time order."""

    def __init__(self, cfg: StrategyConfig | None = None) -> None:
        self.cfg = cfg or StrategyConfig()
        self.long = SideEngine(self.cfg)
        self.short = SideEngine(self.cfg)
        self._last_ts: datetime | None = None

    def on_bar(self, bar: TickBar) -> list[Signal]:
        if self._last_ts is not None and bar.ts <= self._last_ts:
            raise ValueError(f"bar at {bar.ts} is not after {self._last_ts}")
        self._last_ts = bar.ts
        signals = [self._signal("long", e, bar) for e in self.long.on_bar(bar)]
        signals += [self._signal("short", e, bar) for e in self.short.on_bar(bar.mirrored())]
        return signals

    def drain_events(self) -> list[Event]:
        events = [replace(e, side="long") for e in self.long.log.drain()]
        events += [replace(e, side="short") for e in self.short.log.drain()]
        return sorted(events, key=lambda e: e.bar_index)

    @staticmethod
    def _signal(side: Side, e: Entry, bar: TickBar) -> Signal:
        s = 1 if side == "long" else -1
        top, bot = (e.zone_top, e.zone_bot) if s == 1 else (-e.zone_bot, -e.zone_top)
        return Signal(
            side,
            e.entry_idx,
            bar.ts,
            s * e.entry,
            s * e.stop,
            s * e.target,
            f"{side}-{e.setup_id}",
            f"{side}-{e.zone_id}",
            top,
            bot,
            e.zone_o_idx,
            e.liq_idx,
            s * e.liq_price,
            e.sweep_idx,
            e.tap_idx,
            dict(e.features),
        )
```

- [ ] **Step 4: Run the whole suite with coverage and all checks**

Run: `pytest --cov=lsdtrader --cov-report=term-missing --cov-fail-under=90 && ruff check . && ruff format --check . && mypy`
Expected: 70 passed, total coverage ≥ 90 % (prototype: 99 %), all checks clean. The property tests use a seeded random walk (seed 7, 3000 bars) that yields 58 signals on both sides, 9 of them inside the first 400 bars used by the no-lookahead test.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "Compose LSD strategy with mirrored short side and property tests

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
