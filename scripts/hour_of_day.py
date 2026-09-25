# ruff: noqa: E501, B905
"""Result by hour of day of the entry (Europe/Berlin), on an existing run.

Usage: python scripts/hour_of_day.py RUN_FOLDER [OUT.png]

Per hour: N, win rate, net R per trade, sum, t-stat, and the same split into two halves of the
years (stable hours should have the same sign in both). 24 buckets are 24 tests: at p < 0.05
about one hour is expected to look "significant" by chance alone.
"""

import sys
from zoneinfo import ZoneInfo

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pyarrow.parquet as pq

BERLIN = ZoneInfo("Europe/Berlin")
run = sys.argv[1]
out = sys.argv[2] if len(sys.argv) > 2 else f"{run}/hour_of_day.png"
trades = pq.read_table(f"{run}/trades.parquet", columns=["entry_ts", "net_r", "side"]).to_pylist()
for t in trades:
    t["hour"] = t["entry_ts"].astimezone(BERLIN).hour
years = sorted({t["entry_ts"].year for t in trades})
mid = years[len(years) // 2]  # second half starts here


def stats(rs):
    n = len(rs)
    if n < 2:
        return n, 0.0, 0.0, 0.0, 0.0
    m = sum(rs) / n
    v = sum((r - m) ** 2 for r in rs) / (n - 1)
    return n, sum(r > 0 for r in rs) / n, m, sum(rs), m / (v / n) ** 0.5 if v else 0.0


rows = []
print(
    f"Einstiegsstunde Europe/Berlin, N={len(trades)}, Haelften {years[0]}-{mid - 1} / {mid}-{years[-1]}"
)
print(
    f"{'Std':>5} {'N':>5} {'Win%':>6} {'R/T':>7} {'Summe':>7} {'t':>6} | {'R/T H1':>7} {'R/T H2':>7} {'Long':>7} {'Short':>7}"
)
for h in range(24):
    sel = [t for t in trades if t["hour"] == h]
    n, win, m, s, ts = stats([t["net_r"] for t in sel])
    h1 = stats([t["net_r"] for t in sel if t["entry_ts"].year < mid])[2]
    h2 = stats([t["net_r"] for t in sel if t["entry_ts"].year >= mid])[2]
    lo = stats([t["net_r"] for t in sel if t["side"] == "long"])[2]
    sh = stats([t["net_r"] for t in sel if t["side"] == "short"])[2]
    rows.append((h, n, m, s, ts, h1, h2))
    flag = "  *" if abs(ts) >= 2 else ""
    print(
        f"{h:02d}-{h + 1:02d} {n:5d} {win:6.1%} {m:+7.3f} {s:+7.1f} {ts:+6.2f} | {h1:+7.3f} {h2:+7.3f} {lo:+7.3f} {sh:+7.3f}{flag}"
    )

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
hs = [r[0] for r in rows]
ax1.bar(hs, [r[3] for r in rows], color=["#1D9E75" if r[3] > 0 else "#E24B4A" for r in rows])
ax1.set_ylabel("Summe R")
ax1.set_title(f"Ergebnis nach Einstiegsstunde (Berlin), {years[0]}-{years[-1]}, N={len(trades)}")
for r in rows:
    ax1.annotate(
        f"{r[1]}",
        (r[0], 0),
        ha="center",
        va="top" if r[3] >= 0 else "bottom",
        fontsize=7,
        color="#555",
    )
w = 0.4
ax2.bar(
    [h - w / 2 for h in hs], [r[5] for r in rows], w, label=f"{years[0]}-{mid - 1}", color="#5B8DEF"
)
ax2.bar(
    [h + w / 2 for h in hs], [r[6] for r in rows], w, label=f"{mid}-{years[-1]}", color="#F2A541"
)
ax2.axhline(0, color="#333", lw=0.8)
ax2.set_ylabel("R pro Trade")
ax2.set_xlabel("Stunde (Europe/Berlin), Zahl im oberen Bild = N")
ax2.set_xticks(hs)
ax2.legend()
fig.tight_layout()
fig.savefig(out, dpi=110)
print(f"\nBild: {out}")
