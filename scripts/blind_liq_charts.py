# ruff: noqa: E501
"""Blind charts to classify the liquidity distance: setups up to the entry, without result.

Usage: python scripts/blind_liq_charts.py RUN_FOLDER [--seed S]

Draws trades from bins of the distance liquidity - zone edge in ATR(14) of the strategy bars
(measured as in the strategy: ATR after the last closed bar before the sweep), in shuffled
order. Each chart shows the strategy bars from before the zone to the entry bar: zone,
liquidity P', sweep, tap, entry. No exit, no result, no distance. Writes
RUN_FOLDER/blind_liq.html (for Xaver) and RUN_FOLDER/blind_liq_key.csv (the distances; do not
show before the classification is done).
"""

import argparse
import base64
import csv
import random
from pathlib import Path

from lsdtrader.review.review import LIQ, ZONE, load_run
from lsdtrader.viz.chart import INK, Box, ChartSpec, Level, Marker, berlin_label, render

# (lower, upper, how many) in ATR
BINS = [(0, 1, 3), (1, 1.5, 3), (1.5, 2, 3), (2, 2.5, 3), (2.5, 3, 2), (3, 4, 2), (4, 99, 2)]
MARGIN = 10
MAX_BARS = 600

ap = argparse.ArgumentParser()
ap.add_argument("run", type=Path)
ap.add_argument("--seed", type=int, default=7)
args = ap.parse_args()

run = load_run(args.run)
inst, bars = run.data.instrument, run.data.bars
trades, seen = [], set()
for t in sorted(run.trades, key=lambda t: t["entry_ts"]):
    if (t["entry_ts"], t["side"]) not in seen:
        seen.add((t["entry_ts"], t["side"]))
        trades.append(t)

rng = random.Random(args.seed)
picked = []
for lo, hi, n in BINS:
    pool = [t for t in trades if lo <= t["feat_liq_dist_atr"] < hi]
    picked += rng.sample(pool, min(n, len(pool)))
rng.shuffle(picked)

out_dir = args.run / "blind_liq"
out_dir.mkdir(exist_ok=True)
sections, key = [], []
for k, t in enumerate(picked, 1):
    long = t["side"] == "long"
    entry = t["entry_bar"]
    first = max(min(t["zone_o_idx"], t["liq_idx"]) - MARGIN, entry - MAX_BARS)
    sweep_px = bars[t["sweep_idx"]].low if long else bars[t["sweep_idx"]].high
    spec = ChartSpec(
        first=first,
        last=entry,
        title=f"Setup {k}: {t['side'].upper()}, bis zum Einstieg",
        boxes=[Box(t["zone_o_idx"], entry, t["zone_top"], t["zone_bot"], ZONE, "zone")],
        levels=[Level(t["liq_idx"], t["sweep_idx"], t["liq_level"], LIQ, "liquidity P'", ":")],
        markers=[
            Marker(t["sweep_idx"], sweep_px, "sweep", LIQ, "^" if long else "v"),
            Marker(t["tap_idx"], t["zone_top"] if long else t["zone_bot"], "tap", ZONE, "D"),
            Marker(entry, t["entry_signal"], "entry", INK, ">"),
        ],
    )
    png = render(spec, bars, inst, out_dir / f"{k:02d}.png")
    img = base64.b64encode(png.read_bytes()).decode()
    sections.append(
        f"<h2>Setup {k}: {t['side']} &middot; Einstieg {berlin_label(t['entry_ts'])} Berlin &middot; "
        f"Zone {inst.to_price(t['zone_bot'])} - {inst.to_price(t['zone_top'])} &middot; "
        f"P' {inst.to_price(t['liq_level'])}</h2>"
        f'<p>Gültiges Setup &nbsp;[ ]&nbsp;&nbsp;&nbsp; Liquidität zu weit &nbsp;[ ]</p><img src="data:image/png;base64,{img}" style="width:100%">'
    )
    key.append(
        [
            k,
            t["entry_ts"],
            t["side"],
            round(t["feat_liq_dist_atr"], 2),
            round(t["feat_liq_dist_ticks"] / t["feat_zone_height_ticks"], 2),
            t["sweep_idx"],
        ]
    )

(args.run / "blind_liq.html").write_text(
    "<!doctype html><meta charset='utf-8'><title>Liquiditätsabstand blind</title>"
    "<body style='font-family:sans-serif;max-width:1400px;margin:auto;background:#fff'>"
    f"<h1>{inst.root}: {len(picked)} Setups, bitte einordnen</h1>"
    "<p>Nur bis zum Einstieg gezeigt, ohne Ergebnis. Frage je Setup: Ist die Liquidität P' "
    "für diese Zone gültig, oder liegt sie zu weit weg? Bitte nur nach dem Bild bis zum "
    "Einstieg urteilen (in TradingView nicht weiterscrollen). Antwort z. B. als Liste: "
    "1 gültig, 2 zu weit, ...</p>" + "".join(sections),
    encoding="utf-8",
)
with (args.run / "blind_liq_key.csv").open("w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["setup", "entry_ts", "side", "dist_atr14", "dist_zone_heights", "sweep_idx"])
    w.writerows(key)
print(args.run / "blind_liq.html")
