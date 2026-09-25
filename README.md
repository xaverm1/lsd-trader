# lsd-trader

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
