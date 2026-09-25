# Engine, Backtester & Data — Design (Sub-project 2)

**Status:** approved 2026-09-25 · **Date:** 2026-09-25 · **Owner:** Xaver
**Implements:** [LSD Strategy Spec v1.0](2026-09-25-lsd-strategy-v1.md)
**Out of scope:** profitability verdict, out-of-sample / walk-forward methodology (sub-project 3), live data and paper trading (sub-project 4), dashboard (sub-project 5), real orders (sub-project 6).

---

## 1. Goals

1. One strategy implementation that runs unchanged in backtest and, later, live. The retired setup (Pine + Python parity copy) is not repeated.
2. Years of historical data at a cost of at most 50 EUR.
3. Every result reproducible: same data + same config + same code → bit-identical output.
4. Every decision explainable: each rejected setup carries a named reason; any timestamp can be inspected as a chart.
5. Code the owner can read and explain: plain Python, small modules, fully tested.

## 2. Decisions

| Topic | Decision | Reason |
|---|---|---|
| Approach | Own lightweight event-driven engine in Python | stateful strategy (zones move, die, P gets replaced) does not vectorise; full control and explainability; own contribution for thesis |
| Rejected | NautilusTrader (steep learning curve, no Rithmic adapter known), vectorised pandas/vectorbt (stateful rules, backtest/live split returns) | |
| Language | Python 3.12+ only, including the later dashboard (Streamlit) | owner's experience; one language to explain |
| History source | Databento, dataset `GLBX.MDP3`, schema `ohlcv-1m` | official CME data, many years, pay-as-you-go, 125 USD new-account credit; no 5-minute schema exists, so 1-minute is aggregated |
| Instruments for research | Full-size contracts ES, NQ, YM, RTY, GC, SI, CL | longer history than micros (micros start 2019/2021); same tick size and price action |
| Micro vs mini | Research question for sub-project 3 | charts can differ by 1–2 ticks and flip setups under tick-exact rules; costs in R differ ~10× |
| Continuous series | Volume-based roll, difference (Panama) back-adjustment | a roll gap is not a BOS; difference adjustment keeps distances and the tick grid exact |
| Storage | Local Parquet files with checksums | no database needed at this size |
| Live data (later) | Rithmic via a prop-firm account | included with the account; API permission to be checked with the firm before buying |

## 3. Package layout

```
lsd-trader/
├─ src/lsdtrader/
│  ├─ core/          Bar, Instrument (tick size, tick value, sessions), CME calendar, Config
│  ├─ strategy/
│  │   ├─ swings.py      M1 swings
│  │   ├─ structure.py   M2 P, L0, H2, BOS
│  │   ├─ zones.py       M3 origin, relocation, geometry, destruction, extra zones
│  │   ├─ liquidity.py   M4 P′ validity
│  │   ├─ setups.py      M5 sweep → tap → entry
│  │   └─ lsd.py         composes M1–M5: on_bar(bar) -> list[Signal]
│  ├─ execution/     Broker interface, SimBroker (M6: SL/TP, costs, flat before breaks, sizing)
│  ├─ data/          Databento client, Parquet store, roll + adjustment, 1m → 5m, data report
│  ├─ backtest/      Runner: data → strategy → broker → journal
│  ├─ journal/       trades and events tables, run metadata
│  ├─ viz/           trade and timestamp charts
│  └─ cli.py         lsd fetch | backtest | inspect | report
├─ tests/
├─ docs/specs/
└─ .github/workflows/ci.yml
```

### Boundaries

- **strategy/** knows nothing about clocks, costs, sizing or brokers. Input: closed 5-minute bars of one instrument. Output: `Signal(direction, entry_price, stop, target, setup_id, features)`. All rule counters are emitted as events.
- **execution/** owns everything in Strategy Spec §8: fills, slippage, commission, SL/TP resolution, flat before CME breaks, sizing mode. `Broker` is an interface with `SimBroker` now and `RithmicBroker` in sub-project 6.
- **data/** delivers, per instrument, a continuous adjusted 5-minute series for the strategy and the matching 1-minute bars (real contract prices) for the broker.
- **backtest/** wires them; the future live runner (sub-project 4) wires the same strategy and broker interface to a live feed.
- One strategy instance per instrument. Instruments are independent and can run in parallel processes.

## 4. Data

### 4.1 Fetch

- `lsd fetch <ROOT> <FROM> <TO>` downloads `ohlcv-1m` for all individual outright contracts of the root in the range.
- Before downloading, the command queries Databento's cost estimate, prints it, and asks for confirmation. A hard budget cap (`data.budget_usd`, default equivalent of 50 EUR, cumulative across fetches, tracked in a local ledger) refuses any fetch that would exceed it.
- The API key is read from an environment variable and never written to disk or logs.
- Raw files are immutable: `data/raw/<root>/<contract>.parquet` plus a SHA-256 manifest. Already downloaded ranges are never fetched again.

### 4.2 Continuous series and roll

- **Roll rule:** switch to the next contract at the first session boundary after its daily volume exceeds the current contract's daily volume.
- **Adjustment:** difference (Panama) back-adjustment: at each roll, all earlier bars are shifted by `(new_close − old_close)` at the roll boundary, an exact multiple of the tick size.
- The adjusted series is used **only** for strategy decisions. The broker fills on real prices of the contract that was front at that time: entry, SL and TP are converted by the known offset of that segment. Results are in R, so the offset cancels out.
- Rolls happen at a session boundary, where all positions are already flat (Strategy Spec §8.2); no trade spans a roll.
- The roll schedule (dates, contracts, offsets) is stored with the series and printed in the data report.

### 4.3 Aggregation 1m → 5m

- 5-minute bars are aligned to wall-clock multiples of 5 minutes in exchange time (as on TradingView). A 5-minute bar exists if at least one 1-minute bar exists in its window; `open` = first open, `high` = max, `low` = min, `close` = last close, `volume` = sum.
- The strategy sees only 5-minute bars. The broker resolves SL/TP inside a 5-minute bar using its 1-minute bars; only if SL and TP fall inside the same 1-minute bar is SL assumed first.

### 4.4 Data report

`lsd report data` lists per instrument: covered range, roll schedule, missing minutes inside trading hours, bars outside trading hours, and price jumps above a threshold (in ticks). Problems are reported, never silently repaired.

## 5. Strategy core

### 5.1 Per-bar order of operations

For each closed 5-minute bar of an instrument:

1. **Broker:** evaluate open positions against this bar's 1-minute bars (SL, TP, flat before break).
2. **Zones:** destruction check → relocation (build phase only) → mark zones that are left.
3. **Swings:** register swings confirmed on this bar.
4. **Structure:** update P candidates (undercut → replaced), check BOS → create zone(s) and register new liquidity.
5. **Setups:** detect sweeps of valid P′ → tap → entry trigger.
6. **Signals:** emit entries; the broker fills at this bar's close (+ slippage). Exits for these positions are evaluated from the next bar.

Step 1 runs before step 6, so a position opened on bar `e` is first checked on bar `e + 1`. Step 2 runs before step 5, so a bar closing inside a zone destroys it before its tap can count.

### 5.2 Configuration

All parameters of Strategy Spec §9 live in one immutable `Config` object (defaults = primary hypothesis). Execution parameters (costs per instrument, sizing mode, session window, max open positions) live in `ExecutionConfig`. Both are serialised into every run.

### 5.3 Counters and events

Every rule that rejects or kills an object emits a named event (`cand_no_lower_low`, `cand_undercut`, `zone_relocations`, `zone_destroyed_close`, `no_tap`, `no_entry`, …, full list in Strategy Spec). A missing setup must always be explainable by events.

## 6. Execution (SimBroker)

- **Entry:** market at signal bar close + `slippage_ticks` (default 1) against the trade.
- **Stop:** stop price − `slippage_ticks`; if a 1-minute bar opens beyond the stop, fill at that open (− slippage).
- **Target:** limit at TP, no slippage.
- **Flat before break:** close of the last 5-minute bar before each CME daily maintenance break and before the weekend (CME calendar incl. DST and holidays), + slippage.
- **Costs:** commission per contract per side and slippage ticks, configurable per instrument.
- **Sizing:** `research` (fractional quantity, exactly 1R) or `realistic` (integer contracts, `qty < 1` → skipped and counted).
- **Per-trade results:** net R, gross R, cost in R, MFE and MAE in R, exit reason (`tp`, `sl`, `flat_break`).

## 7. Journal

Each run writes a folder `runs/<timestamp>_<short-hash>/` with:

- `meta.json` — Config, ExecutionConfig, data manifest checksums, git commit, package version, run duration.
- `trades.parquet` — one row per trade: instrument, direction, zone (bars, top, bottom, type), P′ (bar, price), sweep/tap/entry/exit times, entry/SL/TP/exit prices (real contract prices), quantity, net/gross R, cost R, MFE/MAE R, exit reason, plus **decision-time features**: zone height (ticks), zone type, P′→zone distance (ticks, ATR), bars sweep→tap, bars tap→entry, stop (ticks), cost in R, time of day, weekday.
- `events.parquet` — every counter event with timestamp, instrument, object id and reason; rejected setups carry the same decision-time features.
- `summary.md` — N, win rate, average net and gross R, average cost R, longest losing streak, trades per instrument, top event counts. Descriptive only.

Features are stored so later questions can be answered without re-running; they are analysed only for questions registered in advance (sub-project 3).

## 8. Visual inspection

- `lsd inspect <run> --trade <id>` and `lsd inspect <instrument> --at "<timestamp>"` render a candlestick chart (static PNG and interactive HTML) with zones (active / left / destroyed), swings, P, H2, BOS, P′, sweep, tap, entry, SL, TP, and a side table of all events in the window.
- `--at` works without a run: it replays the strategy up to that timestamp and shows the state, answering "why was there no setup here?".

## 9. Testing

| Test | Checks |
|---|---|
| Spec scenarios | the 17 acceptance scenarios of Strategy Spec §11 as hand-built bar fixtures |
| Unit tests | each strategy module and the SimBroker in isolation |
| Mirror test | inverting prices (high ↔ low around a pivot value) turns every long into the exact mirrored short and vice versa |
| No-lookahead test | a full run and a bar-by-bar run that is stopped and restarted after every bar produce identical signals and events |
| Determinism | same data + config → bit-identical journal |
| Data tests | aggregation, roll detection and adjustment on synthetic contracts with known answers |

Tooling: `pytest` with coverage, `ruff` (lint + format), `mypy` on `src/`, GitHub Actions running all of it on every push. README with architecture diagram and example output.

## 10. Definition of done

1. All tests green; line coverage of `strategy/` and `execution/` ≥ 90 %.
2. 1-minute history for ES, NQ, YM, RTY, GC, SI, CL fetched and checked (data report reviewed), total spend ≤ 50 EUR.
3. `lsd backtest` runs over all seven instruments with default config and writes a complete run folder.
4. Xaver has inspected **10 randomly drawn trades and 10 randomly drawn rejected setups** (seeded draw, seed recorded) with `lsd inspect` and confirmed they follow the rules; every disagreement is either a spec change (versioned) or a bug fix.
5. The extended golden set is checked: the engine finds the agreed share (v1: ≥ 7 of 9), every miss explained by events.

## 11. Risks

| Risk | Mitigation |
|---|---|
| Databento cost above estimate | cost query before every fetch, hard cumulative budget cap |
| Roll logic creates false structure | roll schedule in data report; synthetic roll tests; visual check around roll dates |
| Owner cannot follow the code | small modules, docstrings referencing spec sections, walkthrough after each module |
| First backtest numbers tempt rule changes | no verdict in sub-project 2; pre-registration happens in sub-project 3 before results are read |

## 12. Amendment 2026-09-25 — data sources

Databento could not be used: the only available card was rejected at signup before it reached the card issuer (support request pending). FirstRate Data (≈190 EUR per instrument) and Kibot (≥ 400 USD) exceed the 50 EUR budget. Dukascopy's free web export delivers one day per 1-minute file and its HTTP feed blocks scripted access; mass-automating either is not done.

Decision (Xaver, 2026-09-25):

- **Primary source for building and first tests: HistData.com free 1-minute CFD data** (SPX/USD, NSX/USD, XAU/USD, XAG/USD, WTI/USD; bid only, no volume). **Correction after review:** the HistData clock is *not* fixed EST; it is Europe/Berlin time minus 6 hours (UTC−5 in European winter, UTC−4 in European summer), verified on SPXUSD 2020 against the daily 16:14 New York halt. **Second correction (2026-09-25):** this holds from 2019; files up to 2018 are stamped in New York local time (verified on XAUUSD 2009-2025 via the reopen and payroll minutes in the US/EU daylight-saving mismatch weeks). The loader picks the clock by year and the data report checks the reopen in those weeks. The data report treats a pause as an expected break only if trading resumes at 18:00 New York; every other pause of 15 minutes or more is listed, so data holes and time-zone errors surface.. Downloaded so far: SPX/USD 2020–2025.
- **Dukascopy CSV exports** are supported as a second CFD source (manual, small samples).
- **Futures data** (Databento or a prop-firm Rithmic feed) stays planned as a second source; §4.1–4.2 (fetch, roll, Panama adjustment) move to that later plan. CFDs have no contract roll.
- **CFD cost model:** a fixed spread per instrument, paid once per trade on entry (bars are bid prices); commission 0, slippage 0. Values are placeholders until measured (Dukascopy exports bid and ask, so the spread can be measured there).
  *Amendment 2026-09-25:* XAUUSD spread set to 0 while the rules are developed; costs are
  judged later on futures data. Gross R = net R for gold runs until then.
- The CFD-vs-futures comparison (same rules, 1–2 tick differences) is kept as a research question for sub-project 3.

## 13. Acceptance log

- **2026-09-25 — §10.4 visual review: accepted by Xaver.** Run `20260925-135322_SPXUSD_53867d92` (SPXUSD 2025, HistData, default config, 792 trades): 10 random trades and 10 near-miss rejections (`lsd review`, seed 1) plus the full interactive chart of all trades (`lsd chart`). Verdict: "scheint alles zu passen". During the review cycle one engine bug was found and fixed (duplicate zones via relocation, 75 duplicate trades).
- §10.5 golden set: open — waits for Xaver's extended list.
