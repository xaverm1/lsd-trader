# ruff: noqa: E501
"""Charts of absorption trades to compare with TradingView: strategy-bar context + 1-minute detail.

Usage: python scripts/trade_charts.py RUN_FOLDER [--latest K] [--random N] [--seed S]
       [--since YYYY-MM-DD]

Writes RUN_FOLDER/trade_charts.html with a table (Berlin times, prices) and, per trade, the
context chart (zone, P', sweep, tap, entry, exit on the strategy bars) and the 1-minute detail
(absorption minute, its high = entry trigger, P', stop, target). Defaults: the 10 latest trades
plus 10 random older ones (seed 1).
"""

import argparse
import base64
import bisect
import html
import random
from dataclasses import replace
from pathlib import Path
from zoneinfo import ZoneInfo

from lsdtrader.review.review import LIQ, ZONE, load_run, trade_spec
from lsdtrader.viz.chart import (
    INK,
    LOSS,
    WIN,
    Box,
    ChartSpec,
    Level,
    Marker,
    Position,
    berlin_label,
    render,
)

ap = argparse.ArgumentParser()
ap.add_argument("run", type=Path)
ap.add_argument("--latest", type=int, default=10)
ap.add_argument("--random", type=int, default=10)
ap.add_argument("--seed", type=int, default=1)
ap.add_argument("--since", help="only trades entered on or after this date (YYYY-MM-DD)")
args = ap.parse_args()

run = load_run(args.run)
inst, bars, minutes = run.data.instrument, run.data.bars, run.data.minute_bars
times, mtimes = run.times, [m.ts for m in minutes]
px = inst.to_price
trades, seen = [], set()
for t in sorted(run.trades, key=lambda t: t["entry_ts"]):
    if (t["entry_ts"], t["side"]) not in seen:  # several zones can fire the same entry minute
        seen.add((t["entry_ts"], t["side"]))
        if args.since is None or t["entry_ts"].date().isoformat() >= args.since:
            trades.append(t)
latest = trades[-args.latest :] if args.latest else []
older = trades[: len(trades) - len(latest)]
picked = sorted(
    random.Random(args.seed).sample(older, min(args.random, len(older))) + latest,
    key=lambda t: t["entry_ts"],
)
out_dir = args.run / "trade_charts"


def midx(ts):  # type: ignore[no-untyped-def]
    return max(bisect.bisect_right(mtimes, ts) - 1, 0)


rows, sections = [], []
for k, t in enumerate(picked, 1):
    side, long = t["side"], t["side"] == "long"
    won = t["gross_r"] > 0
    abs_ts = t.get("feat_abs_ts")
    trig = t.get("feat_abs_high")
    trig = trig if long else (-trig if trig is not None else None)  # entry trigger in real prices
    wick = t.get("feat_abs_low")
    wick = wick if long else (-wick if wick is not None else None)
    spec = trade_spec(t, times, inst, bars)
    h2, h2_idx, bos_idx = t.get("feat_liq_h2"), t.get("feat_liq_h2_idx"), t.get("feat_liq_bos_idx")
    if h2 is not None and h2_idx is not None and bos_idx is not None:
        # the level the liquidity's BOS broke, and the BOS bar (its close beyond H2)
        spec = replace(
            spec,
            first=min(spec.first, h2_idx - 3),
            levels=[
                *spec.levels,
                Level(h2_idx, bos_idx, h2 if long else -h2, "#888780", "BOS level H2", "--"),
            ],
            markers=[
                *spec.markers,
                Marker(bos_idx, bars[bos_idx].close, "BOS of the liquidity", "#888780", "o"),
            ],
        )
    ctx = render(spec, bars, inst, out_dir / f"{k:02d}_context.png")
    e, x = midx(t["entry_ts"]), midx(t["exit_ts"])
    first = (midx(abs_ts) if abs_ts else e) - 40
    last = min(e + 40, x + 5) if x > e else e + 40
    levels = [
        Level(first, last, t["liq_level"], LIQ, "swept liquidity P'", ":"),
        Level(first, last, t["stop"], LOSS, "stop", "--"),
    ]
    markers = [Marker(e, t["entry_signal"], "entry (close)", INK, ">")]
    if trig is not None:
        levels.append(
            Level(
                midx(abs_ts),
                e,
                trig,
                INK,
                "trigger: absorption high" if long else "trigger: absorption low",
                "--",
            )
        )
        markers.append(Marker(midx(abs_ts), wick, "absorption minute", LIQ, "o"))
    if x <= last:
        markers.append(
            Marker(x, t["exit_raw"], f"exit ({t['exit_reason']})", WIN if won else LOSS, "X")
        )
    spec = ChartSpec(
        first=first,
        last=last,
        title=f"{k}. {side.upper()} - 1-minute detail - entry {berlin_label(t['entry_ts'])} Berlin",
        boxes=[Box(first, last, t["zone_top"], t["zone_bot"], ZONE, "zone")],
        levels=levels,
        position=Position(e, min(x, last), t["entry_signal"], t["stop"], t["target"]),
        markers=markers,
        info=[
            f"absorption {berlin_label(abs_ts) if abs_ts else '-'}  score {t.get('feat_abs_score') or 0:.1f}",
            f"entry {px(t['entry_signal'])}  stop {px(t['stop'])}",
            f"target {px(t['target'])}  P' {px(t['liq_level'])}",
            f"result {t['gross_r']:+.2f}R gross ({t['exit_reason']})",
        ],
    )
    det = render(spec, minutes, inst, out_dir / f"{k:02d}_detail.png")
    stamp = t["entry_ts"].astimezone(ZoneInfo("Europe/Berlin"))
    rows.append(
        f"<tr><td>{k}</td><td>{stamp:%Y-%m-%d %H:%M}</td><td>{side}</td><td>{berlin_label(abs_ts) if abs_ts else ''}</td>"
        f"<td>{px(t['entry_signal'])}</td><td>{px(t['stop'])}</td><td>{px(t['target'])}</td>"
        f"<td>{px(t['zone_bot'])} - {px(t['zone_top'])}</td><td>{px(t['liq_level'])}</td>"
        f"<td>{t['exit_reason']}</td><td>{t['gross_r']:+.2f}</td></tr>"
    )
    imgs = "".join(
        f'<img src="data:image/png;base64,{base64.b64encode(p.read_bytes()).decode()}" style="width:100%">'
        for p in (ctx, det)
    )
    sections.append(
        f"<h2 id='t{k}'>{k}. {html.escape(side)} {stamp:%Y-%m-%d %H:%M} Berlin - {t['exit_reason']} {t['gross_r']:+.2f}R</h2>{imgs}"
    )

page = args.run / "trade_charts.html"
page.write_text(
    "<!doctype html><meta charset='utf-8'><title>Absorption trades</title>"
    "<body style='font-family:sans-serif;max-width:1400px;margin:auto;background:#fff'>"
    f"<h1>{inst.root}: {len(picked)} trades ({len(latest)} latest, rest random, seed {args.seed})</h1>"
    "<p>Times Europe/Berlin. Prices of the continuous front contract (volume roll) - check the contract month in TradingView.</p>"
    "<table border=1 cellpadding=4 style='border-collapse:collapse;font-size:13px'>"
    "<tr><th>#</th><th>Entry</th><th>Side</th><th>Absorption</th><th>Entry</th><th>Stop</th><th>Target</th><th>Zone</th><th>P'</th><th>Exit</th><th>R</th></tr>"
    + "".join(rows)
    + "</table>"
    + "".join(sections),
    encoding="utf-8",
)
print(page)
