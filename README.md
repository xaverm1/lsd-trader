# lsd-trader

[![CI](https://github.com/xaverm1/lsd-trader/actions/workflows/ci.yml/badge.svg)](https://github.com/xaverm1/lsd-trader/actions/workflows/ci.yml)

Backtest and (later) live engine for the LSD 5-minute futures strategy.

- Strategy rules: [docs/specs/2026-09-25-lsd-strategy-v1.md](docs/specs/2026-09-25-lsd-strategy-v1.md)
- Engine design: [docs/specs/2026-09-25-engine-backtester-design.md](docs/specs/2026-09-25-engine-backtester-design.md)

## Development

```bash
python -m venv .venv
source .venv/Scripts/activate   # Windows Git Bash; on Linux/macOS: source .venv/bin/activate
python -m pip install -e ".[dev]"
pytest
```

## Data

The engine reads 1-minute bars and builds 5-minute bars from them; the broker resolves stops
and targets on the 1-minute bars.

- **HistData.com** ASCII 1-minute zips (free CFD data: SPX/USD, NSX/USD, XAU/USD, XAG/USD,
  WTI/USD). Timestamps are EST without daylight saving and are converted to UTC.
- **Dukascopy** CSV exports (header `Etc/UTC,...`); pass `--instrument`, e.g. `USA500.IDX/USD`.
- **TradingView** JSON chart exports (5-minute bars only).

Put data files under `data/` (git-ignored). Check them before backtesting:

```bash
lsd data-report data/histdata/HISTDATA_COM_ASCII_SPXUSD_M1_2025.zip
```

CFD costs are modelled as a fixed spread paid once per trade (placeholder values per
instrument in `src/lsdtrader/core/instrument.py`).

## Backtest

```bash
lsd backtest data/histdata/HISTDATA_COM_ASCII_SPXUSD_M1_202*.zip --set rr=3 --out runs
lsd backtest path/to/tradingview_export.json
```

Each run writes `runs/<timestamp>_<instrument>_<fingerprint>/` with `meta.json` (config, data
checksums, git commit), `trades.parquet`, `events.parquet` and a descriptive `summary.md`.
Results are in R, net of commission and slippage. A backtest summary is not a verdict on the
strategy; that needs the out-of-sample methodology of sub-project 3.
