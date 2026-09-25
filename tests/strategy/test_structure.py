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
