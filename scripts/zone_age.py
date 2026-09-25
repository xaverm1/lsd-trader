# ruff: noqa: E501, B905
"""Zone age at the sweep vs. result, on an existing run (post-hoc filter).

Usage: python scripts/zone_age.py RUN_FOLDER

Exact for max_trades_per_zone=1 and no position limit: an age cap only removes trades.
"""

import json
import sys
from collections import defaultdict

import pyarrow.parquet as pq

run = sys.argv[1]
trades = pq.read_table(f"{run}/trades.parquet").to_pylist()
events = pq.read_table(
    f"{run}/events.parquet", columns=["side", "kind", "detail", "bar_index"]
).to_pylist()

first_origin = {}  # (side, zone_id) -> o_idx at creation
for e in events:
    if e["kind"] == "zone_created":
        d = json.loads(e["detail"])
        first_origin.setdefault((e["side"], d["zone_id"]), (d["o_idx"], e["bar_index"]))

for t in trades:
    side, zid = t["side"], int(t["zone_id"].split("-")[1])
    o0, created = first_origin[(side, zid)]
    t["age_o"] = t["sweep_idx"] - t["zone_o_idx"]  # since current origin (after relocation)
    t["age_first"] = t["sweep_idx"] - o0  # since first origin
    t["age_created"] = t["sweep_idx"] - created  # since the BOS that created the zone
    t["relocated"] = t["zone_o_idx"] != o0

caps = [
    (12, "1 h"),
    (24, "2 h"),
    (48, "4 h"),
    (96, "8 h"),
    (144, "12 h"),
    (276, "1 Tag"),
    (552, "2 Tage"),
    (1380, "5 Tage"),
    (None, "unbegrenzt"),
]


def stats(ts):
    n = len(ts)
    if not n:
        return "n=0"
    net = sum(t["net_r"] for t in ts)
    gross = sum(t["gross_r"] for t in ts)
    win = sum(t["exit_reason"] == "tp" or t["gross_r"] > 0 for t in ts) / n
    # equity drawdown in R
    eq = peak = dd = 0.0
    for t in sorted(ts, key=lambda t: t["entry_ts"]):
        eq += t["net_r"]
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return n, win, gross / n, net / n, net, dd


for key, title in (
    ("age_o", "Alter seit aktueller Ursprungskerze (Relocation setzt zurueck)"),
    ("age_first", "Alter seit erster Ursprungskerze (Relocation setzt NICHT zurueck)"),
):
    print(f"\n== {title}")
    print(
        f"{'max Alter':>11} {'N':>5} {'Win%':>6} {'bruttoR/T':>10} {'nettoR/T':>9} {'Summe R':>9} {'MaxDD R':>8}"
    )
    for cap, label in caps:
        sel = [t for t in trades if cap is None or t[key] <= cap]
        n, win, g, a, s, dd = stats(sel)
        print(f"{label:>11} {n:5d} {win:6.1%} {g:+10.3f} {a:+9.3f} {s:+9.1f} {dd:8.1f}")

print("\n== Buckets (nicht kumulativ), Alter seit aktueller Ursprungskerze")
edges = [0, 12, 24, 48, 96, 144, 276, 552, 1380, 10**9]
for lo, hi in zip(edges, edges[1:]):
    sel = [t for t in trades if lo < t["age_o"] <= hi or (lo == 0 and t["age_o"] == 0)]
    if sel:
        n, win, g, a, s, dd = stats(sel)
        print(
            f"({lo:5d},{hi:>10d}] bars  N={n:4d} win={win:5.1%} brutto/T={g:+.3f} netto/T={a:+.3f} Summe={s:+.1f}"
        )

print("\nrelocated share:", sum(t["relocated"] for t in trades) / len(trades))
# quarterly stability for a few caps
print("\n== Netto-Summe R pro Quartal (Alter seit aktueller Ursprungskerze)")
for cap, label in caps:
    q = defaultdict(float)
    for t in trades:
        if cap is None or t["age_o"] <= cap:
            q[(t["entry_ts"].month - 1) // 3 + 1] += t["net_r"]
    print(f"{label:>11}: " + "  ".join(f"Q{k} {q[k]:+6.1f}" for k in (1, 2, 3, 4)))
