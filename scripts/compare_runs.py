# ruff: noqa: E501, B905
"""Compare finished runs against a baseline run (net R, as the runs were made).

Usage: python scripts/compare_runs.py BASELINE_RUN VARIANT_RUN [VARIANT_RUN ...]

Per run: trades, win rate, R/trade, sum, t, max drawdown, long/short and every year.
The label of a run is its strategy settings that differ from the baseline.
"""

import json
import math
import sys
from collections import defaultdict

import pyarrow.parquet as pq


def load(run: str) -> tuple[list[dict], dict]:
    trades = pq.read_table(
        f"{run}/trades.parquet", columns=["entry_ts", "net_r", "side"]
    ).to_pylist()
    trades.sort(key=lambda t: t["entry_ts"])
    with open(f"{run}/meta.json") as fh:
        meta = json.load(fh)
    return trades, {**meta["strategy_config"], **meta["execution_config"]}


def stats(rs: list[float]) -> tuple[int, float, float, float]:
    n = len(rs)
    if n < 2:
        return n, float("nan"), sum(rs), float("nan")
    m = sum(rs) / n
    sd = math.sqrt(sum((r - m) ** 2 for r in rs) / (n - 1))
    return n, m, sum(rs), m / sd * math.sqrt(n)


def max_dd(rs: list[float]) -> float:
    eq = peak = dd = 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return dd


base_trades, base_cfg = load(sys.argv[1])
runs = [("baseline", base_trades)]
for run in sys.argv[2:]:
    trades, cfg = load(run)
    diff = {k: v for k, v in cfg.items() if base_cfg.get(k) != v}
    runs.append((", ".join(f"{k}={v}" for k, v in diff.items()) or run, trades))

years = sorted({t["entry_ts"].year for _, ts in runs for t in ts})
print(
    "| Run | N | Win % | R/Trade | Sum R | t | Max DD R | Long R/T | Short R/T | "
    + " | ".join(map(str, years))
    + " |"
)
print("|---|---|---|---|---|---|---|---|---|" + "---|" * len(years))
for label, ts in runs:
    rs = [t["net_r"] for t in ts]
    n, m, s, tt = stats(rs)
    win = sum(r > 0 for r in rs) / n
    side = {sd: stats([t["net_r"] for t in ts if t["side"] == sd])[1] for sd in ("long", "short")}
    by_year = defaultdict(float)
    for t in ts:
        by_year[t["entry_ts"].year] += t["net_r"]
    cells = " | ".join(f"{by_year[y]:+.0f}" for y in years)
    print(
        f"| {label} | {n} | {win:.1%} | {m:+.3f} | {s:+.0f} | {tt:+.2f} | {max_dd(rs):.0f} | {side['long']:+.3f} | {side['short']:+.3f} | {cells} |"
    )
