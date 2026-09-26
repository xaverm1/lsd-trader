# ruff: noqa: E501
"""Rule walkthrough: small bar scenarios run through the real engine, drawn step by step.

Usage: python scripts/rules_explainer.py OUT.html

Every marker in the pictures (swings, BOS, zone, liquidity, sweep, tap, absorption, entry,
stop) comes from the engine's own objects and events, not from the drawing code, so the
page shows what the code does. Long side; the short side runs the same code on mirrored bars.
Prices are plain numbers (ticks).
"""

import base64
import io
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

from lsdtrader.backtest.runner import run_backtest  # noqa: E402
from lsdtrader.core.bar import TickBar  # noqa: E402
from lsdtrader.core.config import StrategyConfig  # noqa: E402
from lsdtrader.core.events import EventLog  # noqa: E402
from lsdtrader.core.instrument import Instrument  # noqa: E402
from lsdtrader.strategy.lsd import SideEngine  # noqa: E402
from lsdtrader.strategy.structure import Bos, strong_level  # noqa: E402
from lsdtrader.strategy.zones import ZoneBook  # noqa: E402

T0 = datetime(2026, 1, 5, 11, 0, tzinfo=UTC)  # bar 15 at 12:30 Chicago, inside the session
INST = Instrument("DEMO", Decimal("1"), tick_value=1.0, commission_per_side=0.0)
UP, DOWN = "#1D9E75", "#D85A30"
ZONE, LIQ, GREY, RED, INK = "#534AB7", "#BA7517", "#888780", "#E24B4A", "#2C2C2A"


def bars30(*ohlc: tuple[int, int, int, int]) -> list[TickBar]:
    return [TickBar(T0 + timedelta(minutes=30 * i), *x) for i, x in enumerate(ohlc)]


# The basic long story (30-minute bars), same as the test fixture FULL_LONG.
STORY = [
    (110, 112, 104, 105),  # 0
    (105, 106, 100, 101),  # 1  L0
    (101, 108, 101, 107),  # 2
    (107, 115, 106, 114),  # 3
    (114, 118, 113, 117),  # 4  H2
    (117, 117, 110, 111),  # 5
    (111, 112, 106, 107),  # 6  P, bearish -> zone origin
    (107, 110, 107, 109),  # 7  F
    (109, 116, 108, 115),  # 8
    (115, 121, 114, 120),  # 9  BOS, zone left
    (120, 122, 116, 117),  # 10 H2'
    (117, 118, 113, 114),  # 11 P' = liquidity
    (114, 119, 114, 118),  # 12
    (118, 124, 117, 123),  # 13 BOS of P'
    (123, 123, 115, 116),  # 14
]


def candles(ax, bars, first=0, labels=True):  # type: ignore[no-untyped-def]
    for i, b in enumerate(bars):
        c = UP if b.close >= b.open else DOWN
        ax.vlines(i, b.low, b.high, color=c, lw=1.3, zorder=2)
        ax.add_patch(
            Rectangle(
                (i - 0.33, min(b.open, b.close)),
                0.66,
                max(abs(b.close - b.open), 0.15),
                color=c,
                zorder=2,
            )
        )
    if labels:
        ax.set_xticks(range(len(bars)))
        ax.set_xticklabels([str(first + i) for i in range(len(bars))], fontsize=8)
    ax.grid(alpha=0.2)


def png(fig) -> str:  # type: ignore[no-untyped-def]
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100, bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def run_engine(bars: list[TickBar], cfg: StrategyConfig) -> SideEngine:
    eng = SideEngine(cfg)
    for b in bars:
        eng.on_bar(b)
    return eng


sections: list[tuple[str, str, str, str]] = []  # title, text, image, code says

# ---------------------------------------------------------------- 1 swing and BOS
bars = bars30(*STORY)
eng = run_engine(bars, StrategyConfig())
events = eng.log.drain()
bos_ev = [e for e in events if e.kind == "bos"]
fig, ax = plt.subplots(figsize=(12, 5))
candles(ax, bars)
from lsdtrader.strategy.swings import is_swing_low  # noqa: E402

for i in range(len(bars)):
    if is_swing_low(bars, i, 1):
        ax.plot(i, bars[i].low - 0.6, "^", color=GREY, ms=7)
colors = ["#534AB7", "#BA7517"]
for k, e in enumerate(bos_ev):
    d, c = e.detail, colors[k % 2]
    p, h2, b = d["p_idx"], d["h2"], d["bos_idx"]
    h2_idx = max(j for j in range(0, p + 1) if bars[j].high == h2)
    ax.hlines(h2, h2_idx, b, colors=c, linestyles="--", lw=1.4)
    ax.text(h2_idx, h2 + 0.3, f"H2 = {h2}", color=c, fontsize=9)
    ax.plot(p, bars[p].low - 0.6, "^", color=c, ms=10)
    ax.text(p + 0.15, bars[p].low - 1.8, f"P (Swing-Tief {bars[p].low})", color=c, fontsize=9)
    ax.plot(b, bars[b].close, ">", color=c, ms=10)
    ax.text(
        b + 0.2,
        bars[b].close,
        f"BOS: Close {bars[b].close} > {h2}",
        color=c,
        fontsize=9,
        va="center",
    )
ax.set_title("Swing-Tiefs (graue Dreiecke) und BOS, wie der Code sie findet")
code = "; ".join(
    f"BOS von P = Kerze {e.detail['p_idx']} über H2 {e.detail['h2']} auf Kerze {e.detail['bos_idx']}"
    for e in bos_ev
)
sections.append(
    (
        "1. Swing-Tief und BOS",
        "Swing-Tief: eine Kerze, deren Nachbarn links und rechts nicht tiefer sind (1 Kerze je Seite). "
        "Zu jedem neuen Swing-Tief P sucht der Code L0, das letzte Swing-Tief darunter, und H2, das höchste Hoch "
        "zwischen L0 und P. Der BOS ist die erste 30-min-Kerze, die <b>über H2 schließt</b>.",
        png(fig),
        code,
    )
)

# ---------------------------------------------------------------- 2 zone
zones = eng.zones.history
z = zones[0]
fig, axes = plt.subplots(1, 2, figsize=(14, 5))
candles(axes[0], bars)
axes[0].add_patch(
    Rectangle((z.o_idx - 0.5, z.bot), len(bars) - z.o_idx, z.top - z.bot, color=ZONE, alpha=0.15)
)
axes[0].text(z.o_idx - 0.4, z.top + 0.3, f"Zone {z.bot}-{z.top} ({z.kind})", color=ZONE, fontsize=9)
axes[0].annotate(
    "Ursprung: letzte bärische\nKerze bis P zurück",
    (z.o_idx, bars[z.o_idx].high),
    (z.o_idx - 5, 121),
    arrowprops=dict(arrowstyle="->", color=ZONE),
    color=ZONE,
    fontsize=9,
)
left_ev = [e for e in events if e.kind == "zone_left" and e.detail.get("zone_id") == z.zone_id]
if left_ev:
    li = left_ev[0].bar_index
    axes[0].annotate(
        "verlassen: Kerze komplett\nüber der Zone",
        (li, bars[li].low),
        (li + 0.5, 104),
        arrowprops=dict(arrowstyle="->", color=INK),
        fontsize=9,
    )
axes[0].set_title("Accuracy-Zone: Folgekerze F geht nicht höher\n→ Körperoberkante bis Tief")
# normal variant: F goes higher than the origin
normal = list(STORY)
normal[7] = (107, 113, 107, 112)
nb = bars30(*normal)
ne = run_engine(nb, StrategyConfig())
zn = ne.zones.history[0]
candles(axes[1], nb)
axes[1].add_patch(
    Rectangle((zn.o_idx - 0.5, zn.bot), len(nb) - zn.o_idx, zn.top - zn.bot, color=ZONE, alpha=0.15)
)
axes[1].text(
    zn.o_idx - 0.4, zn.top + 0.3, f"Zone {zn.bot}-{zn.top} ({zn.kind})", color=ZONE, fontsize=9
)
axes[1].set_title(
    "Normale Zone: Folgekerze F geht höher (Hoch 113 > 112)\n→ ganze Kerze, Hoch bis Tief"
)
sections.append(
    (
        "2. Zone",
        "Die Zone entsteht mit dem BOS. Ursprung ist die letzte bärische (oder Doji-) Kerze von P aus rückwärts. "
        "Geht die Folgekerze höher als der Ursprung, ist die Zone die ganze Kerze (normal), sonst Körperoberkante bis Tief "
        "(accuracy). Solange die Zone noch nicht verlassen ist, verschiebt eine bärische Kerze, die sie berührt, die Zone "
        "auf sich. Verlassen ist sie, wenn eine Kerze komplett darüber liegt.",
        png(fig),
        f"links: Zone {z.bot}-{z.top} {z.kind}, Ursprung Kerze {z.o_idx}; rechts: Zone {zn.bot}-{zn.top} {zn.kind}",
    )
)

# ---------------------------------------------------------------- 3 invalidation (30 min)
cases = [
    ("Docht in die Zone, Close darüber", (124, 124, 108, 114)),
    ("Close IN der Zone", (124, 124, 108, 110)),
    ("Docht UNTER die Zone, Close darüber", (124, 124, 104, 114)),
    ("Close UNTER der Zone", (124, 124, 100, 103)),
]
fig, axes = plt.subplots(1, 4, figsize=(18, 4.8), sharey=True)
code_parts = []
for ax, (name, x) in zip(axes, cases, strict=True):
    bb = bars30(*STORY[:14], x)
    log = EventLog()
    book = ZoneBook(StrategyConfig(), log)
    zs = book.create(bb[:10], Bos(p_idx=6, p_low=106, l0_idx=1, h2=118, bos_idx=9, known_idx=9))
    for k in range(10, len(bb)):
        book.update(bb[: k + 1])
    zz = zs[0]
    candles(ax, bb[5:], first=5)
    ax.add_patch(
        Rectangle(
            (zz.o_idx - 5 - 0.5, zz.bot),
            len(bb) - zz.o_idx,
            zz.top - zz.bot,
            color=ZONE,
            alpha=0.15,
        )
    )
    alive = zz.live
    ax.set_title(
        f"{name}\n→ Zone {'lebt' if alive else 'TOT'}", color=UP if alive else RED, fontsize=11
    )
    code_parts.append(f"{name}: Zustand {zz.state}")
sections.append(
    (
        "3. Invalidierung der Zone (30 min)",
        "Nach dem Verlassen ist die Zone tot, sobald eine 30-min-Kerze <b>in der Zone schließt</b> (Close ≤ Oberkante) "
        "oder ein <b>Docht unter die Unterkante</b> geht. Ein Docht in die Zone mit Close darüber ist ein Tap und lässt sie leben.",
        png(fig),
        "; ".join(code_parts),
    )
)

# ---------------------------------------------------------------- 4 nearest liquidity
more = STORY[:14] + [
    (123, 125, 121, 124),  # 14
    (124, 126, 119, 120),  # 15 swing low 119
    (120, 124, 120, 123),  # 16
    (123, 129, 122, 128),  # 17 BOS of 119 (close 128 > 126)
    (128, 128, 117, 118),  # 18 sweeps 119 only
    (118, 119, 112, 113),  # 19 sweeps 113
]
mb = bars30(*more)
cfg = StrategyConfig(liq_rule="nearest")
me = run_engine(mb, cfg)
ev = me.log.drain()
fig, ax = plt.subplots(figsize=(13, 5.5))
candles(ax, mb)
zz = me.zones.history[0]
ax.add_patch(
    Rectangle((zz.o_idx - 0.5, zz.bot), len(mb) - zz.o_idx, zz.top - zz.bot, color=ZONE, alpha=0.15)
)
ax.text(zz.o_idx - 0.4, zz.bot - 1.2, "Zone", color=ZONE, fontsize=9)
lines = []
for e in ev:
    if e.kind == "setup_started":
        p = e.detail["liq_price"]
        ax.hlines(p, e.detail["liq_idx"], e.bar_index, colors=UP, linestyles=":", lw=2)
        ax.text(
            e.detail["liq_idx"],
            p + 0.3,
            f"Liquidität {p}: gilt (am nächsten an der Zone)",
            color=UP,
            fontsize=9,
        )
        ax.plot(e.bar_index, mb[e.bar_index].low, "^", color=UP, ms=10)
        lines.append(f"Kerze {e.bar_index}: Sweep von {p} startet Setup")
    if e.kind == "sweep_no_setup":
        li = e.detail["liq_idx"]
        p = mb[li].low
        ax.hlines(p, li, e.bar_index, colors=RED, linestyles=":", lw=2)
        ax.text(
            li - 6,
            p + 0.3,
            f"Liquidität {p}: gilt nicht ({e.detail['reason']})",
            color=RED,
            fontsize=9,
        )
        ax.plot(e.bar_index, mb[e.bar_index].low, "^", color=RED, ms=10)
        lines.append(f"Kerze {e.bar_index}: Sweep von {p} → kein Setup, Grund {e.detail['reason']}")
ax.set_title("Nur die Liquidität, die der Zone am nächsten liegt, zählt (liq_rule=nearest)")
sections.append(
    (
        "4. Liquidität: nur die nächste",
        "Liquidität ist das Swing-Tief P eines BOS, das über einer verlassenen Zone liegt und nach dem Zonenursprung entstanden ist. "
        "Mit der Regel „nearest“ zählt nur das offene Swing-Tief, das der Zone am nächsten liegt. Hier wird zuerst 119 gesweept: "
        "zwischen 119 und der Zone liegt noch das offene Tief 113, also ist 119 zu weit weg. Danach wird 113 gesweept: das ist die nächste, "
        "also startet das Setup.",
        png(fig),
        "; ".join(lines) or "keine Ereignisse",
    )
)

# ---------------------------------------------------------------- 5 strong BOS level
eng5 = run_engine(bars, StrategyConfig())
b5 = [e for e in eng5.log.drain() if e.kind == "bos"][1].detail  # BOS of the liquidity P' (bar 11)
bos5 = Bos(
    p_idx=b5["p_idx"],
    p_low=bars[b5["p_idx"]].low,
    l0_idx=b5["l0_idx"],
    h2=b5["h2"],
    bos_idx=b5["bos_idx"],
    known_idx=b5["bos_idx"],
)
fig, axes = plt.subplots(1, 2, figsize=(15, 5), sharey=True)
code5 = []
for ax, n in zip(axes, (2, 3), strict=True):
    candles(ax, bars)
    h2i = max(j for j in range(bos5.l0_idx + 1, bos5.p_idx + 1) if bars[j].high == bos5.h2)
    ok = strong_level(bars, bos5, n)
    ax.axvspan(h2i - n - 0.5, h2i + n + 0.5, color=UP if ok else RED, alpha=0.08)
    ax.hlines(bos5.h2, h2i, bos5.bos_idx, colors=INK, linestyles="--")
    ax.text(
        h2i - n - 0.4,
        bos5.h2 + 0.4,
        f"H2 {bos5.h2}: {n} Kerzen links und rechts niedriger?",
        fontsize=9,
    )
    ax.plot(bos5.p_idx, bars[bos5.p_idx].low - 0.6, "^", color=LIQ, ms=10)
    ax.text(bos5.p_idx + 0.2, bars[bos5.p_idx].low - 1.6, "Liquidität P'", color=LIQ, fontsize=9)
    ax.plot(bos5.bos_idx, bars[bos5.bos_idx].close, ">", color=INK, ms=9)
    ax.text(bos5.bos_idx + 0.2, bars[bos5.bos_idx].close + 0.5, "BOS", fontsize=9)
    ax.set_title(
        f"N = {n}: {'starkes Level → Liquidität gilt' if ok else 'rechts nur 2 Kerzen vor dem BOS → gilt nicht'}",
        color=UP if ok else RED,
    )
    code5.append(f"strong_level(N={n}) = {ok}")
sections.append(
    (
        "5. Starker BOS: das gebrochene Level muss ein echter Swing sein",
        "Das Level H2, das der BOS der Liquidität bricht, muss selbst ein Swing-Hoch sein: N Kerzen links und rechts niedriger, "
        "und die rechten Kerzen müssen alle <b>vor</b> der BOS-Kerze liegen (liq_bos_pivot=N). Dasselbe Beispiel: mit N = 2 gilt die "
        "Liquidität, mit N = 3 nicht, weil zwischen H2 und dem BOS nur 2 Kerzen liegen. Zonen werden dadurch nicht gefiltert.",
        png(fig),
        "; ".join(code5),
    )
)

# ---------------------------------------------------------------- 6 minute sequence
full = bars30(*STORY, (116, 117, 107, 113))
t = full[15].ts
mins = [
    TickBar(t, 115, 117, 114, 116, 10),
    TickBar(t + timedelta(minutes=1), 116, 116, 112, 112, 10),  # sweep of 113
    TickBar(t + timedelta(minutes=2), 112, 112, 107, 109, 10),  # tap, deepest wick 107
    TickBar(t + timedelta(minutes=3), 111, 112, 108, 111, 100),  # absorption
    TickBar(t + timedelta(minutes=4), 111, 114, 111, 113, 10),  # close above 112 -> entry
]
full[15] = TickBar(t, 115, 117, 107, 113, 140)
cfg6 = StrategyConfig(entry_mode="absorption_1m")
res = run_backtest(INST, full, {t: mins}, cfg6)
tr = [x for x in res.trades if x.side == "long"][0]
f = tr.features
fig, ax = plt.subplots(figsize=(12, 5.5))
candles(ax, mins, labels=False)
ax.set_xticks(range(len(mins)))
ax.set_xticklabels([f"Min {i}" for i in range(len(mins))])
ax.axhspan(106, 111, color=ZONE, alpha=0.12)
ax.text(-0.45, 110.4, "Zone 106-111", color=ZONE, fontsize=9)
ax.hlines(113, -0.5, 4.5, colors=LIQ, linestyles=":")
ax.text(-0.45, 113.2, "Liquidität P' 113", color=LIQ, fontsize=9)
ax.plot(1, 112, "^", color=LIQ, ms=11)
ax.text(0.45, 111.3, "Sweep (unter 113)", color=LIQ, fontsize=9)
ax.plot(2, 111, "D", color=ZONE, ms=9)
ax.text(2.1, 110.5, "Tap (Zonenoberkante)", color=ZONE, fontsize=9)
ax.plot(3, 109.5, "o", color=LIQ, ms=14, alpha=0.6)
ax.text(
    3.15,
    108.3,
    f"Absorption: Volumen-Score {f['abs_score']:.1f} ≥ 1,3\nund langer unterer Docht",
    fontsize=9,
)
ax.hlines(f["abs_high"], 3, 4.4, colors=INK, linestyles="--")
ax.text(3.0, f["abs_high"] + 0.25, f"Hoch der Absorption {f['abs_high']}", fontsize=9)
ax.plot(4, tr.entry_signal, ">", color=INK, ms=11)
ax.text(4.1, tr.entry_signal + 0.3, f"Entry: Close {tr.entry_signal} > {f['abs_high']}", fontsize=9)
ax.hlines(tr.stop, 2, 4.5, colors=RED, linestyles="--")
ax.text(
    2.05, tr.stop - 0.7, f"Stop {tr.stop} = tiefster Docht seit dem Sweep", color=RED, fontsize=9
)
ax.set_ylim(104, 118)
ax.set_title(f"1-min-Ablauf innerhalb einer 30-min-Kerze (Ziel 4R = {tr.target})")
late = run_backtest(INST, full, {t: mins}, replace(cfg6, max_min_sweep_to_tap=0))
wick = list(mins)
wick[2] = TickBar(wick[2].ts, 112, 112, 105, 109, 10)
full_w = list(full)
full_w[15] = TickBar(t, 115, 117, 105, 113, 140)
dead = run_backtest(INST, full_w, {t: wick}, cfg6)
code6 = (
    f"Trade: Entry {tr.entry_signal} um {tr.entry_ts:%H:%M}, Stop {tr.stop}, Ziel {tr.target}, Sweep→Tap {f['min_sweep_to_tap']:.0f} min; "
    f"mit Fenster Sweep→Tap 0 min: {len(late.trades)} Trades; mit Docht auf 105 (unter der Zone): {len(dead.trades)} Trades"
)
sections.append(
    (
        "6. Ablauf auf 1 min: Sweep, Tap, Absorption, Einstieg, Stop",
        "Alles ab dem Sweep prüft der Code Minute für Minute. <b>Sweep</b>: eine Minute unter der Liquidität. <b>Tap</b>: eine Minute an "
        "der Zonenoberkante, höchstens X Minuten nach dem Sweep (max_min_sweep_to_tap). <b>Absorption</b>: Volumen / Standardabweichung "
        "der letzten 100 Minuten ≥ 1,3 und langer unterer Docht; ein neues tieferes Tief entwertet sie. <b>Einstieg</b>: Close über dem "
        "Hoch der Absorptionsminute, innerhalb von 15 Minuten. <b>Stop</b>: tiefster Docht seit dem Sweep. <b>Ziel</b>: 4 R. "
        "Geht in irgendeiner Minute ein Docht unter die Zone, ist sie sofort tot (Kontrolle unten: dann 0 Trades).",
        png(fig),
        code6,
    )
)

out = Path(sys.argv[1])
parts = [
    "<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>",
    "<title>LSD-Regeln</title><body style='font-family:system-ui,sans-serif;max-width:1300px;margin:auto;padding:0 16px;background:#fff;color:#222'>",
    "<h1>LSD-Strategie: jede Regel am Beispiel</h1>",
    "<p>Die Kursbeispiele laufen durch den echten Strategie-Code. Was markiert ist (Swings, BOS, Zone, Liquidität, Sweep, Tap, "
    "Absorption, Einstieg, Stop), hat der Code selbst erkannt. Die Zeile „Code sagt“ ist die Ausgabe des Codes. Long-Seite; "
    "Short ist derselbe Code auf gespiegelten Kerzen. Zahlen unter den Kerzen = Kerzennummer (30 min).</p>",
]
for title, text, img, says in sections:
    parts.append(
        f"<h2>{title}</h2><p>{text}</p><img style='width:100%' src='data:image/png;base64,{img}'>"
        f"<p style='font-family:monospace;background:#f4f4f2;padding:8px'>Code sagt: {says}</p>"
    )
parts.append(
    "<h2>7. Trade-Management und Kosten</h2><ul>"
    "<li>Ziel 4 R, Stop am tiefsten Docht seit dem Sweep.</li>"
    "<li>Trades laufen über Nacht, kein Handelsfenster, keine Glattstellung (--hold-overnight).</li>"
    "<li>Höchstens ein Trade pro Zone; teilen mehrere Zonen denselben Sweep, zählt pro Minute und Seite nur einer.</li>"
    "<li>Kosten: Kommission 2,50 $ pro Seite (ES/NQ) plus 1 Tick Slippage pro Seite, in R des Trades.</li></ul>"
    "<h2>Noch offen</h2><ul><li>Starkes Level: N = 2 oder 3</li><li>Fenster Sweep→Tap</li>"
    "<li>Prop-Zeiten (keine Einstiege 14-17 Uhr Chicago, flat 15:10 Chicago)?</li>"
    "<li>Docht unter die Zone, solange sie noch entsteht (vor dem Verlassen): zählt bisher nicht</li></ul>"
)
out.write_text("".join(parts), encoding="utf-8")
print(out)
