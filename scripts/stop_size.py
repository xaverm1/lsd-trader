# ruff: noqa: E501, B905
"""Stop size vs. result and cost, on an existing run (post-hoc filter).

Usage: python scripts/stop_size.py RUN_FOLDER [TICK_SIZE]

TICK_SIZE defaults to 0.001 (HistData CFDs). A minimum-stop cap only removes trades, so the
filter is exact for max_trades_per_zone=1 and no position limit (same caveat as zone_age.py).
A stop BUFFER changes stop, target and fills and cannot be done post hoc; it needs a rerun.

The second table re-prices every trade with other round-trip costs in USD per unit
(ounce for gold): net_r = gross_r - cost / stop_usd. Rough guide, commission + 1 tick
slippage per side + spread, per ounce:
    GC  (100 oz, $2.50/side):  ~0.05 + 0.20 + 0.10 = ~0.35
    MGC ( 10 oz, $1.24/side):  ~0.25 + 0.20 + 0.10 = ~0.55
    CFD placeholder: 0.25 (spread only, no slippage)
These are placeholders; the prop firm's real numbers decide.
"""

import sys

import pyarrow.parquet as pq

run = sys.argv[1]
tick = float(sys.argv[2]) if len(sys.argv) > 2 else 0.001
trades = pq.read_table(
    f"{run}/trades.parquet",
    columns=["risk_ticks", "gross_r", "net_r", "cost_r", "exit_reason", "entry_ts"],
).to_pylist()
for t in trades:
    t["stop_usd"] = t["risk_ticks"] * tick


def stats(ts):
    n = len(ts)
    if not n:
        return 0, 0.0, 0.0, 0.0, 0.0, 0.0
    g = sum(t["gross_r"] for t in ts) / n
    c = sum(t["cost_r"] for t in ts) / n
    a = sum(t["net_r"] for t in ts) / n
    win = sum(t["gross_r"] > 0 for t in ts) / n
    # t-stat of gross R per trade (is there an edge before costs at all?)
    var = sum((t["gross_r"] - g) ** 2 for t in ts) / max(n - 1, 1)
    tstat = g / (var / n) ** 0.5 if var else 0.0
    return n, win, g, c, a, tstat


stops = sorted(t["stop_usd"] for t in trades)
print(f"N={len(trades)}  median stop ${stops[len(stops) // 2]:.2f}")

print("\n== Buckets (nicht kumulativ) nach Stopgroesse in USD, Kosten wie im Run")
print(
    f"{'Stop':>12} {'N':>5} {'Win%':>6} {'brutto/T':>9} {'Kosten/T':>9} {'netto/T':>8} {'t brutto':>8}"
)
edges = [0, 0.5, 1, 1.5, 2, 3, 5, 10**9]
for lo, hi in zip(edges, edges[1:]):
    sel = [t for t in trades if lo <= t["stop_usd"] < hi]
    n, win, g, c, a, ts = stats(sel)
    label = f"[{lo:g},{hi:g})" if hi < 10**9 else f">= {lo:g}"
    print(f"{label:>12} {n:5d} {win:6.1%} {g:+9.3f} {c:9.3f} {a:+8.3f} {ts:+8.2f}")

print("\n== Mindeststop (kumulativ) x Kostenannahme, netto R pro Trade (Summe R in Klammern)")
costs = [0.10, 0.25, 0.35, 0.55]
print(
    f"{'min Stop':>9} {'N':>5} {'brutto/T':>9} "
    + " ".join(f"{'$' + format(c, '.2f'):>16}" for c in costs)
)
for m in (0, 0.5, 1, 1.5, 2, 3):
    sel = [t for t in trades if t["stop_usd"] >= m]
    if not sel:
        continue
    n, _, g, _, _, _ = stats(sel)
    cells = []
    for c in costs:
        nets = [t["gross_r"] - c / t["stop_usd"] for t in sel]
        cells.append(f"{sum(nets) / n:+7.3f} ({sum(nets):+6.0f})")
    print(f"{'$' + format(m, 'g'):>9} {n:5d} {g:+9.3f} " + " ".join(f"{x:>16}" for x in cells))

print("\n== Brutto R pro Jahr, Mindeststop $1 / $2 (Stabilitaet)")
for m in (1, 2):
    by = {}
    for t in trades:
        if t["stop_usd"] >= m:
            by.setdefault(t["entry_ts"].year, []).append(t["gross_r"])
    print(
        f"  >= ${m}: "
        + "  ".join(f"{y} {sum(v) / len(v):+.2f} (N={len(v)})" for y, v in sorted(by.items()))
    )
