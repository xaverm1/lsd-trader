# ruff: noqa: E501, B905
"""Take-profit levels and run-up (MFE) of an existing run, before costs (gross R).

Usage: python scripts/take_profit.py RUN_FOLDER

Every trade carries `mfe_free_r` (how far price ran before the stop or the flat time, with no
take profit) and `exit_free_r` (how it would have ended). With a target of X R a trade makes
+X if mfe_free_r >= X, else exit_free_r. Exact while max_open_positions is off: the target
does not change which trades are taken. Every level looked at counts as a tested variant.
"""

import math
import sys

import pyarrow.parquet as pq

run = sys.argv[1]
trades = pq.read_table(
    f"{run}/trades.parquet",
    columns=["side", "exit_reason", "gross_r", "mfe_free_r", "exit_free_r", "exit_free_reason"],
).to_pylist()
trades = [t for t in trades if t["mfe_free_r"] is not None]


def stats(rs: list[float]) -> tuple[int, float, float, float]:
    n = len(rs)
    m = sum(rs) / n
    sd = math.sqrt(sum((r - m) ** 2 for r in rs) / (n - 1))
    return n, m, sum(rs), m / sd * math.sqrt(n)


def result(t: dict, x: float) -> float:
    return x if t["mfe_free_r"] >= x else t["exit_free_r"]


print(f"{run}: {len(trades)} trades, gross R (no costs)\n")
print(
    "Without take profit, trades end by:",
    {
        k: sum(t["exit_free_reason"] == k for t in trades)
        for k in ("sl", "flat_break", "end_of_data")
    },
)

print("\n## Target level (gross R per trade)\n")
print("| TP (R) | Win % | R/Trade | Sum R | t | Long R/T | Short R/T |")
print("|---|---|---|---|---|---|---|")
levels = [0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4, 5, 6, 8, 10, None]
for x in levels:
    rs = [result(t, x) if x else t["exit_free_r"] for t in trades]
    n, m, s, tt = stats(rs)
    win = sum(r > 0 for r in rs) / n
    side = {
        sd: stats([r for r, t in zip(rs, trades) if t["side"] == sd])[1] for sd in ("long", "short")
    }
    label = f"{x:g}" if x else "none"
    print(
        f"| {label} | {win:.1%} | {m:+.3f} | {s:+.0f} | {tt:+.2f} | {side['long']:+.3f} | {side['short']:+.3f} |"
    )

print("\n## How far did price run? Share of trades with run-up >= k R (no take profit)\n")
groups = {
    "all": trades,
    "winners (actual net > 0)": [t for t in trades if t["gross_r"] > 0],
    "losers (actual stop)": [t for t in trades if t["exit_reason"] == "sl"],
}
ks = [0.5, 1, 2, 3, 4, 5, 6, 8, 10]
print("| Group | N | " + " | ".join(f">= {k:g}" for k in ks) + " | median |")
print("|---|---|" + "---|" * len(ks) + "---|")
for name, g in groups.items():
    mfe = sorted(t["mfe_free_r"] for t in g)
    shares = " | ".join(f"{sum(v >= k for v in mfe) / len(mfe):.1%}" for k in ks)
    print(f"| {name} | {len(g)} | {shares} | {mfe[len(mfe) // 2]:.2f} |")
