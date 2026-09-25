"""Acceptance review (Design §10.4): charts of randomly drawn trades and rejected setups.

`build_review` reloads a run's data, draws `n` trades and `n` rejected setups with a
recorded seed, renders one chart each and writes an index.html to look through.
"""

from __future__ import annotations

import bisect
import html
import json
import random
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from lsdtrader.core.bar import TickBar
from lsdtrader.core.instrument import Instrument
from lsdtrader.data.load import LoadedData, load_data
from lsdtrader.journal.writer import sha256_file
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

REJECTION_KINDS = ("no_tap", "no_entry", "setup_zone_gone")
MARGIN = 20  # bars shown before the zone and after the end
MAX_BARS = 240  # longest chart; older parts of a zone are clipped
# A no_tap rejection is only worth reviewing when the liquidity sat close to the zone
# (a zone months old, far below price, rejects sweeps that could never tap it).
NEAR_ZONE_HEIGHTS = 3
ZONE, LIQ = "#534AB7", "#BA7517"


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
    for entry, path in zip(meta["data"], files, strict=True):
        if not path.exists():
            raise SystemExit(f"data file of this run not found: {path}")
        if sha256_file(path) != entry["sha256"]:
            raise SystemExit(f"{path} changed since the run; charts would show the wrong bars")
    bar_minutes = meta["execution_config"].get("bar_minutes", 5)
    data = load_data(files, meta["instrument"]["root"], bar_minutes)
    if len(data.bars) != meta["n_bars"]:
        raise SystemExit(f"run had {meta['n_bars']} bars, the data now gives {len(data.bars)}")
    trades = pq.read_table(folder / "trades.parquet").to_pylist()
    kinds = ["setup_started", *REJECTION_KINDS]
    events = pq.read_table(folder / "events.parquet", filters=[("kind", "in", kinds)]).to_pylist()
    return RunData(folder, meta, trades, events, data)


def bar_index(times: list[datetime], ts: datetime) -> int:
    """Index of the bar that opened at or before `ts`."""
    return max(bisect.bisect_right(times, ts) - 1, 0)


def _window(first: int, anchor: int, last: int) -> tuple[int, int]:
    """Bars to show. Prefer [first, last]; if that is longer than MAX_BARS, keep the setup
    (everything up to `anchor`) and clip the aftermath, then the oldest part of the zone."""
    if last - first <= MAX_BARS:
        return first, last
    end = max(anchor, first + MAX_BARS)
    return end - MAX_BARS, end


def _wick(bars: Sequence[TickBar], idx: int, side: str) -> int:
    """The wick that did the work: the low for a long, the high for a short."""
    return bars[idx].low if side == "long" else bars[idx].high


def trade_spec(
    t: dict[str, Any], times: list[datetime], inst: Instrument, bars: Sequence[TickBar]
) -> ChartSpec:
    exit_idx = bar_index(times, t["exit_ts"])
    entry = t["entry_bar"]
    side = t["side"]
    first, last = _window(
        min(t["zone_o_idx"], t["liq_idx"]) - MARGIN, entry + MARGIN, exit_idx + MARGIN
    )
    price = inst.to_price
    risk = abs(t["entry_signal"] - t["stop"])
    rr = abs(t["target"] - t["entry_signal"]) / risk if risk else 0.0
    won = t["net_r"] > 0
    return ChartSpec(
        first=first,
        last=last,
        title=(
            f"{side.upper()} {t['setup_id']} - entry {berlin_label(t['entry_ts'])} Berlin - "
            f"{t['exit_reason'].upper()} {t['net_r']:+.2f}R"
        ),
        boxes=[Box(t["zone_o_idx"], exit_idx, t["zone_top"], t["zone_bot"], ZONE, "zone")],
        levels=[Level(t["liq_idx"], t["sweep_idx"], t["liq_level"], LIQ, "liquidity P'", ":")],
        position=Position(entry, exit_idx, t["entry_signal"], t["stop"], t["target"]),
        markers=[
            Marker(
                t["sweep_idx"],
                _wick(bars, t["sweep_idx"], side),
                "sweep",
                LIQ,
                "v" if side == "short" else "^",
            ),
            Marker(
                t["tap_idx"], t["zone_top"] if side == "long" else t["zone_bot"], "tap", ZONE, "D"
            ),
            Marker(entry, t["entry_signal"], "entry", INK, ">"),
            Marker(
                exit_idx, t["exit_raw"], f"exit ({t['exit_reason']})", WIN if won else LOSS, "X"
            ),
        ],
        info=[
            f"{side.upper()}  {t['exit_reason'].upper()}  {t['net_r']:+.2f}R net",
            f"Entry {price(t['entry_signal'])}",
            f"SL    {price(t['stop'])}",
            f"TP    {price(t['target'])}   RR {rr:.1f}",
            f"Zone  {price(t['zone_bot'])} - {price(t['zone_top'])} ({t['feat_zone_kind']})",
            f"P'    {price(t['liq_level'])}",
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


def rejection_spec(
    r: Rejection, times: list[datetime], inst: Instrument, bars: Sequence[TickBar]
) -> ChartSpec:
    s = r.start
    top, bot = s["zone_top"], s["zone_bot"]
    end = r.end_idx + MARGIN
    first, last = _window(min(s["zone_o_idx"], s["liq_idx"]) - MARGIN, end, end)
    price = inst.to_price
    return ChartSpec(
        first=first,
        last=last,
        title=(
            f"REJECTED {r.side.upper()} setup {r.setup_id}: {r.kind} - "
            f"sweep {berlin_label(times[s['sweep_idx']])} Berlin"
        ),
        boxes=[Box(s["zone_o_idx"], r.end_idx, top, bot, ZONE, "zone")],
        levels=[Level(s["liq_idx"], s["sweep_idx"], s["liq_price"], LIQ, "liquidity P'", ":")],
        markers=[
            Marker(
                s["sweep_idx"],
                _wick(bars, s["sweep_idx"], r.side),
                "sweep",
                LIQ,
                "v" if r.side == "short" else "^",
            ),
            Marker(r.end_idx, _wick(bars, r.end_idx, r.side), f"rejected ({r.kind})", LOSS, "X"),
        ],
        info=[
            f"{r.side.upper()}  rejected: {r.kind}",
            f"Zone  {price(bot)} - {price(top)}",
            f"P'    {price(s['liq_price'])}",
        ],
        vline=r.end_idx,
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
        spec = trade_spec(t, times, inst, bars)
        render(spec, bars, inst, out / name)
        items.append((name, spec.title, "Trade"))
    for i, r in enumerate(rejected, 1):
        name = f"rejected_{i:02d}.png"
        spec = rejection_spec(r, times, inst, bars)
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
<p>Instrument {html.escape(run.data.instrument.root)} · seed {seed} · times in Europe/Berlin.
For each chart: does it follow the rules? Note the number of every chart that does not.</p>
{rows}
</body></html>
"""
    (out / "index.html").write_text(page, encoding="utf-8")
