from datetime import UTC, datetime
from decimal import Decimal

import pytest

from lsdtrader.core.calendar import is_last_bar_before_break
from lsdtrader.core.instrument import get_instrument


def test_tick_conversion_is_exact() -> None:
    es, cl, si = get_instrument("ES"), get_instrument("cl"), get_instrument("SI")
    assert es.to_ticks(7626.5) == 30506
    assert cl.to_ticks("82.48") == 8248
    assert si.to_ticks(31.125) == 6225
    assert es.to_price(30506) == Decimal("7626.50")


def test_off_grid_price_rejected() -> None:
    with pytest.raises(ValueError):
        get_instrument("ES").to_ticks(7626.3)


def test_unknown_instrument() -> None:
    with pytest.raises(KeyError):
        get_instrument("XYZ")


def test_micro_and_mini_share_tick_size() -> None:
    for mini, micro in [("ES", "MES"), ("NQ", "MNQ"), ("GC", "MGC"), ("CL", "MCL"), ("SI", "SIL")]:
        assert get_instrument(mini).tick_size == get_instrument(micro).tick_size


@pytest.mark.parametrize(
    ("utc", "expected"),
    [
        (datetime(2024, 1, 8, 21, 55, tzinfo=UTC), True),  # Mon 15:55 CT (winter, UTC-6)
        (datetime(2024, 1, 8, 21, 50, tzinfo=UTC), False),  # Mon 15:50 CT
        (datetime(2024, 7, 8, 20, 55, tzinfo=UTC), True),  # Mon 15:55 CT (summer, UTC-5)
        (datetime(2024, 7, 8, 21, 55, tzinfo=UTC), False),  # Mon 16:55 CT: inside the halt
        (datetime(2024, 1, 12, 21, 55, tzinfo=UTC), True),  # Fri 15:55 CT: weekend close
        (datetime(2024, 1, 7, 21, 55, tzinfo=UTC), False),  # Sun: no trading at that time
    ],
)
def test_last_bar_before_break(utc: datetime, expected: bool) -> None:
    assert is_last_bar_before_break(utc) is expected


def test_cfd_specs_and_aliases() -> None:
    spx = get_instrument("SPXUSD")
    assert spx.tick_size == Decimal("0.001") and spx.spread_ticks == 400
    assert spx.commission_per_side == 0.0 and spx.slippage_ticks == 0
    assert get_instrument("USA500.IDX/USD") is spx
    assert get_instrument("usatechidxusd").root == "NSXUSD"
