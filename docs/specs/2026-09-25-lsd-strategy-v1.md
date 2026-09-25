# LSD 5min Strategy — Specification v1.0

**Status:** draft for review · **Date:** 2026-09-25 · **Owner:** Xaver
**Scope:** the mechanical trading rules only. Engine architecture, data, research and live execution are specified separately (sub-projects 2–6).

This document is the single source of truth for the strategy. Code and tests are derived from it, never from the retired Pine script (`lsd-bot/old_lsd.pine`, `lsd-bot/lsd_bot.pine`) or the earlier `lsd-bot/SPEC.md`. Where this spec deviates from those, the deviation is listed in §10.

Every rule is written for a **long** setup (demand). A **short** setup (supply) is the exact mirror: swap high ↔ low, above ↔ below, bullish ↔ bearish, `<` ↔ `>`, `min` ↔ `max`.

---

## 1. Overview

```
Zone exists (created by an earlier BOS)
  → above it a higher low P′ forms and produces its own BOS   (P′ = liquidity)
  → price sweeps P′
  → price taps the zone within a few bars
  → first bullish close → entry at that close
  → SL at the lowest wick since the sweep, TP at 4R
```

## 2. Conventions

- **Timeframe:** 5-minute bars. All rules are evaluated at bar close. No rule may use information from a bar that has not closed (no lookahead).
- **Bar fields:** `open, high, low, close`. `bodyTop = max(open, close)`, `bodyBot = min(open, close)`.
- **Bearish bar:** `close < open`. **Bullish bar:** `close > open`. **Doji:** `close == open` (exact equality; tolerance parameter `dojiTolTicks`, default 0).
- **Opposing bar (for a demand zone):** bearish or doji.
- **tick:** the instrument's minimum price increment.
- Parameters are written as `name` and listed with defaults in §9.

---

## 3. Swings (M1)

A **swing low** at bar `c` with pivot length `n = pivLen`:

```
left  (i = 1..n):  low[c−i] <  low[c]   → not a swing   (equal on the left is allowed)
right (i = 1..n):  low[c+i] <= low[c]   → not a swing   (right side must be strictly higher)
```

- Consequence: in a run of bars with the identical low, exactly one bar becomes the swing — the **rightmost** one.
- A swing is **confirmed** at the close of bar `c + n` and may only be used from then on.
- Bar colour is irrelevant for swings.
- Swing highs are mirrored.

## 4. Liquidity candidate P and break of structure (M2)

### 4.1 Definitions

- **P** — a confirmed swing low that is a candidate to produce a BOS.
- **L0(P)** — the most recent confirmed swing low before P with `L0.low < P.low` (**strictly** lower).
- **H2(P)** — the highest high of all bars from L0 to P (inclusive). This is the start of the leg that ended in P.

### 4.2 Rules

1. **P must be a higher low.** If no L0 exists (no earlier swing low is strictly lower than P), P is **not a candidate**. Counter: `cand_no_lower_low`.
   - An **equal low** (`P.low == previous swing low`) counts as a higher low: the previous swing is not strictly lower, so the search continues back to the next strictly lower swing.
2. **BOS:** the first bar after P whose `close > H2(P)` (one tick is enough).
   - Setting `bosConfirm`: `close` (default) or `wick` (`high > H2(P)`).
   - Bars between P and P's confirmation bar are included in the BOS check.
3. **P dies** if any bar before the BOS has `low < P.low`. The new, lower swing becomes the next candidate with its own L0 and H2. Counter: `cand_undercut`.
   - Equivalent formulation: *at the moment of the BOS, P is the lowest swing low between H2 and the BOS bar.*
   - If the new low falls below L0, rule 1 is re-evaluated for it (typically a different L0 and a higher H2).
4. **Optional time limit** `bosMaxBars` (default **off**): if no BOS occurs within that many bars after P, P expires. Counter: `cand_expired`.
5. A P that produced a BOS has two roles at once:
   - it creates a new zone (§5), and
   - it becomes liquidity P′ for older zones below it (§6).

## 5. Zones (M3)

### 5.1 Origin bar O

When P produces a BOS, a demand zone is created:

- Search backwards from P's bar (**inclusive**) up to `zoneLookback` bars (default 20). The first **opposing bar** found is **O**.
- If none is found, O = P's bar (even if bullish).

### 5.2 Build phase and relocation

The zone is replayed bar by bar from O+1 up to the current bar (so its state is identical whether it was tracked live or created retroactively). The build phase lasts until the zone is **left**: the first bar with `low > top`.

For each bar during the build phase, in this order:

1. **Relocation:** if the bar is an opposing bar and overlaps the zone (`low ≤ top and high ≥ bot`), the zone moves to this bar: it becomes the new O, geometry resets to pending. Counter: `zone_relocations`. Relocation can happen repeatedly.
2. Otherwise, if geometry is still pending, this bar is **F** (the follow-up bar) and fixes the geometry (§5.3).
3. **Death during build:** `close < bot`. Counter: `zone_died_building`.

Once the zone has been left, relocation no longer applies. Any later return is a tap attempt or destroys the zone (§5.4).

### 5.3 Geometry

| Type | Condition | Top | Bottom |
|---|---|---|---|
| **Normal** | `F.high > O.high` | `O.high` | `O.low` |
| **Accuracy** | `F.high ≤ O.high` | `O.bodyTop` | `min(O.low, F.low)` |

- The comparison is strict: `F.high == O.high` → Accuracy.
- Normal always stays on the O bar; F never extends a Normal zone.
- Until F exists, the zone uses Normal geometry provisionally.
- Setting `zoneMode`: `auto` (default, table above) or `normal` (always Normal, F ignored).

### 5.4 Destruction (after the zone has been left)

A demand zone is **destroyed** by the first bar that satisfies any of:

1. `close ≤ top` — close inside the zone (or below it)
2. `low < bot` — wick through the entire zone

Destruction is checked **before** the tap on every bar, so a bar that closes inside the zone destroys it and is not a valid tap. Counters: `zone_destroyed_close`, `zone_destroyed_wick`.

Research variant `zoneKill = closeBeyond` (not default): destroyed only on `close < bot`.

### 5.5 Additional zones between P and BOS

Setting `extraZones`:

- `none` (**default**): only the zone from §5.1/5.2.
- `last`: additionally, the last opposing bar between P and the BOS bar that does **not** overlap any zone created from this BOS becomes its own zone.
- `all`: every such non-overlapping opposing bar between P and the BOS bar becomes its own zone.

Each zone is tracked independently. Several zones may be active at once, also stacked.

## 6. Liquidity P′ (M4)

A swing low P′ is valid liquidity for zone Z if **all** hold, evaluated at the moment of the sweep:

1. P′ produced a BOS under §4 (it is a higher low with its own BOS).
2. P′'s bar is after Z's origin bar O. (P′ may form before or after the BOS that created Z.)
3. `P′.low > Z.top` — P′ sits in front of the zone.
4. P′ has not been swept before.
5. Z has been left and is not destroyed.
6. Optional research filter `liqMaxDistATR` (default **off**): `P′.low − Z.top ≤ liqMaxDistATR × ATR(14)` on the sweep bar.

Multiple P′ per zone are allowed; whichever is swept first starts the setup. If a sweep matches no zone, exactly one reason is counted: the furthest stage reached (`no_zone_below` < `zone_not_left` < `liq_before_zone` < `too_far`).

## 7. Sweep → tap → entry (M5)

- **Sweep:** a bar with `low < P′.low`.
- **Tap:** a bar `t` with `sweepBar ≤ t ≤ sweepBar + maxBarsSweepToTap` (default 3) and `low ≤ Z.top + tapTolTicks × tick` (default tolerance **0**: touching the top edge is enough, stopping short is not). Sweep and tap may be the same bar.
- **Entry:** the first bar `e` with `tapBar ≤ e ≤ tapBar + maxBarsTapToEntry` (default 3) that satisfies the entry trigger while Z is intact. Fill at `close[e]`.
  - Setting `entryTrigger`: `bullish` (**default**: `close > open`), `aboveTapHigh` (bullish and `close > high[tapBar]`), `aboveLiq` (bullish and `close > P′.low`), `minBody` (bullish with body ≥ `minBodyTicks`).
  - Because a close inside the zone destroys it (§5.4), a valid entry bar always closes above `Z.top`.
- **One trade per zone** (`maxTradesPerZone = 1`). After an entry the zone is consumed.
- If the tap or entry window expires, the setup is dropped (counters `no_tap`, `no_entry`); P′ stays swept.

## 8. Orders, exits and risk (M6)

### 8.1 Stop and target

- **SL** = lowest low from the sweep bar to the entry bar − `slBufferTicks × tick` (default buffer **0**).
- **TP** = entry + `rr` × (entry − SL). Default `rr = 4`.
- Research variants: `slMode = zoneBottom | zoneMid` (low priority), `rr ∈ {3, 5, 6}`.

### 8.2 Trade management

- A trade is entered at the close of bar `e`; exits are evaluated from bar `e + 1`.
- **Both SL and TP inside one bar:** assume SL (pessimistic).
- **Gaps:** if a bar opens beyond the SL, the stop fills at the open.
- **Flat before breaks:** any open position is closed at the close of the last bar before each CME daily maintenance break and before the weekend close (CME calendar, including DST changes and holidays). No new entries on that last bar.
- **Sessions:** entries allowed around the clock by default. Setting `sessionWindow` (default off) restricts new entries to a time window.
- **Concurrent positions:** unlimited by default. Setting `maxOpenPositions` (default off).

### 8.3 Sizing and costs

- Results are measured in **R** (realised PnL ÷ planned risk).
- **Research mode (default):** fractional size so that every trade risks exactly 1R.
- **Realistic mode:** `qty = floor(riskPerTrade ÷ (stopTicks × tickValue))`; `qty < 1` → no trade (counter `qty_zero`). Actual risk per trade is recorded.
- **Costs:** commission per contract per side (placeholder 1.24 USD — replace with the real broker/prop-firm figure) and slippage of 1 tick on market entries and stop exits. TP limit exits have no slippage. R is reported **net** of costs; gross R is reported alongside.

### 8.4 Instruments

MNQ, MES, MYM, M2K, MGC, SIL, MCL (CME micro futures), 5-minute bars. Contract rolls and continuous-series construction are specified in sub-project 2.

### 8.5 Not in v1

Trend filters, key-level / potential analysis, opposing zones, news filter, break-even, partial exits, flip or break-of-candle entries, reclaim entries.

## 9. Parameters

| Parameter | Default | Research variants |
|---|---|---|
| `pivLen` | 1 | 2, 3 |
| `bosConfirm` | close | wick |
| `bosMaxBars` | off | e.g. 24, 108 |
| `zoneLookback` | 20 | — |
| `dojiTolTicks` | 0 | — |
| `zoneMode` | auto | normal |
| `extraZones` | none | last, all |
| `zoneKill` | closeInside | closeBeyond |
| `liqMaxDistATR` | off | 0.5, 1, 2 |
| `maxBarsSweepToTap` | 3 | 1–6 |
| `tapTolTicks` | 0 | — |
| `maxBarsTapToEntry` | 3 | 1–6 |
| `entryTrigger` | bullish | aboveTapHigh, aboveLiq, minBody |
| `slBufferTicks` | 0 | 1, 2 |
| `slMode` | wick | zoneBottom, zoneMid |
| `rr` | 4 | 3, 5, 6 |
| `sessionWindow` | off | hour windows (selected in-sample, confirmed out-of-sample) |
| `maxOpenPositions` | off | 1, 2 |
| `maxTradesPerZone` | 1 | — |
| `sizing` | research (1R exact) | realistic |

The **defaults are the primary hypothesis**. Every variant tested is counted, and results of the best variant are corrected for the number of variants tried (sub-project 3).

## 10. Deviations from the retired `lsd-bot/SPEC.md`

| Topic | Old | Now | Why |
|---|---|---|---|
| BOS reference | separate 3/3 pivot set, most recent ref-high before P | H2 = highest high between L0 and P | matches how the BOS is read on the chart; removes the confirmation-lag problem |
| Higher-low requirement | none | P must be a higher low; no lower swing → no candidate | a lower low cannot be liquidity for a long |
| Accuracy bottom | `min(O.bodyBot, F.low)` | `min(O.low, F.low)` | the old rule cut O's lower wick and placed zones too high |
| Activation / `buildMaxBars` | explicit activation + 30-bar build limit | build phase ends when zone is left; no bar limit | liquidity above the zone implies the zone was left |
| Tap tolerance | 2 ticks | 0 ticks | a near miss is not a tap |
| SL buffer | 1 tick | 0 ticks | stop sits exactly at the wick |
| Session | 08:00–17:00 Berlin, flat 17:00 | 24/7, flat before every CME break and weekend | find the best hours from data instead of assuming them |
| Concurrent positions | 1 | unlimited (setting) | measure the raw signal first |
| Sizing | 150 USD, integer contracts | research mode: exactly 1R | equal risk per trade; dollar risk irrelevant at this stage |
| Extra zones | — | `extraZones` setting | open question, answered by data |

## 11. Acceptance scenarios

Each scenario becomes a hand-built bar fixture and a unit test. They correspond to the diagrams agreed in the review session of 2026-09-25.

1. **Swing equal lows:** three bars with identical lows → exactly one swing, on the rightmost bar.
2. **H2 selection, uptrend:** leg L0 → H2 → l → h → P with `l > P` → BOS level is H2, not h.
3. **No lower low:** P below every earlier swing low → no candidate, `cand_no_lower_low` += 1.
4. **Equal low:** P == previous swing low → counts as higher low; H2 taken from the range starting at the next strictly lower swing.
5. **P undercut:** price trades below P before BOS → P dies, new low becomes P, BOS over the same H2 is attributed to the new P.
6. **Origin bar:** (a) P bearish → O = P; (b) P bullish, bar before bearish → O = bar before; (c) bearish pullback after P overlapping P's zone → relocation to the pullback.
7. **Extra zones:** non-overlapping pullback between P and BOS → no extra zone under `none`, one under `last`, all under `all`.
8. **Geometry:** Normal (F above O.high) → [O.low, O.high]; Accuracy with F.low above O.low → [O.low, O.bodyTop]; Accuracy with F.low below O.low → [F.low, O.bodyTop]; Normal with F.low below O.low → bottom stays O.low.
9. **Destruction:** wick in + close above → valid tap; close inside → destroyed; wick through → destroyed; close below → destroyed.
10. **Liquidity timing:** higher low Pa inside the impulse before BOS 1 with its own BOS, and Pb after BOS 1 → both valid liquidity.
11. **No liquidity:** zone left, immediate return without any P′ → no setup.
12. **Tap tolerance:** wick into zone → tap; touches top exactly → tap; stops 2 ticks above → no tap.
13. **Entry:** tap bar itself bullish → entry on tap bar; bearish tap then small bullish bar within 3 bars → entry; no bullish bar within 3 bars → `no_entry`.
14. **Full long trade:** zone → P′ with BOS → sweep → tap → entry → SL at lowest wick, TP at 4R, exit at TP.
15. **Same-bar SL and TP:** exit at SL.
16. **Flat before break:** position open at the last bar before the CME daily break → closed at that bar's close.
17. **Short mirror:** scenario 14 mirrored produces the mirrored trade.

### Golden set

The nine RD Concepts trades from the video of 2026-09-03 (table in `lsd-bot/SPEC.md` §8) remain the external acceptance test: **the engine must find at least 7 of 9 with the same zone and the same sweep, and every miss must be explainable by a counter.** The trades are unconfirmed; several lie before 2026-08-02 and need the longer history from sub-project 2. Xaver confirms each match.

## 12. Open items

- Real commission per contract for the chosen prop firm / broker.
- Golden-set confirmation (blocked on historical data).
