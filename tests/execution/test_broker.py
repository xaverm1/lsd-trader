from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

import pytest

from lsdtrader.core.bar import TickBar
from lsdtrader.core.events import EventLog
from lsdtrader.core.instrument import Instrument
from lsdtrader.execution.broker import ExecutionConfig, SimBroker, Trade
from lsdtrader.strategy.lsd import Signal

# 1 tick = 10 USD, commission 1 USD per side, 1 tick slippage
INST = Instrument("TEST", Decimal("0.25"), tick_value=10.0, commission_per_side=1.0)
T = datetime(2024, 1, 8, 15, 0, tzinfo=UTC)  # Monday 09:00 CT, far from the halt


def signal(side: str = "long", entry: int = 100, stop: int = 90, target: int = 140) -> Signal:
    return Signal(side, 0, T, entry, stop, target, f"{side}-0", f"{side}-0", 0, 0, 0, 0, 0, 0, 0)  # type: ignore[arg-type]


def bar(o: int, h: int, lo: int, c: int, minute: int = 5) -> TickBar:
    return TickBar(T + timedelta(minutes=minute), o, h, lo, c)


def run(
    sig: Signal,
    minutes: Sequence[TickBar],
    cfg: ExecutionConfig | None = None,
    five: TickBar | None = None,
) -> tuple[list[Trade], SimBroker, EventLog]:
    log = EventLog()
    broker = SimBroker(INST, cfg or ExecutionConfig(), log)
    broker.submit([sig], bar(100, 100, 100, 100, minute=0))
    five = five or TickBar(
        minutes[0].ts,
        minutes[0].open,
        max(m.high for m in minutes),
        min(m.low for m in minutes),
        minutes[-1].close,
    )
    return broker.on_bar(five, minutes), broker, log


def test_take_profit_net_and_gross_r() -> None:
    (t,), _, _ = run(signal(), [bar(100, 141, 99, 140)])
    assert (t.exit_reason, t.entry_fill, t.exit_fill, t.qty) == ("tp", 101, 140, 1.0)
    assert t.gross_r == pytest.approx(4.0)
    # pnl = (140 - 101) * 10 - 2 * 1 = 388 USD on 100 USD risk
    assert t.net_r == pytest.approx(3.88)
    assert t.cost_r == pytest.approx(0.12)
    assert t.mfe_r == pytest.approx(4.0)


def test_stop_loss_with_slippage() -> None:
    (t,), _, _ = run(signal(), [bar(100, 105, 89, 92)])
    assert (t.exit_reason, t.exit_raw, t.exit_fill) == ("sl", 90, 89)
    assert t.net_r == pytest.approx(-1.22)  # (89 - 101) * 10 - 2 = -122
    assert t.mae_r == pytest.approx(1.0)


def test_stop_and_target_in_same_minute_assumes_stop() -> None:
    # Scenario 15
    (t,), _, _ = run(signal(), [bar(100, 141, 89, 120)])
    assert t.exit_reason == "sl"


def test_minutes_decide_the_order_inside_a_five_minute_bar() -> None:
    minutes = [bar(100, 141, 99, 139, minute=1), bar(139, 139, 85, 86, minute=2)]
    (t,), _, _ = run(signal(), minutes)
    assert t.exit_reason == "tp"


def test_gap_through_stop_fills_at_open() -> None:
    (t,), _, _ = run(signal(), [bar(80, 85, 78, 84)])
    assert (t.exit_reason, t.exit_raw, t.exit_fill) == ("sl", 80, 79)


def test_gap_through_target_fills_at_target() -> None:
    (t,), _, _ = run(signal(), [bar(150, 151, 149, 150)])
    assert (t.exit_reason, t.exit_fill) == ("tp", 140)


def test_short_trade_is_mirrored() -> None:
    (t,), _, _ = run(signal("short", 100, 110, 60), [bar(100, 101, 59, 60)])
    assert (t.exit_reason, t.entry_fill, t.exit_fill) == ("tp", 99, 60)
    assert t.net_r == pytest.approx(3.88)
    (t,), _, _ = run(signal("short", 100, 110, 60), [bar(100, 111, 95, 108)])
    assert (t.exit_reason, t.exit_fill) == ("sl", 111)


def test_position_stays_open_without_hit() -> None:
    trades, broker, _ = run(signal(), [bar(100, 110, 95, 105)])
    assert trades == [] and len(broker.positions) == 1


CME_HALT = ExecutionConfig(flat_time=time(16, 0), session_window=None)


def test_flat_before_break() -> None:
    # Scenario 16: the 5-minute bar 15:55-16:00 CT closes every open position.
    last = TickBar(datetime(2024, 1, 8, 21, 55, tzinfo=UTC), 100, 110, 95, 105)
    (t,), _, _ = run(signal(), [last], CME_HALT, five=last)
    assert (t.exit_reason, t.exit_raw, t.exit_fill) == ("flat_break", 105, 104)


def test_no_entry_on_last_bar_before_break() -> None:
    log = EventLog()
    broker = SimBroker(INST, CME_HALT, log)
    broker.submit([signal()], TickBar(datetime(2024, 1, 8, 21, 55, tzinfo=UTC), 100, 100, 100, 100))
    assert broker.positions == [] and "entry_before_break" in log.kinds()


def test_prop_firm_defaults_flat_at_1510_ct() -> None:
    # Amendment 2026-09-25 (Topstep-style): everything is closed with the bar 15:05-15:10 CT.
    last = TickBar(datetime(2024, 7, 8, 20, 5, tzinfo=UTC), 100, 110, 95, 105)  # summer, UTC-5
    (t,), _, _ = run(signal(), [last], five=last)
    assert t.exit_reason == "flat_break"


@pytest.mark.parametrize(
    ("utc", "allowed"),
    [
        (datetime(2024, 1, 8, 19, 55, tzinfo=UTC), True),  # 13:55 CT (20:55 Berlin)
        (datetime(2024, 1, 8, 20, 0, tzinfo=UTC), False),  # 14:00 CT (21:00 Berlin)
        (datetime(2024, 1, 8, 22, 55, tzinfo=UTC), False),  # 16:55 CT: still halted
        (datetime(2024, 1, 8, 23, 0, tzinfo=UTC), True),  # 17:00 CT reopen (00:00 Berlin)
        (datetime(2024, 3, 12, 19, 0, tzinfo=UTC), False),  # 14:00 CDT = 20:00 Berlin (DST gap)
    ],
)
def test_prop_firm_defaults_no_entries_from_1400_ct_to_reopen(utc: datetime, allowed: bool) -> None:
    log = EventLog()
    broker = SimBroker(INST, ExecutionConfig(), log)
    broker.submit([signal()], TickBar(utc, 100, 100, 100, 100))
    assert bool(broker.positions) is allowed
    assert ("entry_outside_session" in log.kinds()) is not allowed


def test_realistic_sizing_rounds_down_and_skips_zero() -> None:
    cfg = ExecutionConfig(sizing="realistic", risk_usd=250.0)
    _, broker, _ = run(signal(), [bar(100, 110, 95, 105)], cfg)
    assert broker.positions[0].qty == 2.0  # 250 / (10 ticks * 10 USD) = 2.5 -> 2
    _, broker, log = run(signal(), [bar(100, 110, 95, 105)], replace(cfg, risk_usd=50.0))
    assert broker.positions == [] and "qty_zero" in log.kinds()


def test_session_window_and_max_positions() -> None:
    cfg = ExecutionConfig(
        session_window=(time(8, 0), time(9, 0)), session_tz="Europe/Berlin"
    )  # T is 16:00 Berlin
    _, broker, log = run(signal(), [bar(100, 110, 95, 105)], cfg)
    assert broker.positions == [] and "entry_outside_session" in log.kinds()
    log = EventLog()
    broker = SimBroker(INST, ExecutionConfig(max_open_positions=1), log)
    broker.submit([signal(), replace(signal(), setup_id="long-1")], bar(100, 100, 100, 100, 0))
    assert len(broker.positions) == 1 and "max_open_positions" in log.kinds()


def test_close_all_at_end_of_data() -> None:
    _, broker, _ = run(signal(), [bar(100, 110, 95, 105)])
    (t,) = broker.close_all(bar(105, 106, 104, 106, minute=10))
    assert (t.exit_reason, t.exit_fill) == ("end_of_data", 105)


def test_gap_exits_update_excursions() -> None:
    # Review finding: a gap exit must count the gap in MFE/MAE.
    (t,), _, _ = run(signal(), [bar(80, 85, 78, 84)])
    assert t.mae_r == pytest.approx(2.0)  # entry 100, stop 90, filled from open 80
    (t,), _, _ = run(signal(), [bar(150, 151, 149, 150)])
    assert t.mfe_r == pytest.approx(4.0)


def test_explicit_break_flag_overrides_calendar() -> None:
    # Holiday early close: the runner knows a break follows even when the calendar does not.
    log = EventLog()
    broker = SimBroker(INST, ExecutionConfig(), log)
    broker.submit([signal()], bar(100, 100, 100, 100, minute=0))
    b = bar(100, 110, 95, 105)
    (t,) = broker.on_bar(b, [b], last_before_break=True)
    assert t.exit_reason == "flat_break"
    broker.submit([signal()], b, last_before_break=True)
    assert broker.positions == [] and "entry_before_break" in log.kinds()


CFD = Instrument("CFD", Decimal("0.001"), 0.001, 0.0, slippage_ticks=0, spread_ticks=3)


def cfd_run(sig: Signal, minutes: Sequence[TickBar]) -> tuple[list[Trade], SimBroker]:
    broker = SimBroker(CFD, ExecutionConfig(), EventLog())
    broker.submit([sig], bar(100, 100, 100, 100, minute=0))
    return broker.on_bar(minutes[-1], minutes), broker


def test_cfd_long_buys_at_the_ask_short_sells_at_the_bid() -> None:
    # Bars are bid prices. A long pays the spread on entry, a short on its exit (a buy).
    _, broker = cfd_run(signal("long", 100, 90, 140), [bar(100, 100, 100, 100)])
    assert broker.positions[0].entry_fill == 103
    _, broker = cfd_run(signal("short", 100, 110, 60), [bar(100, 100, 100, 100)])
    assert broker.positions[0].entry_fill == 100


def test_cfd_short_stop_triggers_on_the_ask() -> None:
    # Review finding (bid-bar bias): the bid high 107 is an ask of 110 -> the buy stop fills.
    (t,), _ = cfd_run(signal("short", 100, 110, 60), [bar(100, 107, 99, 105)])
    assert (t.exit_reason, t.exit_raw, t.exit_fill) == ("sl", 110, 110)
    assert t.net_r == pytest.approx(-1.0)  # sold 100, bought back 110
    assert t.gross_r == pytest.approx(-0.7)  # on the bid chart it left at 107
    assert t.cost_r == pytest.approx(0.3)  # the spread, same as for a long


def test_cfd_short_target_needs_the_ask() -> None:
    # Bid low 60 is an ask of 63: the buy limit at 60 is not reached yet.
    trades, broker = cfd_run(signal("short", 100, 110, 60), [bar(100, 101, 60, 62)])
    assert trades == [] and len(broker.positions) == 1
    (t,), _ = cfd_run(signal("short", 100, 110, 60), [bar(100, 101, 57, 58)])
    assert (t.exit_reason, t.exit_fill, t.net_r, t.gross_r) == ("tp", 60, 4.0, pytest.approx(4.3))


def test_cfd_long_is_unchanged() -> None:
    (t,), _ = cfd_run(signal("long", 100, 90, 140), [bar(100, 101, 90, 92)])
    assert (t.exit_reason, t.exit_fill) == ("sl", 90)
    assert (t.gross_r, t.net_r) == (pytest.approx(-1.0), pytest.approx(-1.3))


def test_cfd_short_flat_exit_buys_at_the_ask() -> None:
    last = TickBar(datetime(2024, 7, 8, 20, 5, tzinfo=UTC), 100, 101, 95, 96)  # 15:10 CT
    broker = SimBroker(CFD, ExecutionConfig(), EventLog())
    broker.submit([signal("short", 100, 110, 60)], bar(100, 100, 100, 100, minute=0))
    (t,) = broker.on_bar(last, [last])
    assert (t.exit_reason, t.exit_raw, t.exit_fill) == ("flat_break", 99, 99)
    assert (t.gross_r, t.net_r) == (pytest.approx(0.4), pytest.approx(0.1))


def test_hold_overnight_has_no_flat_and_no_entry_window() -> None:
    cfg = ExecutionConfig(flat_before_break=False, session_window=None)
    last = TickBar(datetime(2024, 7, 8, 20, 5, tzinfo=UTC), 100, 110, 95, 105)  # 15:10 CT bar
    trades, broker, _ = run(signal(), [last], cfg, five=last)
    assert trades == [] and len(broker.positions) == 1
    log = EventLog()
    broker = SimBroker(INST, cfg, log)
    broker.submit([signal()], TickBar(datetime(2024, 1, 8, 20, 0, tzinfo=UTC), 100, 100, 100, 100))
    assert len(broker.positions) == 1  # 14:00 CT is allowed now


def test_flat_check_uses_the_bar_length() -> None:
    # A 15-minute bar 14:55-15:10 CT is the last one before a 15:10 CT flat time.
    cfg = ExecutionConfig(bar_minutes=15)
    last = TickBar(datetime(2024, 7, 8, 19, 55, tzinfo=UTC), 100, 110, 95, 105)
    (t,), _, _ = run(signal(), [last], cfg, five=last)
    assert t.exit_reason == "flat_break"
