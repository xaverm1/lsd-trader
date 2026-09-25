"""Command line.

    lsd backtest FILE... [--instrument ROOT] [--set name=value ...]
    lsd data-report FILE... [--instrument ROOT] [--out report.md]

FILE is a TradingView JSON export (5-minute bars) or one or more 1-minute files
(HistData .zip, Dukascopy .csv), which are merged and aggregated to 5 minutes.
"""

from __future__ import annotations

import argparse
import dataclasses
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from lsdtrader.backtest.runner import run_backtest
from lsdtrader.core.bar import TickBar
from lsdtrader.core.config import StrategyConfig
from lsdtrader.core.instrument import Instrument, get_instrument
from lsdtrader.data.aggregate import to_five_minute
from lsdtrader.data.minute_files import histdata_symbol, load_minute_files
from lsdtrader.data.report import build_report
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


@dataclasses.dataclass(frozen=True, slots=True)
class LoadedData:
    instrument: Instrument
    bars: list[TickBar]  # 5-minute
    minutes: dict[datetime, list[TickBar]] | None  # 1-minute bars per 5-minute bar
    minute_bars: list[TickBar]
    source: str
    duplicates_dropped: int = 0


def load_data(files: Sequence[Path], instrument: str | None) -> LoadedData:
    if len(files) == 1 and files[0].suffix.lower() == ".json":
        inst, bars = load_tradingview_json(files[0])
        return LoadedData(inst, bars, None, [], "tradingview 5m")
    symbols = {histdata_symbol(f) for f in files if f.suffix.lower() == ".zip"}
    if len(symbols) > 1:
        raise SystemExit(f"files are for different instruments: {sorted(symbols)}")
    if instrument is None:
        if not symbols:
            raise SystemExit("--instrument is required for Dukascopy CSV files")
        (instrument,) = symbols
    inst = get_instrument(instrument)
    if symbols and get_instrument(next(iter(symbols))) is not inst:
        raise SystemExit(f"--instrument {instrument} does not match the files ({symbols.pop()})")
    minute_bars, dropped = load_minute_files(files, inst)
    bars, minutes = to_five_minute(minute_bars)
    return LoadedData(inst, bars, minutes, minute_bars, "1m files aggregated to 5m", dropped)


def cmd_backtest(args: argparse.Namespace) -> int:
    cfg = StrategyConfig(**parse_overrides(args.set))  # type: ignore[arg-type]
    exec_cfg = ExecutionConfig(sizing=args.sizing, risk_usd=args.risk)
    data = load_data(args.files, args.instrument)
    result = run_backtest(data.instrument, data.bars, data.minutes, cfg, exec_cfg)
    notes = {
        "data_source": data.source,
        "exit_resolution": "1-minute bars" if data.minutes else "5-minute bars (stop first)",
    }
    folder = write_run(result, args.out, args.files, notes)
    s = summarize(result.trades)
    print(
        f"{data.instrument.root}: {result.n_bars} bars, {s.n} trades, "
        f"win rate {s.win_rate:.1%}, avg net R {s.avg_net_r:+.3f}, total {s.total_net_r:+.2f}R"
    )
    print(f"run folder: {folder}")
    return 0


def cmd_data_report(args: argparse.Namespace) -> int:
    data = load_data(args.files, args.instrument)
    if not data.minute_bars:
        raise SystemExit("data-report needs 1-minute files (HistData .zip or Dukascopy .csv)")
    report = build_report(data.instrument, data.minute_bars, data.duplicates_dropped)
    text = report.to_markdown()
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"report written to {args.out}")
    else:
        print(text, end="")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lsd", description="LSD strategy engine")
    sub = parser.add_subparsers(dest="command", required=True)

    bt = sub.add_parser("backtest", help="run a backtest")
    bt.add_argument("files", type=Path, nargs="+")
    bt.add_argument("--instrument", help="instrument root, e.g. SPXUSD (default: from the file)")
    bt.add_argument("--set", action="append", default=[], metavar="NAME=VALUE")
    bt.add_argument("--sizing", choices=["research", "realistic"], default="research")
    bt.add_argument("--risk", type=float, default=100.0, help="USD risk per trade (1R)")
    bt.add_argument("--out", type=Path, default=Path("runs"))
    bt.set_defaults(func=cmd_backtest)

    dr = sub.add_parser("data-report", help="gaps and price jumps in 1-minute files")
    dr.add_argument("files", type=Path, nargs="+")
    dr.add_argument("--instrument")
    dr.add_argument("--out", type=Path)
    dr.set_defaults(func=cmd_data_report)

    args = parser.parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
