# ruff: noqa: E501
"""Charts to check the reclaim entry: per trade the strategy-bar context and the 1-minute detail.

Usage: python scripts/reclaim_charts.py RUN_FOLDER [N=10] [SEED=1]

Draws N random trades (seeded) and writes RUN_FOLDER/reclaim_charts.html with both charts of
each trade embedded. The 1-minute chart runs from the start of the tap bar to 30 minutes
after the entry (or the exit, if earlier) and shows the swept liquidity the entry must close
back beyond.
"""

import base64
import bisect
import random
import sys
from datetime import timedelta
from pathlib import Path

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

folder = Path(sys.argv[1])
n = int(sys.argv[2]) if len(sys.argv) > 2 else 10
seed = int(sys.argv[3]) if len(sys.argv) > 3 else 1
run = load_run(folder)
inst, bars, minutes = run.data.instrument, run.data.bars, run.data.minute_bars
bar_len = timedelta(minutes=run.meta["execution_config"].get("bar_minutes", 5))
times, mtimes = run.times, [m.ts for m in minutes]
out_dir = folder / "reclaim_charts"
picked = random.Random(seed).sample(run.trades, min(n, len(run.trades)))


def minute_idx(ts):  # type: ignore[no-untyped-def]
    return max(bisect.bisect_right(mtimes, ts) - 1, 0)


sections = []
for k, t in enumerate(sorted(picked, key=lambda t: t["entry_ts"])):
    ctx = render(trade_spec(t, times, inst, bars), bars, inst, out_dir / f"{k:02d}_context.png")
    side, won = t["side"], t["net_r"] > 0
    tap_start = times[t["tap_idx"]]
    first = minute_idx(tap_start) - 15
    entry_m = minute_idx(t["entry_ts"])
    exit_m = minute_idx(t["exit_ts"])
    last = min(entry_m + 30, exit_m + 5) if exit_m > entry_m else entry_m + 30
    last = min(last, first + 240)
    pre = [m for m in minutes[first:entry_m] if m.ts >= tap_start + bar_len]
    spec = ChartSpec(
        first=first,
        last=last,
        title=f"{side.upper()} {t['setup_id']} - 1-minute entry detail - entry {berlin_label(t['entry_ts'])} Berlin",
        boxes=[Box(first, last, t["zone_top"], t["zone_bot"], ZONE, "zone")],
        levels=[Level(first, last, t["liq_level"], LIQ, "swept liquidity P'", ":")],
        position=Position(entry_m, min(exit_m, last), t["entry_signal"], t["stop"], t["target"]),
        markers=[
            Marker(entry_m, t["entry_signal"], "reclaim close = entry", INK, ">"),
            Marker(exit_m, t["exit_raw"], f"exit ({t['exit_reason']})", WIN if won else LOSS, "X"),
        ],
        info=[
            f"tap bar {berlin_label(tap_start)} (+{bar_len.seconds // 60} min)",
            f"minutes checked before entry: {len(pre)}",
            f"entry {inst.to_price(t['entry_signal'])}  P' {inst.to_price(t['liq_level'])}",
            f"stop  {inst.to_price(t['stop'])}  target {inst.to_price(t['target'])}",
            f"result {t['gross_r']:+.2f}R gross",
        ],
        vline=minute_idx(tap_start + bar_len),
        notes=["dashed line: close of the tap bar - reclaim minutes count only after it"],
    )
    det = render(spec, minutes, inst, out_dir / f"{k:02d}_detail.png")
    imgs = "".join(
        f'<img src="data:image/png;base64,{base64.b64encode(p.read_bytes()).decode()}" style="width:100%">'
        for p in (ctx, det)
    )
    sections.append(
        f"<h2>{k + 1}. {side} {t['setup_id']} - {t['exit_reason']} {t['gross_r']:+.2f}R</h2>{imgs}"
    )

page = folder / "reclaim_charts.html"
page.write_text(
    "<!doctype html><meta charset='utf-8'><title>Reclaim entries</title>"
    "<body style='font-family:sans-serif;max-width:1400px;margin:auto;background:#fff'>"
    f"<h1>Reclaim entries - {inst.root}, {len(picked)} random trades (seed {seed})</h1>"
    + "".join(sections),
    encoding="utf-8",
)
print(page)
