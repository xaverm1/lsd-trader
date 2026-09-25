# ruff: noqa: E501, B905
"""Moving-average trend at the entry vs. result, post hoc on an existing run (gross R).

Usage: python scripts/ma_trend.py RUN_FOLDER [TP ...]   (default TP 4 and 6)

Rebuilds the 5-minute bars from the run's data files and computes, at the close of the entry
bar, four candidates fixed before looking at any result ("with" = long above / short below):
  close_ema200    close above EMA 200
  ema50_ema200    EMA 50 above EMA 200
  close_ema240    close above EMA 240 (~ EMA 20 on 1 hour)
  ema200_rising   EMA 200 higher than 12 bars (1 hour) ago
"""

import json
import math
import sys
from pathlib import Path

import pyarrow.parquet as pq

from lsdtrader.core.instrument import get_instrument
from lsdtrader.data.aggregate import to_five_minute
from lsdtrader.data.minute_files import load_minute_files

run = sys.argv[1]
tps = [float(x) for x in sys.argv[2:]] or [4.0, 6.0]
with open(f"{run}/meta.json") as fh:
    meta = json.load(fh)
minutes, _ = load_minute_files(
    [Path(d["path"]) for d in meta["data"]], get_instrument(meta["instrument"]["root"])
)
bars, _ = to_five_minute(minutes)


def ema(values: list[float], n: int) -> list[float]:
    k, out, e = 2 / (n + 1), [], values[0]
    for v in values:
        e = v * k + e * (1 - k)
        out.append(e)
    return out


close = [float(b.close) for b in bars]
e50, e200, e240 = ema(close, 50), ema(close, 200), ema(close, 240)
at = {}
for i, b in enumerate(bars):
    if i < 240:
        continue  # warm-up
    at[b.ts] = {
        "close_ema200": close[i] > e200[i],
        "ema50_ema200": e50[i] > e200[i],
        "close_ema240": close[i] > e240[i],
        "ema200_rising": e200[i] > e200[i - 12],
    }

trades = [
    t
    for t in pq.read_table(f"{run}/trades.parquet").to_pylist()
    if t["mfe_free_r"] is not None and t["entry_ts"] in at
]


def r_at(t: dict, tp: float) -> float:
    return tp if t["mfe_free_r"] >= tp else t["exit_free_r"]


def stats(rs: list[float]) -> str:
    n = len(rs)
    if n < 2:
        return f"N={n:4d}"
    m = sum(rs) / n
    sd = math.sqrt(sum((r - m) ** 2 for r in rs) / (n - 1))
    return f"N={n:4d} R/T={m:+.3f} t={m / sd * math.sqrt(n) if sd else float('nan'):+.2f}"


print(f"{run}: {len(trades)} trades with MA values, gross R")
for tp in tps:
    print(f"\n===== TP {tp:g} R | all: {stats([r_at(t, tp) for t in trades])}")
    for key in ("close_ema200", "ema50_ema200", "close_ema240", "ema200_rising"):
        w = [r_at(t, tp) for t in trades if at[t["entry_ts"]][key] == (t["side"] == "long")]
        a = [r_at(t, tp) for t in trades if at[t["entry_ts"]][key] != (t["side"] == "long")]
        print(f"  {key:14s} with: {stats(w)} | against: {stats(a)}")
