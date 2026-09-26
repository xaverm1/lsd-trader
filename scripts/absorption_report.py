# ruff: noqa: E501, B905
"""Report for absorption_1m runs: targets, costs, years, bubble strength.

Usage: python scripts/absorption_report.py RUN_FOLDER [RUN_FOLDER ...]

Gross R from the run (a target of X R is evaluated exactly from the run-up without take
profit); net R = gross minus the run's own cost per trade (commission + 1 tick slippage per
side from the instrument spec, in R of that trade).
"""

import json
import math
import statistics
import sys
from collections import defaultdict

import pyarrow.parquet as pq

TPS = (2, 3, 4, 6)


def r_at(t: dict, tp: float) -> float:
    return tp if t["mfe_free_r"] >= tp else t["exit_free_r"]


def st(rs: list[float]) -> str:
    n = len(rs)
    if n < 2:
        return "n/a"
    m = sum(rs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in rs) / (n - 1))
    return f"{m:+.3f} ({m / sd * math.sqrt(n):+.1f})"


for run in sys.argv[1:]:
    with open(f"{run}/meta.json") as fh:
        meta = json.load(fh)
    tick = float(meta["instrument"]["tick_size"])
    ts = [t for t in pq.read_table(f"{run}/trades.parquet").to_pylist() if t["mfe_free_r"] is not None]
    years = sorted({t["entry_ts"].year for t in ts})
    stops = [t["risk_ticks"] * tick for t in ts]
    cost = [t["cost_r"] for t in ts]
    print(f"\n## {meta['instrument']['root']} {years[0]}-{years[-1]}, stop_ref={meta['strategy_config'].get('stop_ref')}")
    print(f"{len(ts)} trades ({len(ts) / len(years):.0f}/yr), median stop {statistics.median(stops):.2f} pts, "
          f"median cost {statistics.median(cost):.2f} R, mean cost {sum(cost) / len(cost):.2f} R\n")
    print("| TP | gross R/T (t) | net R/T (t) | win % |")
    print("|---|---|---|---|")
    for tp in TPS:
        g = [r_at(t, tp) for t in ts]
        n = [x - t["cost_r"] for x, t in zip(g, ts)]
        print(f"| {tp}R | {st(g)} | {st(n)} | {sum(x > 0 for x in g) / len(g):.1%} |")
    print("\nBy year, TP 4R: gross / net R per trade (N)")
    by = defaultdict(list)
    for t in ts:
        by[t["entry_ts"].year].append(t)
    print(" ".join(f"{y}: {sum(r_at(t, 4) for t in g) / len(g):+.2f}/{sum(r_at(t, 4) - t['cost_r'] for t in g) / len(g):+.2f} ({len(g)})" for y, g in sorted(by.items())))
    print("\nBy bubble strength (volume score), TP 4R gross:")
    for lo, hi in ((1.3, 2), (2, 3), (3, 5), (5, 99)):
        g = [r_at(t, 4) for t in ts if lo <= (t.get("feat_abs_score") or 0) < hi]
        print(f"  score {lo}-{hi}: N={len(g)} {st(g)}")
    print("\nBy stop size (pts), TP 4R gross / net:")
    qs = sorted(stops)
    edges = [qs[0], qs[len(qs) // 4], qs[len(qs) // 2], qs[3 * len(qs) // 4], qs[-1] + 1]
    for lo, hi in zip(edges, edges[1:]):
        g = [t for t, s in zip(ts, stops) if lo <= s < hi]
        if g:
            print(f"  {lo:.2f}-{hi:.2f}: N={len(g)} gross {st([r_at(t, 4) for t in g])} net {st([r_at(t, 4) - t['cost_r'] for t in g])}")
