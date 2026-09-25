"""Run folder: meta.json, trades.parquet, events.parquet, summary.md (Design §7)."""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

import lsdtrader
from lsdtrader.backtest.runner import RunResult
from lsdtrader.journal.summary import render_markdown, summarize

PRICE_FIELDS = ("entry_signal", "entry_fill", "stop", "target", "exit_raw", "exit_fill")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return out.stdout.strip()


def trade_rows(result: RunResult) -> list[dict[str, Any]]:
    inst = result.instrument
    rows = []
    for t in result.trades:
        row = {k: v for k, v in asdict(t).items() if k != "features"}
        for k in PRICE_FIELDS:
            row[f"{k}_price"] = float(inst.to_price(row[k]))
        row.update({f"feat_{k}": v for k, v in t.features.items()})
        rows.append(row)
    return rows


def event_rows(result: RunResult) -> list[dict[str, Any]]:
    return [
        {
            "bar_index": e.bar_index,
            "side": e.side,
            "kind": e.kind,
            "detail": json.dumps(e.detail, sort_keys=True, default=str),
        }
        for e in result.events
    ]


def build_meta(result: RunResult, data_files: Sequence[Path]) -> dict[str, Any]:
    inst = asdict(result.instrument)
    inst["tick_size"] = str(inst["tick_size"])
    return {
        "package_version": lsdtrader.__version__,
        "git_commit": git_commit(),
        "instrument": inst,
        "strategy_config": asdict(result.strategy_config),
        "execution_config": asdict(result.execution_config),
        "data": [{"path": str(p), "sha256": sha256_file(p)} for p in data_files],
        "n_bars": result.n_bars,
        "n_trades": len(result.trades),
    }


def write_run(result: RunResult, out_dir: Path, data_files: Sequence[Path] = ()) -> Path:
    meta = build_meta(result, data_files)
    fingerprint = hashlib.sha256(json.dumps(meta, sort_keys=True, default=str).encode()).hexdigest()
    now = datetime.now(UTC)
    folder = out_dir / f"{now:%Y%m%d-%H%M%S}_{result.instrument.root}_{fingerprint[:8]}"
    folder.mkdir(parents=True, exist_ok=False)
    meta["created_utc"] = now.isoformat()
    meta["fingerprint"] = fingerprint
    (folder / "meta.json").write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")
    pq.write_table(pa.Table.from_pylist(trade_rows(result)), folder / "trades.parquet")
    pq.write_table(pa.Table.from_pylist(event_rows(result)), folder / "events.parquet")
    title = f"Backtest {result.instrument.root}"
    summary = render_markdown(title, summarize(result.trades), result.n_bars, result.events)
    (folder / "summary.md").write_text(summary, encoding="utf-8")
    return folder
