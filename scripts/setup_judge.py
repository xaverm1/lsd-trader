# ruff: noqa: E501
"""Judgement page: would Xaver have taken this setup? Blind (charts end at the entry).

Usage: python scripts/setup_judge.py RUN_FOLDER [--n N] [--seed S] [--since YYYY-MM-DD]
       [--until YYYY-MM-DD] [--name OUT]

Writes RUN_FOLDER/OUT.html: per setup the strategy bars up to the entry bar with the zone, the
code's liquidity, the high/low its break broke, sweep, tap, entry and stop. Buttons "genommen" /
"nicht genommen", reason tags and a note. Kept in the browser (localStorage), exported with
"Download" as setup_judgements.json. Contains price data: never commit the output.
"""

import argparse
import json
import random
from pathlib import Path
from zoneinfo import ZoneInfo

from lsdtrader.review.review import load_run

BERLIN = ZoneInfo("Europe/Berlin")
BEFORE = 40
MAX_BARS = 400

ap = argparse.ArgumentParser()
ap.add_argument("run", type=Path)
ap.add_argument("--n", type=int, default=40)
ap.add_argument("--seed", type=int, default=3)
ap.add_argument("--since", default="2000-01-01")
ap.add_argument("--until", default="2100-01-01")
ap.add_argument("--name", default="setup_judge")
args = ap.parse_args()

run = load_run(args.run)
inst, bars = run.data.instrument, run.data.bars
px = inst.to_price
trades, seen = [], set()
for t in sorted(run.trades, key=lambda t: t["entry_ts"]):
    day = t["entry_ts"].date().isoformat()
    if (t["entry_ts"], t["side"]) not in seen and args.since <= day <= args.until:
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


def bar_rows(a: int, b: int) -> list[list]:
    return [
        [
            x.ts.isoformat(),
            x.ts.astimezone(BERLIN).strftime("%d.%m %H:%M"),
            float(px(x.open)),
            float(px(x.high)),
            float(px(x.low)),
            float(px(x.close)),
        ]
        for x in bars[a : b + 1]
    ]


setups = []
for k, t in enumerate(picked, 1):
    e = t["entry_bar"]
    h2 = t.get("feat_liq_h2_idx")
    anchors = [t["zone_o_idx"], t["liq_idx"]] + ([h2] if h2 is not None else [])
    first = max(min(anchors) - BEFORE, e - MAX_BARS, 0)
    setups.append(
        {
            "id": k,
            "side": t["side"],
            "entry_utc": t["entry_ts"].isoformat(),
            "title": f"Setup {k}: {inst.root} {'LONG' if t['side'] == 'long' else 'SHORT'}, Einstieg {t['entry_ts'].astimezone(BERLIN):%d.%m.%Y %H:%M} Berlin",
            "bars": bar_rows(first, e),
            "zone": [t["zone_o_idx"] - first, float(px(t["zone_bot"])), float(px(t["zone_top"]))],
            "liq": [t["liq_idx"] - first, float(px(t["liq_level"]))],
            "brk": [h2 - first if h2 is not None and h2 >= first else None, real(t, "feat_liq_h2")],
            "sweep": t["sweep_idx"] - first,
            "tap": t["tap_idx"] - first,
            "entry": [e - first, float(px(t["entry_signal"])), float(px(t["stop"]))],
        }
    )

REASONS = [
    "Liquidität falsch/fehlt",
    "Liquidität zu weit weg",
    "Zone schlecht",
    "gegen den Trend",
    "Level zu klein",
    "zu spät / zu lange her",
    "Stop zu eng/zu weit",
    "unruhig / hässlich",
    "Sonstiges",
]

PAGE = r"""<!doctype html><html lang="de"><meta charset="utf-8">
<title>Setups beurteilen</title>
<style>
body{font-family:system-ui,sans-serif;margin:0;background:#fafaf8;color:#222}
header{padding:10px 16px;border-bottom:1px solid #ddd;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
button{padding:6px 12px;border:1px solid #bbb;border-radius:6px;background:#fff;cursor:pointer;font-size:14px}
button.yes.on{background:#1d9e75;color:#fff;border-color:#1d9e75}
button.no.on{background:#d9534f;color:#fff;border-color:#d9534f}
button.tag.on{background:#555;color:#fff;border-color:#555}
#wrap{padding:8px 16px}
canvas{background:#fff;border:1px solid #ddd;border-radius:6px;width:100%;height:560px;display:block;cursor:grab}
#tags{display:flex;gap:6px;flex-wrap:wrap;margin:8px 0}
textarea{width:100%;height:50px;font-size:13px}
.muted{color:#777;font-size:13px}
</style>
<header>
  <button id="prev">&larr;</button><b id="title"></b><button id="next">&rarr;</button>
  <span class="muted" id="count"></span>
  <button id="yes" class="yes">genommen (J)</button>
  <button id="no" class="no">nicht genommen (N)</button>
  <button id="dl" style="margin-left:auto">Download</button>
</header>
<div id="wrap">
  <canvas id="c"></canvas>
  <div class="muted" style="margin-top:6px">Bei "nicht genommen": Gründe anklicken (mehrere möglich), gern auch bei "genommen", wenn etwas stört.</div>
  <div id="tags"></div>
  <textarea id="note" placeholder="Notiz (optional)"></textarea>
  <p class="muted">Violett: Zone. Orange gepunktet: Liquidität des Codes, grau gestrichelt: das Level, dessen Bruch sie gemacht hat. Dreieck: Sweep, Raute: Tap, Pfeil: Einstieg, rot: Stop.
  Mausrad zoomt, ziehen verschiebt, Doppelklick zeigt alles, Pfeiltasten wechseln, J/N beurteilen. Alles wird im Browser gespeichert; am Ende "Download".</p>
</div>
<script>
const DATA = __DATA__, REASONS = __REASONS__, KEY = "judge_" + __RUN__;
let store = {}; try { store = JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (e) {}
const save = () => { try { localStorage.setItem(KEY, JSON.stringify(store)); } catch (e) {} };
let cur = 0, view = null, drag = null;
const cv = document.getElementById("c"), ctx = cv.getContext("2d"), S = () => DATA[cur];
const rec = () => (store[S().id] ||= {take: null, reasons: [], note: ""});
function fit() { const n = S().bars.length; view = {a: Math.max(0, n - 160), b: n - 1}; }
function layout() { const r = cv.getBoundingClientRect(), d = window.devicePixelRatio || 1; cv.width = r.width * d; cv.height = r.height * d; ctx.setTransform(d, 0, 0, d, 0, 0); return {w: r.width, h: r.height, L: 10, R: r.width - 70, T: 12, B: r.height - 40}; }
function scales(g) {
  const d = S(), bs = d.bars.slice(view.a, view.b + 1);
  let lo = Math.min(...bs.map(b => b[4]), d.entry[2]), hi = Math.max(...bs.map(b => b[3]), d.entry[2]);
  const pad = (hi - lo) * 0.06; lo -= pad; hi += pad; const bw = (g.R - g.L) / (view.b - view.a + 1);
  return {x: i => g.L + (i - view.a + 0.5) * bw, y: p => g.T + (hi - p) / (hi - lo) * (g.B - g.T), i: x => Math.floor((x - g.L) / bw) + view.a, bw, lo, hi};
}
function nice(x) { const e = Math.pow(10, Math.floor(Math.log10(x))), f = x / e; return (f < 1.5 ? 1 : f < 3.5 ? 2 : f < 7.5 ? 5 : 10) * e; }
function hline(s, g, i0, p, col, dash, txt) {
  if (p === null || p === undefined) return; const x0 = Math.max(i0 === null ? g.L : s.x(i0) - s.bw / 2, g.L), y = s.y(p);
  ctx.save(); ctx.strokeStyle = col; ctx.lineWidth = 1.8; ctx.setLineDash(dash); ctx.beginPath(); ctx.moveTo(x0, y); ctx.lineTo(g.R, y); ctx.stroke(); ctx.restore();
  ctx.fillStyle = col; ctx.font = "12px system-ui"; ctx.fillText(txt, x0 + 4, y - 5);
}
function draw() {
  const g = layout(), s = scales(g), d = S(), r = rec();
  ctx.clearRect(0, 0, g.w, g.h); ctx.font = "11px system-ui"; ctx.fillStyle = "#777"; ctx.strokeStyle = "#eee";
  const st = nice((s.hi - s.lo) / 8);
  for (let p = Math.ceil(s.lo / st) * st; p < s.hi; p += st) { const y = s.y(p); ctx.beginPath(); ctx.moveTo(g.L, y); ctx.lineTo(g.R, y); ctx.stroke(); ctx.fillText(p.toFixed(2), g.R + 6, y + 4); }
  const ev = Math.max(1, Math.round(90 / s.bw)); for (let i = view.a; i <= view.b; i += ev) ctx.fillText(d.bars[i][1], s.x(i) - 28, g.B + 16);
  const z = d.zone; ctx.fillStyle = "rgba(124,108,214,0.18)"; const zx = Math.max(s.x(z[0]) - s.bw / 2, g.L); ctx.fillRect(zx, s.y(z[2]), g.R - zx, s.y(z[1]) - s.y(z[2]));
  for (let i = view.a; i <= view.b; i++) { const [, , o, h, l, c] = d.bars[i], x = s.x(i); ctx.strokeStyle = ctx.fillStyle = c >= o ? "#1d9e75" : "#d85a30";
    ctx.beginPath(); ctx.moveTo(x, s.y(h)); ctx.lineTo(x, s.y(l)); ctx.stroke(); const w = Math.max(1, s.bw * 0.7); ctx.fillRect(x - w / 2, s.y(Math.max(o, c)), w, Math.max(1, Math.abs(s.y(o) - s.y(c)))); }
  hline(s, g, d.brk[0], d.brk[1], "#666", [5, 4], "gebrochenes Level");
  hline(s, g, d.liq[0], d.liq[1], "#c77a00", [2, 3], "Liquidität");
  const [ei, ep, sp] = d.entry; hline(s, g, ei, sp, "#d9534f", [1, 0], "Stop");
  const mk = (i, y, col, f) => { if (i < view.a || i > view.b) return; ctx.fillStyle = col; ctx.beginPath(); f(s.x(i), y); ctx.fill(); };
  const up = d.side === "long";
  const sb = d.bars[d.sweep]; mk(d.sweep, s.y(up ? sb[4] : sb[3]) + (up ? 12 : -12), "#c77a00", (x, y) => { ctx.moveTo(x, y - (up ? 7 : -7)); ctx.lineTo(x - 6, y + (up ? 5 : -5)); ctx.lineTo(x + 6, y + (up ? 5 : -5)); });
  mk(d.tap, s.y(up ? z[2] : z[1]), "#4b3fb0", (x, y) => { ctx.moveTo(x, y - 6); ctx.lineTo(x + 6, y); ctx.lineTo(x, y + 6); ctx.lineTo(x - 6, y); });
  mk(ei, s.y(ep), "#222", (x, y) => { ctx.moveTo(x + 4, y); ctx.lineTo(x + 14, y - 6); ctx.lineTo(x + 14, y + 6); });
  document.getElementById("title").textContent = d.title;
  document.getElementById("count").textContent = `(${cur + 1} / ${DATA.length}, beurteilt: ${Object.values(store).filter(v => v.take !== null).length})`;
  document.getElementById("yes").classList.toggle("on", r.take === true); document.getElementById("no").classList.toggle("on", r.take === false);
  document.querySelectorAll("#tags button").forEach(b => b.classList.toggle("on", r.reasons.includes(b.textContent)));
  document.getElementById("note").value = r.note || "";
}
const tags = document.getElementById("tags");
REASONS.forEach(t => { const b = document.createElement("button"); b.className = "tag"; b.textContent = t;
  b.onclick = () => { const r = rec(); r.reasons = r.reasons.includes(t) ? r.reasons.filter(x => x !== t) : [...r.reasons, t]; save(); draw(); }; tags.appendChild(b); });
const judge = v => { const r = rec(); r.take = r.take === v ? null : v; save(); draw(); };
document.getElementById("yes").onclick = () => judge(true); document.getElementById("no").onclick = () => judge(false);
document.getElementById("note").oninput = e => { rec().note = e.target.value; save(); };
const go = k => { cur = (cur + k + DATA.length) % DATA.length; fit(); draw(); };
document.getElementById("prev").onclick = () => go(-1); document.getElementById("next").onclick = () => go(1);
document.addEventListener("keydown", e => { if (e.target.tagName === "TEXTAREA") return;
  if (e.key === "ArrowRight") go(1); if (e.key === "ArrowLeft") go(-1); if (e.key === "j" || e.key === "J") judge(true); if (e.key === "n" || e.key === "N") judge(false); });
cv.addEventListener("mousedown", ev => { drag = {x: ev.offsetX, a: view.a, b: view.b}; });
window.addEventListener("mouseup", () => { drag = null; });
cv.addEventListener("mousemove", ev => { if (!drag) return; const s = scales(layout()), n = S().bars.length, w = drag.b - drag.a;
  const a = Math.min(Math.max(drag.a + Math.round((drag.x - ev.offsetX) / s.bw), 0), n - 1 - w); view = {a, b: a + w}; draw(); });
cv.addEventListener("wheel", ev => { ev.preventDefault(); const s = scales(layout()), n = S().bars.length, c = s.i(ev.offsetX), w = view.b - view.a;
  const nw = Math.min(n - 1, Math.max(15, Math.round(w * (ev.deltaY > 0 ? 1.2 : 0.8)))); let a = Math.round(c - (c - view.a) * nw / Math.max(w, 1));
  a = Math.min(Math.max(a, 0), n - 1 - nw); view = {a, b: a + nw}; draw(); }, {passive: false});
cv.addEventListener("dblclick", () => { view = {a: 0, b: S().bars.length - 1}; draw(); });
document.getElementById("dl").onclick = () => { const out = DATA.map(d => ({id: d.id, side: d.side, entry_utc: d.entry_utc, ...(store[d.id] || {take: null, reasons: [], note: ""})}));
  const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([JSON.stringify({run: __RUN__, setups: out}, null, 1)], {type: "application/json"})); a.download = "setup_judgements.json"; a.click(); };
window.addEventListener("resize", draw); fit(); draw();
</script></html>"""

out = args.run / f"{args.name}.html"
out.write_text(
    PAGE.replace("__DATA__", json.dumps(setups))
    .replace("__REASONS__", json.dumps(REASONS, ensure_ascii=False))
    .replace("__RUN__", json.dumps(args.run.name)),
    encoding="utf-8",
)
print(out, len(setups), "setups")
