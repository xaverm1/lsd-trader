"""Acceptance review (Design §10.4): charts of randomly drawn trades and rejected setups.

`build_review` reloads a run's data, draws `n` trades and `n` rejected setups with a
recorded seed, renders one chart each and writes an index.html to look through.
"""

from __future__ import annotations

import bisect
import html
import json
import random
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from lsdtrader.core.bar import TickBar
from lsdtrader.core.instrument import Instrument
from lsdtrader.data.load import LoadedData, load_data
from lsdtrader.viz.chart import Box, ChartSpec, Level, Marker, render

REJECTION_KINDS = ("no_tap", "no_entry", "setup_zone_gone")
MARGIN = 20  # bars shown before the zone and after the end
MAX_BARS = 240  # longest chart; older parts of a zone are clipped
# A no_tap rejection is only worth reviewing when the liquidity sat close to the zone
# (a zone months old, far below price, rejects sweeps that could never tap it).
NEAR_ZONE_HEIGHTS = 3


@dataclass(frozen=True, slots=True)
class RunData:
    folder: Path
    meta: dict[str, Any]
    trades: list[dict[str, Any]]
    events: list[dict[str, Any]]
    data: LoadedData

    @property
    def times(self) -> list[datetime]:
        return [b.ts for b in self.data.bars]


def load_run(folder: Path) -> RunData:
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    files = [Path(d["path"]) for d in meta["data"]]
    data = load_data(files, meta["instrument"]["root"])
    trades = pq.read_table(folder / "trades.parquet").to_pylist()
    kinds = ["setup_started", *REJECTION_KINDS]
    events = pq.read_table(folder / "events.parquet", filters=[("kind", "in", kinds)]).to_pylist()
    return RunData(folder, meta, trades, events, data)


def bar_index(times: list[datetime], ts: datetime) -> int:
    """Index of the bar that opened at or before `ts`."""
    return max(bisect.bisect_right(times, ts) - 1, 0)


def _window(first: int, last: int) -> tuple[int, int]:
    return max(first, last - MAX_BARS), last


def trade_spec(t: dict[str, Any], times: list[datetime], inst: Instrument) -> ChartSpec:
    exit_idx = bar_index(times, t["exit_ts"])
    entry = t["entry_bar"]
    first, last = _window(min(t["zone_o_idx"], t["liq_idx"]) - MARGIN, exit_idx + MARGIN)
    color = "#1D9E75" if t["net_r"] > 0 else "#D85A30"
    price = inst.to_price
    return ChartSpec(
        first=first,
        last=last,
        title=(
            f"{t['side']} {t['setup_id']}  entry {t['entry_ts']:%Y-%m-%d %H:%M} UTC  "
            f"{t['exit_reason']}  net {t['net_r']:+.2f}R"
        ),
        boxes=[Box(t["zone_o_idx"], exit_idx, t["zone_top"], t["zone_bot"], "#534AB7", "zone")],
        levels=[
            Level(t["liq_idx"], t["sweep_idx"], t["liq_level"], "#BA7517", "liquidity P'", ":"),
            Level(entry, exit_idx, t["entry_signal"], "#444441", "entry", "-"),
            Level(entry, exit_idx, t["stop"], "#E24B4A", "SL"),
            Level(entry, exit_idx, t["target"], color, "TP"),
        ],
        markers=[
            Marker(t["sweep_idx"], t["liq_level"], "sweep", "#BA7517"),
            Marker(t["tap_idx"], t["zone_top"] if t["side"] == "long" else t["zone_bot"], "tap"),
            Marker(entry, t["entry_signal"], "entry", "#444441"),
            Marker(exit_idx, t["exit_raw"], t["exit_reason"], color),
        ],
        notes=[
            f"zone {price(t['zone_bot'])}-{price(t['zone_top'])} ({t['feat_zone_kind']})  "
            f"entry {price(t['entry_signal'])}  SL {price(t['stop'])}  TP {price(t['target'])}  "
            f"gross {t['gross_r']:+.2f}R  cost {t['cost_r']:.2f}R",
        ],
    )


@dataclass(frozen=True, slots=True)
class Rejection:
    side: str
    setup_id: int
    kind: str
    end_idx: int
    start: dict[str, Any]  # details of the setup_started event, plus its bar as sweep_idx


def near_zone(r: Rejection) -> bool:
    s = r.start
    height = s["zone_top"] - s["zone_bot"]
    dist = s["liq_price"] - s["zone_top"] if r.side == "long" else s["zone_bot"] - s["liq_price"]
    return r.kind != "no_tap" or dist <= NEAR_ZONE_HEIGHTS * height


def rejections(events: list[dict[str, Any]]) -> list[Rejection]:
    started: dict[tuple[str, int], dict[str, Any]] = {}
    out = []
    for e in events:
        detail = json.loads(e["detail"])
        key = (e["side"], detail.get("setup_id"))
        if e["kind"] == "setup_started":
            started[key] = dict(detail, sweep_idx=e["bar_index"])
        elif e["kind"] in REJECTION_KINDS and key in started:
            out.append(
                Rejection(e["side"], detail["setup_id"], e["kind"], e["bar_index"], started[key])
            )
    return out


def rejection_spec(r: Rejection, times: list[datetime], inst: Instrument) -> ChartSpec:
    s = r.start
    top, bot = s["zone_top"], s["zone_bot"]
    first, last = _window(min(s["zone_o_idx"], s["liq_idx"]) - MARGIN, r.end_idx + MARGIN)
    return ChartSpec(
        first=first,
        last=last,
        title=(
            f"REJECTED {r.side} setup {r.setup_id}: {r.kind}  "
            f"sweep {times[s['sweep_idx']]:%Y-%m-%d %H:%M} UTC"
        ),
        boxes=[Box(s["zone_o_idx"], r.end_idx, top, bot, "#534AB7", "zone")],
        levels=[
            Level(s["liq_idx"], s["sweep_idx"], s["liq_price"], "#BA7517", "liquidity P'", ":")
        ],
        markers=[
            Marker(s["sweep_idx"], s["liq_price"], "sweep", "#BA7517"),
            Marker(r.end_idx, top if r.side == "long" else bot, r.kind, "#E24B4A"),
        ],
        notes=[
            f"reason: {r.kind}  zone {inst.to_price(bot)}-{inst.to_price(top)}  "
            f"liquidity {inst.to_price(s['liq_price'])}"
        ],
    )


def build_review(folder: Path, n: int = 10, seed: int = 1) -> Path:
    run = load_run(folder)
    times = run.times
    rng = random.Random(seed)
    trades = rng.sample(run.trades, min(n, len(run.trades)))
    rejected = [r for r in rejections(run.events) if near_zone(r)]
    rejected = rng.sample(rejected, min(n, len(rejected)))
    out = folder / f"review_seed{seed}"
    bars: list[TickBar] = run.data.bars
    inst = run.data.instrument
    items: list[tuple[str, str, str]] = []
    for i, t in enumerate(trades, 1):
        name = f"trade_{i:02d}.png"
        spec = trade_spec(t, times, inst)
        render(spec, bars, inst, out / name)
        items.append((name, spec.title, "Trade"))
    for i, r in enumerate(rejected, 1):
        name = f"rejected_{i:02d}.png"
        spec = rejection_spec(r, times, inst)
        render(spec, bars, inst, out / name)
        items.append((name, spec.title, "Rejected setup"))
    write_index(out, run, seed, items)
    return out / "index.html"


def write_index(out: Path, run: RunData, seed: int, items: list[tuple[str, str, str]]) -> None:
    rows = "\n".join(
        f"<section><h2>{html.escape(kind)} {i}</h2><p>{html.escape(title)}</p>"
        f'<img src="{name}" alt="{html.escape(title)}"></section>'
        for i, (name, title, kind) in enumerate(items, 1)
    )
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Review {html.escape(run.folder.name)}</title>
<style>body{{font-family:sans-serif;max-width:1400px;margin:auto;padding:16px}}
img{{width:100%;border:1px solid #ccc}}section{{margin-bottom:32px}}</style></head><body>
<h1>Review of {html.escape(run.folder.name)}</h1>
<p>Instrument {html.escape(run.data.instrument.root)} · seed {seed} · times in UTC.
For each chart: does it follow the rules? Note the number of every chart that does not.</p>
{rows}
</body></html>
"""
    (out / "index.html").write_text(page, encoding="utf-8")
