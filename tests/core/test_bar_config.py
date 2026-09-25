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
    assert cfg.max_bars_sweep_to_tap == 12  # one hour of 5-minute bars
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
