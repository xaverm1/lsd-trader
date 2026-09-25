# Handoff: current state and next steps (2026-09-25)

Read this first when picking the project up in a new (cloud) session.

## Setup

    bash scripts/cloud_setup.sh

Installs the package, clones the private data repo `xaverm1/lsd-trader-data` into `data/`
(HistData 1-minute CFD files: XAUUSD 2015-2025, SPXUSD 2020-2025), runs the tests.
The data must never be committed to this public repo.

## Goal now

Priority is a profitable strategy for a prop firm (bachelor thesis is on hold).
All testing and optimization happens on **gold (XAUUSD)**.

## Data split (fixed before looking at any gold result)

| Years | Use |
|---|---|
| 2015-2021 | optimize freely |
| 2022-2023 | validate only what survived optimization (2023 has ~600 data holes) |
| 2024-2025 | LOCKED holdout, touched exactly once at the very end |

Pre-2019 files end the daily halt at 17:01 CT (data report flags it; harmless) and some
DST-mismatch weeks may look shifted by one hour, which matters only for time-of-day filters.

## Next task: zone age

Question from Xaver: how old may a zone be (at the sweep) and still trigger a trade?

    F=data/histdata/HISTDATA_COM_ASCII_XAUUSD_M1
    .venv/bin/lsd backtest $(for y in 2015 2016 2017 2018 2019 2020 2021; do echo ${F}_$y.zip; done)
    .venv/bin/python scripts/zone_age.py runs/<run folder>

`zone_age.py` filters the finished run by zone age (exact for 1 trade per zone and no
position limit). Exploratory SPX 2025 result: only zones <= 1 h (12 bars) old were positive
(+0.22 R gross, N=135, not significant). If gold 2015-2021 confirms, add `max_zone_age_bars`
to `StrategyConfig` (spec amendment, test, code), then check on 2022-2023.

### First gold result (2015-2021, default config, run done locally 2026-09-25)

6736 trades, win rate 23.6 %, gross +0.04 R/trade, **net -0.32 R/trade (-2162 R)**.
- Zone age does NOT help on gold: <= 1 h is the worst bucket (gross -0.07 R, N=910);
  the SPX finding did not replicate. No age filter so far.
- **Costs are the real problem:** median stop is only $0.90 while the assumed CFD spread is
  $0.25, so costs are 0.36 R/trade. Stops under $1 (N=3709): gross +0.07, cost 0.53 R.
  Stops $2-3: cost 0.11 R. Next candidates: minimum stop size / stop buffer, and checking
  the real cost of GC/MGC futures at the prop firm (the spread placeholder decides a lot).

### Stop size result (gold 2015-2021, default config, cloud run 2026-09-25)

Same run reproduced exactly (6736 trades, -2162.5 R). `scripts/stop_size.py`:
- A minimum stop does NOT make it profitable under any cost assumption. Best cell: min stop
  $1.5, cost $0.10/oz -> -0.026 R/trade (N=1766). Gross R is ~0 for every stop >= $0.5.
- The only significant gross bucket is stops < $0.5 (+0.156 R, t=2.8, N=1392), exactly where
  costs are 0.83 R, and shorts are better than longs in every small-stop bucket.
- **Suspected model bias:** stop/target hits are evaluated on BID bars for both sides; the
  spread is only deducted from P&L. A short's exits are buys at the ASK, so its stop should
  trigger earlier and its target later than simulated. The bias scales with spread/stop, i.e.
  it inflates exactly the small-stop gross. Fix before any further filter work: shift the
  short side's stop/target checks by the spread (and check where the long entry fills).
- MGC is likely MORE expensive per ounce than the $0.25 CFD placeholder (~$0.55 incl. 1 tick
  slippage per side); GC ~$0.35. A stop buffer cannot be tested post hoc and needs a rerun.

### Spread off (decided by Xaver 2026-09-25)

XAUUSD spread is now 0 (no costs at all on gold): the rules are developed cost-free and
costs are judged later on futures data. Zero-spread 2015-2021 = old gross: +0.041 R/trade,
+276 R, t=1.73; shorts +0.069 (t=2.0), longs +0.012; 2020 and 2021 negative.
Keep in mind when judging a change: GC costs ~ $0.35/oz / stop in R (~0.4 R at the $0.90
median stop), and the short-side bid-bar bias above still inflates short results.

### Hour of day (gold 2015-2021, no costs, `scripts/hour_of_day.py`)

Picture: `docs/results/hour_of_day_gold_2015-2021.png`. No single hour reaches |t| >= 2 (24
tests; one would be expected by chance). Best 09-10 Berlin (+0.19 R/T, N=373, t=1.8, both
halves positive), worst 04-05 (-0.15, N=164) and 18-19 (-0.15, N=182, sign flips between
halves). Session blocks (fixed by convention, not by the result): London 08-14 +0.085 R/T
(N=1952, t=1.8, both halves +), Asia 00-08 +0.048, NY overlap 14-18 +0.022,
NY afternoon 18-24 -0.027. No time filter adopted; a session filter would be a hypothesis
for 2022-2023, not a finding. DST-mismatch weeks before 2019 may shift single hours.

## Working rules

- Each rule change: spec amendment in `docs/specs/2026-09-25-lsd-strategy-v1.md`, failing
  test, code, rerun.
- Change rules only when a setup is recognised wrongly, never because a trade lost.
- Report results with N, costs and the split they come from; beware multiple testing.
- Xaver reads German; explain rule questions with a picture.
- Commits use the noreply address 138877794+xaverm1@users.noreply.github.com.
