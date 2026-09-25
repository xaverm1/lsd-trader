"""Candlestick charts with strategy overlays (Design §8), rendered to PNG with matplotlib.

Times on the x-axis are Europe/Berlin. A trade is drawn as a position box like TradingView's
long/short tool: green from entry to target, red from entry to stop, prices at the right.
Markers are symbols explained in a legend, so labels never pile up on the entry bar.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

import matplotlib

matplotlib.use("Agg")  # no display needed
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

from lsdtrader.core.bar import TickBar  # noqa: E402
from lsdtrader.core.instrument import Instrument  # noqa: E402

UP, DOWN, NEUTRAL = "#1D9E75", "#D85A30", "#888780"
WIN, LOSS, INK = "#1D9E75", "#E24B4A", "#2C2C2A"
BERLIN = ZoneInfo("Europe/Berlin")
MIN_POSITION_BARS = 15  # a position box is at least this wide so its prices stay readable

Shape = Literal["o", "^", "v", "D", "X", ">", "<"]


def berlin_label(ts: datetime) -> str:
    return f"{ts.astimezone(BERLIN):%m-%d %H:%M}"


def position_extent(entry_idx: int, exit_idx: int) -> tuple[int, int]:
    return entry_idx, max(exit_idx, entry_idx + MIN_POSITION_BARS)


def marker_offsets(markers: Sequence[Marker]) -> list[float]:
    """Horizontal offsets that put markers of the same bar side by side (0.7 bar apart)."""
    counts: dict[int, int] = {}
    for m in markers:
        counts[m.idx] = counts.get(m.idx, 0) + 1
    seen: dict[int, int] = {}
    out = []
    for m in markers:
        n, k = counts[m.idx], seen.get(m.idx, 0)
        seen[m.idx] = k + 1
        out.append(round((k - (n - 1) / 2) * 0.7, 6))
    return out


@dataclass(frozen=True, slots=True)
class Box:
    """A zone: bar range [start, end] and price range in ticks."""

    start: int
    end: int
    top: int
    bot: int
    color: str
    label: str = ""


@dataclass(frozen=True, slots=True)
class Level:
    start: int
    end: int
    price: int
    color: str
    label: str = ""
    style: Literal["-", "--", ":"] = "--"


@dataclass(frozen=True, slots=True)
class Marker:
    idx: int
    price: int
    label: str  # shown in the legend
    color: str = "#534AB7"
    shape: Shape = "o"


@dataclass(frozen=True, slots=True)
class Position:
    """Entry, stop and target from bar `start` to bar `end` (drawn at least MIN_POSITION_BARS)."""

    start: int
    end: int
    entry: int
    stop: int
    target: int


@dataclass(frozen=True, slots=True)
class ChartSpec:
    """Everything one chart shows. Bar indices refer to the full bar list."""

    first: int
    last: int
    title: str
    boxes: list[Box] = field(default_factory=list)
    levels: list[Level] = field(default_factory=list)
    markers: list[Marker] = field(default_factory=list)
    position: Position | None = None
    info: list[str] = field(default_factory=list)  # box in the top-left corner
    notes: list[str] = field(default_factory=list)  # text below the chart
    vline: int | None = None  # dashed vertical line, e.g. "now" in inspect-at


def render(spec: ChartSpec, bars: Sequence[TickBar], inst: Instrument, path: Path) -> Path:
    """Draw bars[spec.first : spec.last + 1] with overlays and save a PNG."""
    first, last = max(spec.first, 0), min(spec.last, len(bars) - 1)

    def px(ticks: int) -> float:
        return float(inst.to_price(ticks))

    fig, ax = plt.subplots(figsize=(16, 8), dpi=130)
    for i in range(first, last + 1):
        b = bars[i]
        color = UP if b.close > b.open else DOWN if b.close < b.open else NEUTRAL
        ax.vlines(i - first, px(b.low), px(b.high), color=color, linewidth=1.0, zorder=2)
        body_lo, body_hi = px(b.body_bot), px(b.body_top)
        height = max(body_hi - body_lo, 1e-9)
        ax.add_patch(Rectangle((i - first - 0.35, body_lo), 0.7, height, color=color, zorder=2))
    for box in spec.boxes:
        x0, x1 = max(box.start, first) - first - 0.5, min(box.end, last) - first + 0.5
        _shade(ax, x0, x1, px(box.bot), px(box.top), box.color, alpha=0.15, edge=1.5)
        if box.label:
            ax.text(x0, px(box.top), f" {box.label}", fontsize=9, color=box.color, va="bottom")
    for lv in spec.levels:
        x0, x1 = max(lv.start, first) - first, min(lv.end, last) - first
        ax.hlines(px(lv.price), x0, x1, colors=lv.color, linestyles=lv.style, linewidth=1.4)
        if lv.label:
            label = f"{lv.label} {px(lv.price)}"
            ax.text(x0, px(lv.price), label, fontsize=9, color=lv.color, va="bottom")
    if spec.position is not None:
        _draw_position(ax, spec.position, first, last, px)
    for mk, dx in zip(spec.markers, marker_offsets(spec.markers), strict=True):
        if first <= mk.idx <= last:
            ax.scatter(
                mk.idx - first + dx,
                px(mk.price),
                marker=mk.shape,
                s=65,
                color=mk.color,
                edgecolors="white",
                linewidths=0.8,
                zorder=5,
                label=mk.label,
            )
    if spec.vline is not None and first <= spec.vline <= last:
        ax.axvline(spec.vline - first, color=INK, linestyle="--", linewidth=1)
    # legend and info box sit right of the chart, so they never cover candles
    fig.subplots_adjust(right=0.78)
    if spec.markers:
        ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1.0), fontsize=9, framealpha=0.9)
    if spec.info:
        box_style = {"boxstyle": "round", "facecolor": "white", "alpha": 0.9, "edgecolor": "#ccc"}
        ax.text(
            1.01,
            0.72,
            "\n".join(spec.info),
            transform=ax.transAxes,
            fontsize=10,
            va="top",
            family="monospace",
            bbox=box_style,
        )
    step = max((last - first) // 12, 1)
    ticks = list(range(0, last - first + 1, step))
    ax.set_xticks(ticks)
    ax.set_xticklabels([berlin_label(bars[first + t].ts) for t in ticks], rotation=30, fontsize=9)
    ax.set_xlim(-1, last - first + 8)  # room for the price labels on the right
    ax.set_title(spec.title, fontsize=12)
    ax.set_xlabel("Europe/Berlin")
    ax.grid(alpha=0.2)
    if spec.notes:
        fig.text(0.01, 0.01, "\n".join(spec.notes), fontsize=8, va="bottom", family="monospace")
        fig.subplots_adjust(bottom=0.12 + 0.022 * len(spec.notes))
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path)
    plt.close(fig)
    return path


def _shade(
    ax: Any, x0: float, x1: float, lo: float, hi: float, color: str, alpha: float, edge: float
) -> None:
    ax.add_patch(
        Rectangle(
            (x0, min(lo, hi)),
            x1 - x0,
            abs(hi - lo),
            facecolor=color,
            alpha=alpha,
            edgecolor=color,
            linewidth=edge,
            zorder=1,
        )
    )


def _draw_position(
    ax: Any, pos: Position, first: int, last: int, px: Callable[[int], float]
) -> None:
    start, end = position_extent(pos.start, pos.end)
    x0, x1 = max(start, first) - first - 0.5, min(end, last) - first + 0.5
    entry, stop, target = px(pos.entry), px(pos.stop), px(pos.target)
    _shade(ax, x0, x1, entry, target, WIN, alpha=0.18, edge=1)
    _shade(ax, x0, x1, entry, stop, LOSS, alpha=0.18, edge=1)
    ax.hlines(entry, x0, x1, colors=INK, linewidth=1.6, zorder=3)
    for price, name, color in ((target, "TP", WIN), (entry, "Entry", INK), (stop, "SL", LOSS)):
        ax.text(x1, price, f" {name} {price}", fontsize=9, color=color, va="center", weight="bold")
