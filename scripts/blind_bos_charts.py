# ruff: noqa: E501
"""Blind charts to classify which BOS makes a swing low liquidity (Xaver's judgement).

Usage: python scripts/blind_bos_charts.py RUN_FOLDER [--seed S] [--per-cell K]

Every distinct liquidity of the run's trades (bar + side) is scored on three candidate
criteria, and K examples are drawn from each combination so that the criteria disagree:
  A  the broken level H2 is a swing high with 3 bars on each side (right side before the BOS)
  B  the move from H2 down to the liquidity is at least 1 ATR(14) (ATR after the BOS bar)
  C  the BOS bar closes above the highest high of the 12 bars (6 h) before it
The charts show the strategy bars from 40 bars before the liquidity to the sweep (at most 60
bars after the BOS): the
liquidity, the level its BOS broke, the BOS bar and the sweep. No zone, no trade, no result.
Writes RUN_FOLDER/blind_bos.html and RUN_FOLDER/blind_bos_key.csv (the scores; do not show
before the classification is done).
"""

import argparse
import base64
import csv
import itertools
import random
from pathlib import Path

from lsdtrader.core.bar import TickBar
from lsdtrader.review.review import LIQ, load_run
from lsdtrader.strategy.atr import Atr
from lsdtrader.viz.chart import ChartSpec, Level, Marker, berlin_label, render

ap = argparse.ArgumentParser()
ap.add_argument("run", type=Path)
ap.add_argument("--seed", type=int, default=11)
ap.add_argument("--per-cell", type=int, default=2)
ap.add_argument("--exclude", type=Path, help="key CSV of an earlier batch: skip its examples")
ap.add_argument("--start", type=int, default=1, help="number of the first example")
ap.add_argument("--name", default="blind_bos", help="output name (html, key csv, png folder)")
args = ap.parse_args()

run = load_run(args.run)
inst, bars = run.data.instrument, run.data.bars
atr_calc = Atr(14)
atr = [atr_calc.update(b) for b in bars]


def side_bars(side: str) -> list[TickBar]:
    return bars if side == "long" else [b.mirrored() for b in bars]


mirrored = [b.mirrored() for b in bars]
liqs: dict[tuple[int, str], dict] = {}
for t in sorted(run.trades, key=lambda t: t["entry_ts"]):
    liqs.setdefault((t["liq_idx"], t["side"]), t)

rows = []
for (_liq_idx, side), t in liqs.items():
    bs = bars if side == "long" else mirrored
    h2, c, bos = t["feat_liq_h2"], t["feat_liq_h2_idx"], t["feat_liq_bos_idx"]
    p = t["liq_level"] if side == "long" else -t["liq_level"]
    if h2 is None or c is None or bos is None or atr[bos] is None:
        continue
    a = (
        c - 3 >= 0
        and c + 3 < bos
        and all(bs[c - k].high <= h2 and bs[c + k].high < h2 for k in range(1, 4))
    )
    b = (h2 - p) / atr[bos] >= 1.0
    cc = bs[bos].close > max(x.high for x in bs[max(bos - 12, 0) : bos])
    rows.append((t, a, b, cc, (h2 - p) / atr[bos]))

if args.exclude:
    with args.exclude.open() as fh:
        shown = {(r["side"], r["liq_ts"]) for r in csv.DictReader(fh)}
    rows = [r for r in rows if (r[0]["side"], str(bars[r[0]["liq_idx"]].ts)) not in shown]
from collections import Counter  # noqa: E402

print("per cell (A, B, C):", dict(Counter((r[1], r[2], r[3]) for r in rows)))
rng = random.Random(args.seed)
picked = []
for cell in itertools.product((True, False), repeat=3):
    pool = [r for r in rows if (r[1], r[2], r[3]) == cell]
    picked += rng.sample(pool, min(args.per_cell, len(pool)))
rng.shuffle(picked)

out_dir = args.run / args.name
out_dir.mkdir(exist_ok=True)
sections, key = [], []
for k, (t, a, b, cc, legatr) in enumerate(picked, args.start):
    long = t["side"] == "long"
    h2 = t["feat_liq_h2"] if long else -t["feat_liq_h2"]
    bos, c = t["feat_liq_bos_idx"], t["feat_liq_h2_idx"]
    first = min(t["liq_idx"], c) - 40
    last = min(t["sweep_idx"], max(t["liq_idx"], bos) + 60)  # formation; the sweep if near
    spec = ChartSpec(
        first=first,
        last=last,
        title=f"Beispiel {k}: Tief/Hoch als Liquidität für {'Long' if long else 'Short'}?",
        levels=[
            Level(t["liq_idx"], last, t["liq_level"], LIQ, "Liquidität?", ":"),
            Level(c, bos, h2, "#555555", "gebrochenes Level", "--"),
        ],
        markers=[Marker(bos, bars[bos].close, "BOS (Close)", "#555555", "o")]
        + (
            [
                Marker(
                    t["sweep_idx"],
                    bars[t["sweep_idx"]].low if long else bars[t["sweep_idx"]].high,
                    "Sweep",
                    LIQ,
                    "^" if long else "v",
                )
            ]
            if last == t["sweep_idx"]
            else []
        ),
    )
    png = render(spec, bars, inst, out_dir / f"{k:02d}.png")
    img = base64.b64encode(png.read_bytes()).decode()
    sections.append(
        f"<h2>Beispiel {k}: {'Long' if long else 'Short'} &middot; Liquidität {inst.to_price(t['liq_level'])} "
        f"({berlin_label(bars[t['liq_idx']].ts)}) &middot; BOS {berlin_label(bars[bos].ts)} Berlin</h2>"
        f"<p>Echte Liquidität &nbsp;[ ]&nbsp;&nbsp;&nbsp; keine Liquidität &nbsp;[ ]</p>"
        f'<img src="data:image/png;base64,{img}" style="width:100%">'
    )
    key.append(
        [
            k,
            t["side"],
            bars[t["liq_idx"]].ts,
            bars[bos].ts,
            int(a),
            int(b),
            int(cc),
            round(legatr, 2),
        ]
    )

(args.run / f"{args.name}.html").write_text(
    "<!doctype html><meta charset='utf-8'><title>BOS blind</title>"
    "<body style='font-family:sans-serif;max-width:1400px;margin:auto;background:#fff'>"
    f"<h1>{inst.root}: Beispiele {args.start}-{args.start + len(picked) - 1}, bitte einordnen</h1>"
    "<p>30-min-Kerzen bis zum Sweep (höchstens 60 Kerzen nach dem BOS; liegt der Sweep später, fehlt er im Bild). Gepunktet: das Tief (bei Short: Hoch), das der Code als "
    "Liquidität nimmt. Gestrichelt: das Level, dessen Bruch (Close, grauer Punkt) es zur "
    "Liquidität gemacht hat. Frage: Ist das für dich echte Liquidität? Antwort z. B. "
    "1 ja, 2 nein, ... gern mit kurzem Grund bei den Neins.</p>" + "".join(sections),
    encoding="utf-8",
)
with (args.run / f"{args.name}_key.csv").open("w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(
        [
            "beispiel",
            "side",
            "liq_ts",
            "bos_ts",
            "A_pivot3",
            "B_leg_ge_1atr",
            "C_close_above_6h_high",
            "leg_atr",
        ]
    )
    w.writerows(key)
print(args.run / f"{args.name}.html", len(rows), "liquidities,", len(picked), "picked")
