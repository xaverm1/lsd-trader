from datetime import UTC, datetime, timedelta

from lsdtrader.core.bar import TickBar
from lsdtrader.core.instrument import get_instrument
from lsdtrader.data.aggregate import five_minute_start, to_five_minute
from lsdtrader.data.report import build_report

T = datetime(2025, 1, 2, 14, 30, tzinfo=UTC)


def minute(i: int, o: int, h: int, lo: int, c: int) -> TickBar:
    return TickBar(T + timedelta(minutes=i), o, h, lo, c)


def test_five_minute_alignment() -> None:
    assert five_minute_start(datetime(2025, 1, 2, 14, 37, tzinfo=UTC)) == datetime(
        2025, 1, 2, 14, 35, tzinfo=UTC
    )


def test_aggregation_ohlc_and_minute_groups() -> None:
    minutes = [
        minute(0, 10, 12, 9, 11),
        minute(1, 11, 15, 10, 14),
        minute(4, 14, 14, 8, 9),
        minute(5, 9, 10, 7, 8),  # next 5-minute bar, only one minute
    ]
    bars, groups = to_five_minute(minutes)
    assert [(b.ts, b.open, b.high, b.low, b.close) for b in bars] == [
        (T, 10, 15, 8, 9),
        (T + timedelta(minutes=5), 9, 10, 7, 8),
    ]
    assert len(groups[T]) == 3 and len(groups[T + timedelta(minutes=5)]) == 1


def test_report_classifies_gaps_breaks_and_jumps() -> None:
    # T = 09:30 New York. Only pauses that end at the 18:00 New York reopen are expected breaks.
    minutes = [minute(i, 100, 102, 99, 101) for i in range(10)]
    minutes.append(minute(30, 101, 103, 100, 102))  # 20-minute gap -> listed
    minutes.append(minute(120, 102, 104, 101, 103))  # 89-minute hole mid-session -> listed
    minutes.append(minute(121, 900, 902, 899, 901))  # jump of 797 ticks > 50 x 3
    minutes.append(minute(510, 901, 902, 900, 901))  # resumes 18:00 New York -> expected break
    report = build_report(get_instrument("SPXUSD"), minutes, duplicates_dropped=2)
    assert report.n_minutes == 14 and report.n_breaks == 1
    assert [g.length for g in report.gaps] == [timedelta(minutes=20), timedelta(minutes=89)]
    assert [j.ticks for j in report.jumps] == [797]
    text = report.to_markdown()
    assert "Duplicate timestamps dropped while loading: 2" in text
    assert "## Largest gaps" in text and "## Price jumps" in text


def test_report_of_nothing() -> None:
    report = build_report(get_instrument("SPXUSD"), [])
    assert report.n_minutes == 0 and report.first is None
