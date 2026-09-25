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

## Backtest

```bash
lsd backtest path/to/tradingview_export.json --set rr=3 --out runs
```

Each run writes `runs/<timestamp>_<instrument>_<fingerprint>/` with `meta.json` (config, data
checksums, git commit), `trades.parquet`, `events.parquet` and a descriptive `summary.md`.
Results are in R, net of commission and slippage. A backtest summary is not a verdict on the
strategy; that needs the out-of-sample methodology of sub-project 3.
