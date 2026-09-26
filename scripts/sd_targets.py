# ruff: noqa: E501, B905
"""Targets from the leg into the zone ("SD projections") vs. fixed R, post hoc (gross R).

Usage: python scripts/sd_targets.py RUN_FOLDER [PIVOT=5]

Leg (long): from the last confirmed 1-minute swing high (PIVOT bars each side) before the
lowest low (= the stop) down to that low. Target at level -k = leg high + k * leg length
(fib convention: 0 = leg high, 1 = leg low). Shorts mirrored. A target of X R is hit if the
run-up without take profit reached X before the stop (mfe_free_r), exact for one target.
Partial plan: 50 % at -2, 50 % at -4; "BE" moves the stop to entry after the first partial.
"""

import bisect
import math
import statistics
import sys
from pathlib import Path

from lsdtrader.review.review import load_run

folder = Path(sys.argv[1])
pivot = int(sys.argv[2]) if len(sys.argv) > 2 else 5
run = load_run(folder)
mins = run.data.minute_bars
mts = [m.ts for m in mins]


def swing(i: int, n: int, high: bool) -> bool:
    if i - n < 0 or i + n >= len(mins):
        return False
    v = mins[i].high if high else mins[i].low
    for k in range(1, n + 1):
        a, b = (mins[i - k].high, mins[i + k].high) if high else (mins[i - k].low, mins[i + k].low)
        if (high and (a > v or b >= v)) or (not high and (a < v or b <= v)):
            return False
    return True


rows, skipped = [], 0
for t in run.trades:
    if t["mfe_free_r"] is None:
        continue
    long = t["side"] == "long"
    e = bisect.bisect_right(mts, t["entry_ts"]) - 1
    # minute of the extreme (the stop) at or before the entry
    ext = None
    for i in range(e, max(e - 2000, 0), -1):
        if (mins[i].low if long else mins[i].high) == t["stop"]:
            ext = i
            break
    if ext is None:
        skipped += 1
        continue
    # last swing high (low for shorts) confirmed before the extreme
    top = None
    for i in range(ext - pivot, max(ext - 2000, pivot), -1):
        if swing(i, pivot, long):
            top = mins[i].high if long else mins[i].low
            break
    if top is None:
        skipped += 1
        continue
    d = 1 if long else -1
    leg = d * (top - t["stop"])
    risk = d * (t["entry_signal"] - t["stop"])
    if leg <= 0 or risk <= 0:
        skipped += 1
        continue
    tgt = {k: d * (top + d * k * leg - t["entry_signal"]) / risk for k in (2, 2.5, 4)}
    if tgt[2] <= 0:
        skipped += 1
        continue
    rows.append((t, tgt))


def res(t: dict, x: float) -> float:
    return x if t["mfe_free_r"] >= x else t["exit_free_r"]


def partial(t: dict, a: float, b: float, be: bool) -> float:
    if t["mfe_free_r"] < a:
        return t["exit_free_r"]
    second = (
        b
        if t["mfe_free_r"] >= b
        else (0.0 if be and t["exit_free_reason"] == "sl" else t["exit_free_r"])
    )
    if be and t["mfe_free_r"] < b and t["exit_free_reason"] != "sl":
        second = max(second, 0.0)
    return 0.5 * a + 0.5 * second


def stats(rs: list[float]) -> str:
    n = len(rs)
    m = sum(rs) / n
    sd = math.sqrt(sum((r - m) ** 2 for r in rs) / (n - 1))
    win = sum(r > 0 for r in rs) / n
    return f"| {m:+.3f} | {m / sd * math.sqrt(n):+.2f} | {win:.1%} | {sum(rs):+.0f} |"


print(f"{folder}: {len(rows)} trades with a leg (pivot {pivot}), {skipped} skipped\n")
print(
    "Target distance in R: median  -2: {:.1f}  -2.5: {:.1f}  -4: {:.1f}".format(
        *(statistics.median(tg[k] for _, tg in rows) for k in (2, 2.5, 4))
    )
)
print(
    f"Leg length in stops: median {statistics.median((tg[4] - tg[2]) / 2 for _, tg in rows):.2f}\n"
)
print("| Exit | R/Trade | t | Win % | Sum R |")
print("|---|---|---|---|---|")
for label, f in [
    ("fixed 2R", lambda t, tg: res(t, 2)),
    ("fixed 4R", lambda t, tg: res(t, 4)),
    ("fixed 6R", lambda t, tg: res(t, 6)),
    ("SD -2", lambda t, tg: res(t, tg[2])),
    ("SD -2.5", lambda t, tg: res(t, tg[2.5])),
    ("SD -4", lambda t, tg: res(t, tg[4])),
    ("50% -2 / 50% -4", lambda t, tg: partial(t, tg[2], tg[4], False)),
    ("50% -2 / 50% -4, BE", lambda t, tg: partial(t, tg[2], tg[4], True)),
]:
    print(f"| {label} " + stats([f(t, tg) for t, tg in rows]))

# fair comparison: the same partial plan with fixed R targets
print("\nSame partial plan with fixed targets:")
print("| Exit | R/Trade | t | Win % | Sum R |")
print("|---|---|---|---|---|")
for a, b in ((2, 4), (2, 6), (3, 6)):
    for be in (False, True):
        print(
            f"| 50% {a}R / 50% {b}R{', BE' if be else ''} "
            + stats([partial(t, a, b, be) for t, _ in rows])
        )
