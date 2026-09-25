# Handoff: current state and next steps (2026-09-25)

Read this first when picking the project up in a new (cloud) session.

## Setup

    bash scripts/cloud_setup.sh

Installs the package, clones the private data repo `xaverm1/lsd-trader-data` into `data/`
(HistData 1-minute CFD files: XAUUSD 2009-2025, SPXUSD 2020-2025), runs the tests.
The data must never be committed to this public repo.

XAUUSD 2009-2014 were added to the data repo on 2026-09-25 (2009 starts 2009-03-15; HistData
has no earlier gold year). They are not assigned to any split yet and have not been
backtested; Xaver decides their use. Data reports: the daily halt often starts at 17:15 New
York (old COMEX schedule) and ends at 18:00; 2009-2012 have 34-41 holes >= 15 min outside
halts per year (2014-2015: 6-10). The one-hour shift in the US/EU DST-mismatch weeks is fixed
(see "Clock / daylight saving" below).
If the clone fails in the cloud, attach `xaverm1/lsd-trader-data` to the session, clone it
next to this repo and link it: `ln -s ../lsd-trader-data data`.

## Goal now

Priority is a profitable strategy for a prop firm (bachelor thesis is on hold).
All testing and optimization happens on **gold (XAUUSD)**.

## Data split (fixed before looking at any gold result)

| Years | Use |
|---|---|
| 2015-2021 | optimize freely |
| 2022-2023 | validate only what survived optimization (2023 has ~600 data holes) |
| 2024-2025 | LOCKED holdout, touched exactly once at the very end |

Pre-2019 files end the daily halt at 17:01 CT (data report flags it; harmless).

### Clock / daylight saving (fixed 2026-09-25)

HistData files up to 2018 are stamped in New York local time, from 2019 in Berlin time - 6 h.
Both clocks agree except in the 3-4 weeks a year where US and EU daylight saving differ; the
loader used Berlin - 6 h for all years, so in those weeks 2009-2018 bars were one hour late.
Evidence (XAUUSD 2009-2025): the reopen is stamped 18:00/18:01 in every week up to 2018 and
17:00 in the mismatch weeks from 2019; payrolls (08:30 NY) sit at 08:30 in the 2012/2018
files and 07:30 in 2019/2024. The loader now picks the clock by year
(`histdata_clock`), and `lsd data-report` prints a **Clock check** line: how many reopens in
mismatch weeks fall at 18:00-18:05 New York, with a WARNING if fewer than half do (old
loader: 0 of 15-20 in every year up to 2018; now 9/14 to 20/20 in every year, the misses are
ragged old reopens at 17:45-17:59 or late ones after 18:05, none shifted by an hour). Check that line
for every new file. Effect on the gold baseline 2015-2021 (no costs): 6736 -> 6737 trades,
+276 R -> +264 R (+0.041 -> +0.039 R/trade); results below marked (old clock) predate this.

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
costs are judged later on futures data. Zero-spread 2015-2021 = old gross (old clock): +0.041 R/trade,
+276 R, t=1.73; shorts +0.069 (t=2.0), longs +0.012; 2020 and 2021 negative.
Keep in mind when judging a change: GC costs ~ $0.35/oz / stop in R (~0.4 R at the $0.90
median stop), and the short-side bid-bar bias above still inflates short results.

### Hour of day (gold 2015-2021, no costs, `scripts/hour_of_day.py`)

Picture: `docs/results/hour_of_day_gold_2015-2021.png`. No single hour reaches |t| >= 2 (24
tests; one would be expected by chance). Old clock: best 09-10 Berlin (+0.19 R/T, N=373, t=1.8, both
halves positive), worst 04-05 (-0.15, N=164) and 18-19 (-0.15, N=182, sign flips between
halves). Session blocks (fixed by convention, not by the result): London 08-14 +0.085 R/T
(N=1952, t=1.8, both halves +), Asia 00-08 +0.048, NY overlap 14-18 +0.022,
NY afternoon 18-24 -0.027. No time filter adopted; a session filter would be a hypothesis
for 2022-2023, not a finding. Rerun with the fixed clock (picture updated): same picture,
09-10 +0.21 R/T (N=381, t=1.9), 04-05 -0.17 (N=166), 18-19 -0.14 (N=185); still no |t| >= 2.

## Working rules

- Each rule change: spec amendment in `docs/specs/2026-09-25-lsd-strategy-v1.md`, failing
  test, code, rerun.
- Change rules only when a setup is recognised wrongly, never because a trade lost.
- Report results with N, costs and the split they come from; beware multiple testing.
- Xaver reads German; explain rule questions with a picture.
- Commits use the noreply address 138877794+xaverm1@users.noreply.github.com.
