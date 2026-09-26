# ruff: noqa: E501, B905
"""Break-even or take profit at level -1 of the leg, simulated minute by minute (gross R).

Usage: python scripts/sd_be.py RUN_FOLDER [PIVOT=5]

Same leg as sd_targets.py (last confirmed 1-minute swing high before the stop low; level -k =
leg high + k * leg). Every exit plan is replayed on the 1-minute bars after the entry minute:
stop and target in the same minute count as stop; a break-even stop is armed after the minute
that reached its trigger and applies from the next minute. Shorts are mirrored. Trades that
never reach stop or target end at the last available close.
"""

import bisect
import math
import sys
from pathlib import Path

from lsdtrader.review.review import load_run

folder = Path(sys.argv[1])
pivot = int(sys.argv[2]) if len(sys.argv) > 2 else 5
run = load_run(folder)
mins = run.data.minute_bars
mts = [m.ts for m in mins]


def swing_high(i: int, n: int, hi: list[int]) -> bool:
    if i - n < 0 or i + n >= len(hi):
        return False
    v = hi[i]
    return all(hi[i - k] <= v and hi[i + k] < v for k in range(1, n + 1))


def mirrored(i: int, long: bool) -> tuple[int, int, int]:
    """(high, low, close) of minute i in the trade's own direction (short = price negated)."""
    m = mins[i]
    return (m.high, m.low, m.close) if long else (-m.low, -m.high, -m.close)


def simulate(
    e: int, long: bool, entry: int, stop: int, plan: list[tuple[float, int]], be_at: int | None
) -> float:
    """plan: [(fraction, target price)], prices in trade direction. Returns R."""
    risk = entry - stop
    open_parts = list(plan)
    result, cur_stop, armed = 0.0, stop, False
    for i in range(e + 1, len(mins)):
        h, lo, c = mirrored(i, long)
        if lo <= cur_stop:
            return result + sum(f for f, _ in open_parts) * (cur_stop - entry) / risk
        keep = []
        for f, tp in open_parts:
            if h >= tp:
                result += f * (tp - entry) / risk
            else:
                keep.append((f, tp))
        open_parts = keep
        if not open_parts:
            return result
        if be_at is not None and not armed and h >= be_at:
            cur_stop, armed = entry, True
    last = mirrored(len(mins) - 1, long)[2]
    return result + sum(f for f, _ in open_parts) * (last - entry) / risk


rows = []
for t in run.trades:
    long = t["side"] == "long"
    d = 1 if long else -1
    e = bisect.bisect_right(mts, t["entry_ts"]) - 1
    stop, entry = d * t["stop"], d * t["entry_signal"]
    ext = next((i for i in range(e, max(e - 2000, 0), -1) if mirrored(i, long)[1] == stop), None)
    if ext is None:
        continue
    lo_i = max(ext - 2000, 0)
    his = [mirrored(i, long)[0] for i in range(lo_i, ext + 1)]
    top = next(
        (his[j] for j in range(len(his) - 1 - pivot, pivot - 1, -1) if swing_high(j, pivot, his)),
        None,
    )
    if top is None or top <= stop or entry <= stop:
        continue
    leg = top - stop
    lvl = {k: top + round(k * leg) for k in (1, 2, 2.5, 4)}
    if lvl[1] <= entry:
        continue
    rows.append((e, long, entry, stop, lvl))

risk_r = lambda r, p: (p - r[2]) / (r[2] - r[3])  # noqa: E731
plans = {
    "TP -2": lambda r: ([(1, r[4][2])], None),
    "TP -2, BE ab -1": lambda r: ([(1, r[4][2])], r[4][1]),
    "TP -2.5": lambda r: ([(1, r[4][2.5])], None),
    "TP -2.5, BE ab -1": lambda r: ([(1, r[4][2.5])], r[4][1]),
    "TP -4": lambda r: ([(1, r[4][4])], None),
    "TP -4, BE ab -1": lambda r: ([(1, r[4][4])], r[4][1]),
    "TP -1": lambda r: ([(1, r[4][1])], None),
    "50% -1 / 50% -2, BE ab -1": lambda r: ([(0.5, r[4][1]), (0.5, r[4][2])], r[4][1]),
    "50% -1 / 50% -4, BE ab -1": lambda r: ([(0.5, r[4][1]), (0.5, r[4][4])], r[4][1]),
    "50% -2 / 50% -4, BE ab -2": lambda r: ([(0.5, r[4][2]), (0.5, r[4][4])], r[4][2]),
    "fest 4R": lambda r: ([(1, r[2] + 4 * (r[2] - r[3]))], None),
    "fest 6R": lambda r: ([(1, r[2] + 6 * (r[2] - r[3]))], None),
}

print(f"{folder}: {len(rows)} trades (pivot {pivot})")
med = sorted(risk_r(r, r[4][1]) for r in rows)[len(rows) // 2]
print(f"Level -1 liegt im Median bei {med:.1f} R\n")
print("| Ausstieg | R/Trade | t | Gewinner % | Summe R |")
print("|---|---|---|---|---|")
for name, f in plans.items():
    rs = [simulate(r[0], r[1], r[2], r[3], *f(r)) for r in rows]
    n = len(rs)
    m = sum(rs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in rs) / (n - 1))
    print(
        f"| {name} | {m:+.3f} | {m / sd * math.sqrt(n):+.2f} | {sum(x > 0 for x in rs) / n:.1%} | {sum(rs):+.0f} |"
    )
