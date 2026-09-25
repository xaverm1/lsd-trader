"""Command line: `lsd backtest FILE [--set name=value ...]`."""

from __future__ import annotations

import argparse
import dataclasses
from collections.abc import Sequence
from pathlib import Path

from lsdtrader.backtest.runner import run_backtest
from lsdtrader.core.config import StrategyConfig
from lsdtrader.data.tradingview import load_tradingview_json
from lsdtrader.execution.broker import ExecutionConfig
from lsdtrader.journal.summary import summarize
from lsdtrader.journal.writer import write_run


def parse_value(text: str) -> object:
    if text.lower() == "none":
        return None
    for cast in (int, float):
        try:
            return cast(text)
        except ValueError:
            pass
    return text


def parse_overrides(items: Sequence[str]) -> dict[str, object]:
    names = {f.name for f in dataclasses.fields(StrategyConfig)}
    out: dict[str, object] = {}
    for item in items:
        key, sep, value = item.partition("=")
        if not sep or key not in names:
            raise SystemExit(f"--set expects name=value with name in {sorted(names)}; got {item!r}")
        out[key] = parse_value(value)
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lsd", description="LSD strategy engine")
    sub = parser.add_subparsers(dest="command", required=True)
    bt = sub.add_parser("backtest", help="run a backtest on a TradingView JSON export")
    bt.add_argument("file", type=Path)
    bt.add_argument("--set", action="append", default=[], metavar="NAME=VALUE")
    bt.add_argument("--sizing", choices=["research", "realistic"], default="research")
    bt.add_argument("--risk", type=float, default=100.0, help="USD risk per trade (1R)")
    bt.add_argument("--out", type=Path, default=Path("runs"))
    args = parser.parse_args(argv)

    cfg = StrategyConfig(**parse_overrides(args.set))  # type: ignore[arg-type]
    exec_cfg = ExecutionConfig(sizing=args.sizing, risk_usd=args.risk)
    instrument, bars = load_tradingview_json(args.file)
    result = run_backtest(instrument, bars, None, cfg, exec_cfg)
    folder = write_run(result, args.out, [args.file])
    s = summarize(result.trades)
    print(
        f"{instrument.root}: {result.n_bars} bars, {s.n} trades, win rate {s.win_rate:.1%}, "
        f"avg net R {s.avg_net_r:+.3f}, total {s.total_net_r:+.2f}R"
    )
    print(f"run folder: {folder}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
