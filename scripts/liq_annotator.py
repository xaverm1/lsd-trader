# ruff: noqa: E501
"""Annotation page: Xaver marks where he sees liquidity, each with the level whose break made it
liquidity and the bar that broke it.

Usage: python scripts/liq_annotator.py RUN_FOLDER [--n N] [--seed S] [--since YYYY-MM-DD]
       [--exclude liq_marks.json ...] [--name OUT]

Writes RUN_FOLDER/liq_annotate.html: one chart per setup (strategy bars from before the zone
to the entry; zone and entry shown, the code's liquidity hidden until "Code zeigen"). One
liquidity is three clicks: (1) its high/low, (2) the broken level (a low/high), (3) the BOS
bar (skippable: then the first close beyond the level counts). Clicks snap to the high or low
of the clicked bar, whichever is nearer. Marks stay in the browser (localStorage) and are
exported with "Download" as liq_marks.json. Contains price data: never commit the output.
"""

import argparse
import json
import random
from pathlib import Path
from zoneinfo import ZoneInfo

from lsdtrader.review.review import load_run

BERLIN = ZoneInfo("Europe/Berlin")
BEFORE = 30  # bars shown before the zone origin
MAX_BARS = 320

ap = argparse.ArgumentParser()
ap.add_argument("run", type=Path)
ap.add_argument("--n", type=int, default=20)
ap.add_argument("--seed", type=int, default=5)
ap.add_argument("--since", default="2026-01-01")
ap.add_argument(
    "--exclude", nargs="*", type=Path, default=[], help="liq_marks.json of earlier batches"
)
ap.add_argument("--name", default="liq_annotate", help="output file name (without .html)")
args = ap.parse_args()
shown = {
    (s["entry_utc"], s["side"]) for f in args.exclude for s in json.loads(f.read_text())["setups"]
}

run = load_run(args.run)
inst, bars = run.data.instrument, run.data.bars
px = inst.to_price
trades, seen = [], set()
for t in sorted(run.trades, key=lambda t: t["entry_ts"]):
    if (
        (t["entry_ts"], t["side"]) not in seen
        and (t["entry_ts"].isoformat(), t["side"]) not in shown
        and t["entry_ts"].date().isoformat() >= args.since
    ):
        seen.add((t["entry_ts"], t["side"]))
        trades.append(t)
picked = sorted(
    random.Random(args.seed).sample(trades, min(args.n, len(trades))), key=lambda t: t["entry_ts"]
)


def real(t: dict, key: str) -> float | None:
    v = t.get(key)
    if v is None:
        return None
    return float(px(v if t["side"] == "long" else -v))


setups = []
for k, t in enumerate(picked, 1):
    e = t["entry_bar"]
    first = max(min(t["zone_o_idx"], t["liq_idx"]) - BEFORE, e - MAX_BARS, 0)
    last = min(e + 2, len(bars) - 1)
    h2_idx = t.get("feat_liq_h2_idx")
    setups.append(
        {
            "id": k,
            "side": t["side"],
            "entry_utc": t["entry_ts"].isoformat(),
            "entry_berlin": t["entry_ts"].astimezone(BERLIN).strftime("%d.%m.%Y %H:%M"),
            "first": first,
            "bars": [
                [
                    b.ts.isoformat(),
                    b.ts.astimezone(BERLIN).strftime("%d.%m %H:%M"),
                    float(px(b.open)),
                    float(px(b.high)),
                    float(px(b.low)),
                    float(px(b.close)),
                ]
                for b in bars[first : last + 1]
            ],
            "zone": [t["zone_o_idx"] - first, float(px(t["zone_bot"])), float(px(t["zone_top"]))],
            "entry": [e - first, float(px(t["entry_signal"]))],
            "code_liq": [t["liq_idx"] - first, float(px(t["liq_level"]))],
            "code_bos": [h2_idx - first if h2_idx is not None else None, real(t, "feat_liq_h2")],
        }
    )

PAGE = r"""<!doctype html><html lang="de"><meta charset="utf-8">
<title>Liquidität markieren</title>
<style>
body{font-family:system-ui,sans-serif;margin:0;background:#fafaf8;color:#222}
header{padding:10px 16px;border-bottom:1px solid #ddd;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
button{padding:6px 12px;border:1px solid #bbb;border-radius:6px;background:#fff;cursor:pointer;font-size:14px}
button.on{background:#2a78d6;color:#fff;border-color:#2a78d6}
#wrap{padding:8px 16px}
canvas{background:#fff;border:1px solid #ddd;border-radius:6px;cursor:crosshair;width:100%;height:560px;display:block}
#step{font-size:15px;margin:8px 0;padding:6px 10px;background:#fff4dd;border-radius:6px;display:inline-block}
#info{font-size:14px;margin:6px 0}
textarea{width:100%;height:60px;font-size:13px}
.muted{color:#777;font-size:13px}
</style>
<header>
  <button id="prev">&larr;</button><b id="title"></b><button id="next">&rarr;</button>
  <span class="muted" id="count"></span>
  <button id="skip">BOS-Kerze überspringen</button>
  <button id="undo">letzte Markierung löschen</button>
  <button id="none">keine Liquidität</button>
  <button id="reveal">Code zeigen</button>
  <button id="dl" style="margin-left:auto">Download</button>
</header>
<div id="wrap">
  <div id="step"></div>
  <div id="info"></div>
  <canvas id="c"></canvas>
  <p class="muted">Eine Liquidität = 3 Klicks: (1) ihr Hoch/Tief, (2) das Level, das für dich gebrochen wird, (3) die Kerze, die es bricht (oder überspringen).
  Klicks rasten auf Hoch oder Tief der Kerze ein, je nachdem was näher liegt. Mehrere Liquiditäten pro Setup möglich (L1, L2, ...).
  Mausrad: zoomen, ziehen: verschieben, Doppelklick: alles zeigen. Violett: Zone, schwarzer Pfeil: Einstieg des Codes. Alles wird im Browser gespeichert; am Ende "Download".</p>
  <textarea id="note" placeholder="Notiz zu diesem Setup (optional), z. B. warum"></textarea>
</div>
<script>
const DATA = __DATA__;
const KEY = "liqpairs_" + __RUN__;
const COLS = ["#c77a00", "#8e44ad", "#16a085", "#c0392b", "#2c3e50", "#d35400"];
let store = {};
try { store = JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (e) {}
const save = () => { try { localStorage.setItem(KEY, JSON.stringify(store)); } catch (e) {} };
let cur = 0, reveal = false, view = null, drag = null;
const cv = document.getElementById("c"), ctx = cv.getContext("2d");
const S = () => DATA[cur];
const rec = () => (store[S().id] ||= {pairs: [], none: false, note: ""});
const open = () => { const p = rec().pairs; const l = p[p.length - 1]; return l && !l.done ? l : null; };

function fit() { view = {a: 0, b: S().bars.length - 1}; }
function layout() {
  const r = cv.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
  cv.width = r.width * dpr; cv.height = r.height * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return {w: r.width, h: r.height, L: 10, R: r.width - 70, T: 10, B: r.height - 40};
}
function scales(g) {
  const bs = S().bars.slice(view.a, view.b + 1);
  let lo = Math.min(...bs.map(b => b[4])), hi = Math.max(...bs.map(b => b[3]));
  const z = S().zone; lo = Math.min(lo, z[1]); hi = Math.max(hi, z[2]);
  const pad = (hi - lo) * 0.05; lo -= pad; hi += pad;
  const n = view.b - view.a + 1, bw = (g.R - g.L) / n;
  return {x: i => g.L + (i - view.a + 0.5) * bw, y: p => g.T + (hi - p) / (hi - lo) * (g.B - g.T),
          p: y => hi - (y - g.T) / (g.B - g.T) * (hi - lo), i: x => Math.floor((x - g.L) / bw) + view.a, bw, lo, hi};
}
function niceStep(x) { const e = Math.pow(10, Math.floor(Math.log10(x))), f = x / e; return (f < 1.5 ? 1 : f < 3.5 ? 2 : f < 7.5 ? 5 : 10) * e; }
function level(s, g, pt, col, txt, dash) {
  const x0 = Math.max(s.x(pt.i) - s.bw / 2, g.L), y = s.y(pt.price);
  ctx.save(); ctx.strokeStyle = col; ctx.lineWidth = 2; ctx.setLineDash(dash);
  ctx.beginPath(); ctx.moveTo(x0, y); ctx.lineTo(g.R, y); ctx.stroke(); ctx.restore();
  ctx.fillStyle = col; ctx.beginPath(); ctx.arc(s.x(pt.i), y, 4.5, 0, 7); ctx.fill();
  ctx.font = "12px system-ui"; ctx.fillText(`${txt} ${pt.price.toFixed(2)}`, x0 + 6, y - 6);
}
function draw() {
  const g = layout(), s = scales(g), d = S(), r = rec();
  ctx.clearRect(0, 0, g.w, g.h);
  ctx.font = "11px system-ui"; ctx.fillStyle = "#777"; ctx.strokeStyle = "#eee";
  const step = niceStep((s.hi - s.lo) / 8);
  for (let p = Math.ceil(s.lo / step) * step; p < s.hi; p += step) {
    const y = s.y(p); ctx.beginPath(); ctx.moveTo(g.L, y); ctx.lineTo(g.R, y); ctx.stroke(); ctx.fillText(p.toFixed(2), g.R + 6, y + 4);
  }
  const every = Math.max(1, Math.round(90 / s.bw));
  for (let i = view.a; i <= view.b; i += every) ctx.fillText(d.bars[i][1], s.x(i) - 28, g.B + 16);
  const z = d.zone; ctx.fillStyle = "rgba(124,108,214,0.18)";
  const zx = Math.max(s.x(z[0]) - s.bw / 2, g.L); ctx.fillRect(zx, s.y(z[2]), g.R - zx, s.y(z[1]) - s.y(z[2]));
  for (let i = view.a; i <= view.b; i++) {
    const [, , o, h, l, c] = d.bars[i], x = s.x(i), up = c >= o;
    ctx.strokeStyle = ctx.fillStyle = up ? "#1d9e75" : "#d85a30";
    ctx.beginPath(); ctx.moveTo(x, s.y(h)); ctx.lineTo(x, s.y(l)); ctx.stroke();
    const bw = Math.max(1, s.bw * 0.7); ctx.fillRect(x - bw / 2, s.y(Math.max(o, c)), bw, Math.max(1, Math.abs(s.y(o) - s.y(c))));
  }
  const [ei, ep] = d.entry; ctx.fillStyle = "#222"; ctx.beginPath();
  ctx.moveTo(s.x(ei) + 4, s.y(ep)); ctx.lineTo(s.x(ei) + 14, s.y(ep) - 6); ctx.lineTo(s.x(ei) + 14, s.y(ep) + 6); ctx.fill();
  r.pairs.forEach((p, k) => {
    const col = COLS[k % COLS.length], n = `L${k + 1}`;
    if (p.liq) level(s, g, p.liq, col, `${n} Liquidität`, [6, 4]);
    if (p.lvl) {
      level(s, g, p.lvl, col, `${n} gebrochenes Level`, [2, 3]);
      ctx.save(); ctx.strokeStyle = col; ctx.setLineDash([3, 3]); ctx.beginPath();
      ctx.moveTo(s.x(p.liq.i), s.y(p.liq.price)); ctx.lineTo(s.x(p.lvl.i), s.y(p.lvl.price)); ctx.stroke(); ctx.restore();
    }
    if (p.bos) {
      const b = d.bars[p.bos.i]; ctx.strokeStyle = col; ctx.lineWidth = 2;
      ctx.strokeRect(s.x(p.bos.i) - s.bw / 2 - 1, s.y(b[3]) - 2, s.bw + 2, s.y(b[4]) - s.y(b[3]) + 4); ctx.lineWidth = 1;
      ctx.fillStyle = col; ctx.fillText(`${n} BOS`, s.x(p.bos.i) - 12, s.y(b[4]) + 14);
    }
  });
  if (reveal) {
    level(s, g, {i: d.code_liq[0], price: d.code_liq[1]}, "#2a78d6", "Code: Liquidität", [1, 0]);
    if (d.code_bos[0] !== null) level(s, g, {i: d.code_bos[0], price: d.code_bos[1]}, "#7a9cc6", "Code: gebrochenes Level", [1, 0]);
  }
  const o = open();
  document.getElementById("step").textContent = r.none ? "Markiert als: keine Liquidität" :
    !o ? `Klick 1: Liquidität L${r.pairs.length + 1} (Hoch/Tief)` : !o.lvl ? `Klick 2: das Level, dessen Bruch L${r.pairs.length} zur Liquidität macht` : `Klick 3: die Kerze, die das Level bricht (oder überspringen)`;
  document.getElementById("title").textContent = `Setup ${d.id}: ${d.side === "long" ? "LONG" : "SHORT"}, Einstieg ${d.entry_berlin} Berlin`;
  document.getElementById("count").textContent = `(${cur + 1} / ${DATA.length}, bearbeitet: ${Object.values(store).filter(v => v.pairs.some(p => p.done) || v.none).length})`;
  document.getElementById("info").textContent = r.pairs.map((p, k) => `L${k + 1}: ${p.liq ? p.liq.price.toFixed(2) + " (" + p.liq.berlin + ")" : ""}` +
    (p.lvl ? ` / Level ${p.lvl.price.toFixed(2)} (${p.lvl.berlin})` : "") + (p.bos ? ` / BOS ${p.bos.berlin}` : p.done ? " / BOS: erste Kerze" : "")).join("   ·   ");
  document.getElementById("note").value = r.note || "";
  document.getElementById("reveal").classList.toggle("on", reveal);
}
cv.addEventListener("mousedown", ev => { drag = {x: ev.offsetX, a: view.a, b: view.b, moved: false}; });
cv.addEventListener("mousemove", ev => {
  if (!drag) return; const g = layout(), s = scales(g);
  if (Math.abs(ev.offsetX - drag.x) > 4) drag.moved = true;
  if (!drag.moved) return; const di = Math.round((drag.x - ev.offsetX) / s.bw), n = S().bars.length, w = drag.b - drag.a;
  const a = Math.min(Math.max(drag.a + di, 0), n - 1 - w); view = {a, b: a + w}; draw();
});
window.addEventListener("mouseup", ev => { if (drag && !drag.moved && ev.target === cv) click(ev.offsetX, ev.offsetY); drag = null; });
cv.addEventListener("wheel", ev => {
  ev.preventDefault(); const g = layout(), s = scales(g), n = S().bars.length, c = s.i(ev.offsetX);
  const w = view.b - view.a, nw = Math.min(n - 1, Math.max(15, Math.round(w * (ev.deltaY > 0 ? 1.2 : 0.8))));
  let a = Math.round(c - (c - view.a) * nw / Math.max(w, 1)); a = Math.min(Math.max(a, 0), n - 1 - nw);
  view = {a, b: a + nw}; draw();
}, {passive: false});
cv.addEventListener("dblclick", () => { fit(); draw(); });
function click(x, y) {
  const g = layout(), s = scales(g), d = S(), r = rec(), i = s.i(x);
  if (i < view.a || i > view.b) return;
  const b = d.bars[i], p = s.p(y), isHigh = Math.abs(p - b[3]) < Math.abs(p - b[4]);
  const pt = {i, ts: b[0], berlin: b[1], price: isHigh ? b[3] : b[4], at: isHigh ? "high" : "low"};
  r.none = false;
  const o = open();
  if (!o) r.pairs.push({liq: pt, lvl: null, bos: null, done: false});
  else if (!o.lvl) o.lvl = pt;
  else { o.bos = {i, ts: b[0], berlin: b[1]}; o.done = true; }
  save(); draw();
}
document.getElementById("skip").onclick = () => { const o = open(); if (o && o.lvl) { o.done = true; save(); draw(); } };
document.getElementById("undo").onclick = () => {
  const r = rec(), o = open();
  if (o) { if (o.lvl) o.lvl = null; else r.pairs.pop(); }
  else if (r.pairs.length) { const l = r.pairs[r.pairs.length - 1]; if (l.bos) { l.bos = null; l.done = false; } else { l.done = false; } }
  save(); draw();
};
document.getElementById("none").onclick = () => { const r = rec(); r.none = !r.none; if (r.none) r.pairs = []; save(); draw(); };
document.getElementById("reveal").onclick = () => { reveal = !reveal; draw(); };
document.getElementById("note").oninput = e => { rec().note = e.target.value; save(); };
const go = k => { cur = (cur + k + DATA.length) % DATA.length; reveal = false; fit(); draw(); };
document.getElementById("prev").onclick = () => go(-1);
document.getElementById("next").onclick = () => go(1);
document.addEventListener("keydown", e => { if (e.target.tagName === "TEXTAREA") return; if (e.key === "ArrowRight") go(1); if (e.key === "ArrowLeft") go(-1); });
document.getElementById("dl").onclick = () => {
  const out = DATA.map(d => ({id: d.id, side: d.side, entry_utc: d.entry_utc, first: d.first, ...(store[d.id] || {pairs: [], none: false, note: ""})}));
  const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([JSON.stringify({run: __RUN__, setups: out}, null, 1)], {type: "application/json"}));
  a.download = "liq_marks.json"; a.click();
};
window.addEventListener("resize", draw);
fit(); draw();
</script></html>"""

out = args.run / f"{args.name}.html"
out.write_text(
    PAGE.replace("__DATA__", json.dumps(setups)).replace("__RUN__", json.dumps(args.run.name)),
    encoding="utf-8",
)
print(out, len(setups), "setups")
