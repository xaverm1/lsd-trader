# ruff: noqa: E501, B905
"""RD-TREE v3 criteria on an existing run (post-hoc, gross R, exact: filters only remove trades).

Usage: python scripts/rd_tree.py RUN_FOLDER [TP ...]   (default TP 4 and 6)

Per trade the run records trend candidates (+1 with the trade, -1 against, 0 unclear) and the
distance to the nearest untouched swing high/low in R. A target of X R makes +X if the run-up
without take profit reached X, else the free exit (see take_profit.py).
Criterion "against" as in the vault: trend against or unclear = 1; no key level, or the level
closer than k R = 1. RD-TREE: take if at most 1 against.
"""

import math
import sys
from itertools import product

import pyarrow.parquet as pq

run = sys.argv[1]
tps = [float(x) for x in sys.argv[2:]] or [4.0, 6.0]
trades = [
    t for t in pq.read_table(f"{run}/trades.parquet").to_pylist() if t["mfe_free_r"] is not None
]
EXT = ["trend_bos5", "trend_bos10", "trend_bos20", "trend_hhhl48", "trend_hhhl144"]
INT = ["trend_bos1", "trend_bos2", "trend_bos5"]
LEVELS = ["level5_r", "level10_r", "level20_r"]
KS = [0.0, 3.0, 6.0]


def r_at(t: dict, tp: float) -> float:
    return tp if t["mfe_free_r"] >= tp else t["exit_free_r"]


def stats(rs: list[float]) -> str:
    n = len(rs)
    if n < 2:
        return f"N={n:4d}"
    m = sum(rs) / n
    sd = math.sqrt(sum((r - m) ** 2 for r in rs) / (n - 1))
    t = m / sd * math.sqrt(n) if sd else float("nan")
    return f"N={n:4d} R/T={m:+.3f} t={t:+.2f}"


def pot_against(t: dict, lv: str, k: float) -> bool:
    d = t[f"feat_{lv}"]
    return d is None or d < k if k else d is None


print(f"{run}: {len(trades)} trades, gross R\n")
for tp in tps:
    base = [r_at(t, tp) for t in trades]
    print(f"===== TP {tp:g} R | all trades: {stats(base)}")
    print("\n-- Trend criteria alone (with / unclear / against)")
    for f in EXT + INT:
        cells = []
        for v, lab in ((1, "with"), (0, "unclear"), (-1, "against")):
            cells.append(f"{lab}: {stats([r_at(t, tp) for t in trades if t['feat_' + f] == v])}")
        print(f"  {f:14s} " + " | ".join(cells))
    print("\n-- Potential alone (level exists and >= k R away / not)")
    for lv, k in product(LEVELS, KS):
        ok = [r_at(t, tp) for t in trades if not pot_against(t, lv, k)]
        no = [r_at(t, tp) for t in trades if pot_against(t, lv, k)]
        print(f"  {lv:10s} k={k:g}: yes {stats(ok)} | no {stats(no)}")
    print("\n-- RD-TREE counter (take if <= 1 against), all combinations")
    rows = []
    for e, i, lv, k in product(EXT, INT, LEVELS, KS):
        taken = []
        for t in trades:
            against = (t["feat_" + e] != 1) + (t["feat_" + i] != 1) + pot_against(t, lv, k)
            if against <= 1:
                taken.append(r_at(t, tp))
        rows.append((e, i, lv, k, taken))
    for e, i, lv, k, taken in rows:
        print(f"  {e:13s} {i:10s} {lv:9s} k={k:g}: {stats(taken)}")
    print()
