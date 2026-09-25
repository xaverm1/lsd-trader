# ruff: noqa: E501, B905
"""Compare runs on different bar lengths, gross and after an assumed futures cost.

Usage: python scripts/timeframes.py [--cost 0.35] RUN_FOLDER ...

Cost per trade in R = cost in USD per ounce / stop in USD (GC ~ $0.35/oz round trip incl.
1 tick slippage per side, see HANDOFF). TP 4 is the run itself; TP 6 is post hoc from the
run-up without take profit (exact). R are gross from the run (spread 0 on XAUUSD).
"""

import json
import math
import statistics
import sys

import pyarrow.parquet as pq

args = sys.argv[1:]
cost = 0.35
if args and args[0] == "--cost":
    cost, args = float(args[1]), args[2:]


def stats(rs: list[float]) -> tuple[float, float]:
    n = len(rs)
    m = sum(rs) / n
    sd = math.sqrt(sum((r - m) ** 2 for r in rs) / (n - 1))
    return m, m / sd * math.sqrt(n)


print(f"cost assumption: ${cost}/oz per round trip\n")
print(
    "| Bars | N | Trades/yr | Median stop $ | Cost R | TP4 gross R/T (t) | TP4 net | TP6 gross R/T (t) | TP6 net | TP6 gross by year |"
)
print("|---|---|---|---|---|---|---|---|---|---|")
for run in args:
    with open(f"{run}/meta.json") as fh:
        meta = json.load(fh)
    tf = meta["execution_config"].get("bar_minutes", 5)
    ts = pq.read_table(
        f"{run}/trades.parquet",
        columns=["entry_ts", "gross_r", "risk_ticks", "mfe_free_r", "exit_free_r"],
    ).to_pylist()
    tick = float(meta["instrument"]["tick_size"])
    stops = [t["risk_ticks"] * tick for t in ts]
    costs = [cost / s for s in stops]
    tp4 = [t["gross_r"] for t in ts]
    tp6 = [6.0 if t["mfe_free_r"] >= 6 else t["exit_free_r"] for t in ts]
    years = sorted({t["entry_ts"].year for t in ts})
    by_year = " ".join(
        f"{y % 100:02d}:{sum(r for r, t in zip(tp6, ts) if t['entry_ts'].year == y) / max(1, sum(1 for t in ts if t['entry_ts'].year == y)):+.2f}"
        for y in years
    )
    m4, t4 = stats(tp4)
    m6, t6 = stats(tp6)
    mc = sum(costs) / len(costs)
    print(
        f"| {tf}m | {len(ts)} | {len(ts) / len(years):.0f} | {statistics.median(stops):.2f} | {mc:.2f} | {m4:+.3f} ({t4:+.1f}) | {m4 - mc:+.3f} | {m6:+.3f} ({t6:+.1f}) | {m6 - mc:+.3f} | {by_year} |"
    )
