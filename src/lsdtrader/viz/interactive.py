"""Interactive chart of a whole run: every trade on one scrollable candlestick chart.

`write_interactive_chart` writes a single self-contained HTML file (TradingView Lightweight
Charts is embedded, so it works offline). Times are shifted to Europe/Berlin wall-clock time,
because the chart library displays timestamps as UTC. CME-style markets are closed on the
Sunday mornings when Berlin changes its clocks, so the shift never makes two bars collide.

Concurrent trades cannot share one line series (points must be in time order), so trades are
spread over a few "lanes"; each lane is one set of line series. Line series ignore whitespace
and join consecutive points; a segment takes the colour of its start point, so the last point
of each trade is transparent, which hides the link to the next trade in the lane.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from lsdtrader.core.bar import TickBar
from lsdtrader.core.instrument import Instrument
from lsdtrader.review.review import RunData, bar_index
from lsdtrader.viz.chart import BERLIN, MIN_POSITION_BARS

ASSETS = Path(__file__).parent / "assets"
TRANSPARENT = "rgba(0,0,0,0)"
LIBRARY = ASSETS / "lightweight-charts.standalone.production.js"


def berlin_epoch(ts: datetime) -> int:
    """Seconds since epoch of the Berlin wall-clock time, for display as 'UTC' in the chart."""
    local = ts.astimezone(BERLIN)
    return int(ts.timestamp()) + int(local.utcoffset().total_seconds())  # type: ignore[union-attr]


def assign_lanes(intervals: Sequence[tuple[int, int]]) -> list[int]:
    """Smallest lane number per interval so that intervals in one lane never overlap.

    Intervals are (start, end) bar indices, inclusive, in any order; returns one lane each.
    One free bar is kept between intervals of a lane for the whitespace point that ends a line.
    """
    order = sorted(range(len(intervals)), key=lambda i: intervals[i])
    lane_end: list[int] = []
    lanes = [0] * len(intervals)
    for i in order:
        start, end = intervals[i]
        for lane, last in enumerate(lane_end):
            if last + 1 < start:
                lane_end[lane] = end
                lanes[i] = lane
                break
        else:
            lane_end.append(end)
            lanes[i] = len(lane_end) - 1
    return lanes


def _price(inst: Instrument, ticks: int) -> float:
    return float(inst.to_price(ticks))


def chart_data(run: RunData) -> dict[str, Any]:
    """Candles, trades and line-series lanes as JSON-ready data."""
    bars: list[TickBar] = run.data.bars
    inst = run.data.instrument
    times = [b.ts for b in bars]
    t = [berlin_epoch(ts) for ts in times]
    candles = [
        {
            "time": t[i],
            "open": _price(inst, b.open),
            "high": _price(inst, b.high),
            "low": _price(inst, b.low),
            "close": _price(inst, b.close),
        }
        for i, b in enumerate(bars)
    ]
    trades = []
    for n, row in enumerate(sorted(run.trades, key=lambda r: r["entry_bar"])):
        exit_idx = bar_index(times, row["exit_ts"])
        start = min(row["zone_o_idx"], row["liq_idx"])
        # entry/SL/TP lines at least MIN_POSITION_BARS long, as in the static charts
        pos_end = min(max(exit_idx, row["entry_bar"] + MIN_POSITION_BARS), len(bars) - 1)
        trades.append(
            {
                "n": n + 1,
                "id": row["setup_id"],
                "side": row["side"],
                "start": start,
                "entry": row["entry_bar"],
                "exit": exit_idx,
                "pos_end": pos_end,
                "entry_time": t[row["entry_bar"]],
                "exit_time": t[exit_idx],
                "label": f"{row['entry_ts'].astimezone(BERLIN):%Y-%m-%d %H:%M}",
                "entry_price": _price(inst, row["entry_signal"]),
                "stop": _price(inst, row["stop"]),
                "target": _price(inst, row["target"]),
                "exit_price": _price(inst, row["exit_raw"]),
                "zone_top": _price(inst, row["zone_top"]),
                "zone_bot": _price(inst, row["zone_bot"]),
                "liq": _price(inst, row["liq_level"]),
                "liq_idx": row["liq_idx"],
                "sweep": row["sweep_idx"],
                "exit_reason": row["exit_reason"],
                "net_r": round(row["net_r"], 2),
            }
        )
    lanes = assign_lanes([(tr["start"], max(tr["exit"], tr["pos_end"])) for tr in trades])
    return {
        "instrument": inst.root,
        "run": run.folder.name,
        "candles": candles,
        "trades": trades,
        "lanes": _lane_series(trades, lanes, t),
    }


def _lane_series(
    trades: list[dict[str, Any]], lanes: list[int], t: list[int]
) -> list[dict[str, list[dict[str, Any]]]]:
    """Per lane: point lists for zone top/bottom, P', entry, stop, target.

    Each trade's segment ends in a transparent point, so segments are not joined.
    """
    kinds = ("zone_top", "zone_bot", "liq", "entry_price", "stop", "target")
    out: list[dict[str, list[dict[str, Any]]]] = [
        {k: [] for k in kinds} for _ in range(max(lanes, default=-1) + 1)
    ]
    spans = {
        "zone_top": ("start", "exit"),
        "zone_bot": ("start", "exit"),
        "liq": ("liq_idx", "sweep"),
        "entry_price": ("entry", "pos_end"),
        "stop": ("entry", "pos_end"),
        "target": ("entry", "pos_end"),
    }
    for tr, lane in sorted(zip(trades, lanes, strict=True), key=lambda p: p[0]["start"]):
        for kind in kinds:
            a, b = (tr[s] for s in spans[kind])
            points = out[lane][kind]
            if b > a:
                points.append({"time": t[a], "value": tr[kind]})
            points.append({"time": t[b], "value": tr[kind], "color": TRANSPARENT})
    return out


def write_interactive_chart(run: RunData, out: Path | None = None) -> Path:
    out = out or run.folder / "chart.html"
    data = json.dumps(chart_data(run), separators=(",", ":"))
    library = LIBRARY.read_text(encoding="utf-8")
    page = TEMPLATE.replace("/*LIBRARY*/", library).replace("/*DATA*/", data)
    out.write_text(page, encoding="utf-8")
    return out


TEMPLATE = """<!doctype html>
<html lang="de"><head><meta charset="utf-8"><title>LSD trades</title>
<style>
body{margin:0;font-family:system-ui,sans-serif;display:flex;height:100vh;
background:#fff;color:#1a1a1a}
#chart{flex:1;min-width:0}
#side{width:340px;overflow:auto;border-left:1px solid #ddd;font-size:13px}
#side h1{font-size:15px;margin:10px}
#side p{margin:0 10px 8px;color:#555}
table{border-collapse:collapse;width:100%}
td,th{padding:4px 6px;border-bottom:1px solid #eee;text-align:left;cursor:pointer}
tr:hover{background:#f3f1fe} .win{color:#0f6e56} .loss{color:#a32d2d}
th{position:sticky;top:0;background:#fff}
</style></head><body>
<div id="chart"></div>
<div id="side"><h1 id="title"></h1><p>Klick auf einen Trade springt dorthin.
Scrollen/Ziehen bewegt den Chart, Mausrad zoomt. Zeiten: Europe/Berlin.</p>
<table><thead><tr><th>#</th><th>Entry</th><th>Seite</th><th>Exit</th><th>R</th></tr></thead>
<tbody id="rows"></tbody></table></div>
<script>/*LIBRARY*/</script>
<script>
const D = /*DATA*/;
const LW = LightweightCharts;
document.getElementById('title').textContent =
  `${D.instrument} - ${D.trades.length} Trades - ${D.run}`;
const chart = LW.createChart(document.getElementById('chart'), {
  autoSize: true,
  timeScale: {timeVisible: true, secondsVisible: false, rightOffset: 10},
  crosshair: {mode: LW.CrosshairMode.Normal},
});
const candles = chart.addSeries(LW.CandlestickSeries, {
  upColor: '#1D9E75', downColor: '#D85A30', borderVisible: false,
  wickUpColor: '#1D9E75', wickDownColor: '#D85A30',
});
candles.setData(D.candles);
const style = {
  zone_top: {color: '#534AB7', lineWidth: 2},
  zone_bot: {color: '#534AB7', lineWidth: 2},
  liq: {color: '#BA7517', lineWidth: 1, lineStyle: LW.LineStyle.Dotted},
  entry_price: {color: '#2C2C2A', lineWidth: 2},
  stop: {color: '#E24B4A', lineWidth: 1, lineStyle: LW.LineStyle.Dashed},
  target: {color: '#1D9E75', lineWidth: 1, lineStyle: LW.LineStyle.Dashed},
};
for (const lane of D.lanes) {
  for (const [kind, points] of Object.entries(lane)) {
    const s = chart.addSeries(LW.LineSeries, Object.assign({
      priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
      pointMarkersVisible: false,
    }, style[kind]));
    s.setData(points);
  }
}
const markers = [];
for (const tr of D.trades) {
  const long = tr.side === 'long';
  markers.push({time: tr.entry_time, position: long ? 'belowBar' : 'aboveBar',
    shape: long ? 'arrowUp' : 'arrowDown', color: '#2C2C2A', text: `#${tr.n}`});
  markers.push({time: tr.exit_time, position: long ? 'aboveBar' : 'belowBar',
    shape: 'circle', color: tr.net_r > 0 ? '#1D9E75' : '#E24B4A',
    text: `${tr.net_r > 0 ? '+' : ''}${tr.net_r}R`});
}
markers.sort((a, b) => a.time - b.time);
LW.createSeriesMarkers(candles, markers);
const rows = document.getElementById('rows');
for (const tr of D.trades) {
  const row = document.createElement('tr');
  row.innerHTML = `<td>${tr.n}</td><td>${tr.label}</td><td>${tr.side}</td>` +
    `<td>${tr.exit_reason}</td><td class="${tr.net_r > 0 ? 'win' : 'loss'}">${tr.net_r}</td>`;
  row.onclick = () => chart.timeScale().setVisibleRange({
    from: D.candles[Math.max(tr.start - 20, 0)].time,
    to: D.candles[Math.min(tr.exit + 30, D.candles.length - 1)].time,
  });
  rows.appendChild(row);
}
if (D.trades.length) rows.firstChild.onclick();
</script></body></html>
"""
