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

## Working rules

- Each rule change: spec amendment in `docs/specs/2026-09-25-lsd-strategy-v1.md`, failing
  test, code, rerun.
- Change rules only when a setup is recognised wrongly, never because a trade lost.
- Report results with N, costs and the split they come from; beware multiple testing.
- Xaver reads German; explain rule questions with a picture.
- Commits use the noreply address 138877794+xaverm1@users.noreply.github.com.
