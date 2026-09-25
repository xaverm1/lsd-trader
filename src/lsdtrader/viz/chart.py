"""Candlestick charts with strategy overlays (Design §8), rendered to PNG with matplotlib."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import matplotlib

matplotlib.use("Agg")  # no display needed
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

from lsdtrader.core.bar import TickBar  # noqa: E402
from lsdtrader.core.instrument import Instrument  # noqa: E402

UP, DOWN = "#1D9E75", "#D85A30"


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
    label: str
    color: str = "#534AB7"


@dataclass(frozen=True, slots=True)
class ChartSpec:
    """Everything one chart shows. Bar indices refer to the full bar list."""

    first: int
    last: int
    title: str
    boxes: list[Box] = field(default_factory=list)
    levels: list[Level] = field(default_factory=list)
    markers: list[Marker] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def render(spec: ChartSpec, bars: Sequence[TickBar], inst: Instrument, path: Path) -> Path:
    """Draw bars[spec.first : spec.last + 1] with overlays and save a PNG."""
    first, last = max(spec.first, 0), min(spec.last, len(bars) - 1)

    def px(ticks: int) -> float:
        return float(inst.to_price(ticks))

    fig, ax = plt.subplots(figsize=(14, 7), dpi=110)
    for i in range(first, last + 1):
        b = bars[i]
        x = i - first
        color = UP if b.close > b.open else DOWN if b.close < b.open else "#888780"
        ax.vlines(x, px(b.low), px(b.high), color=color, linewidth=0.8)
        body_lo, body_hi = px(b.body_bot), px(b.body_top)
        ax.add_patch(Rectangle((x - 0.35, body_lo), 0.7, max(body_hi - body_lo, 1e-9), color=color))
    for box in spec.boxes:
        x0, x1 = max(box.start, first) - first - 0.5, min(box.end, last) - first + 0.5
        ax.add_patch(
            Rectangle(
                (x0, px(box.bot)),
                x1 - x0,
                px(box.top) - px(box.bot),
                facecolor=box.color,
                alpha=0.18,
                edgecolor=box.color,
                linewidth=1,
            )
        )
        if box.label:
            ax.text(x0, px(box.top), box.label, fontsize=8, color=box.color, va="bottom")
    for lv in spec.levels:
        x0, x1 = max(lv.start, first) - first, min(lv.end, last) - first
        ax.hlines(px(lv.price), x0, x1, colors=lv.color, linestyles=lv.style, linewidth=1.2)
        if lv.label:
            ax.text(x1, px(lv.price), f" {lv.label}", fontsize=8, color=lv.color, va="center")
    for mk in spec.markers:
        if first <= mk.idx <= last:
            ax.plot(mk.idx - first, px(mk.price), "o", color=mk.color, markersize=5)
            ax.annotate(
                mk.label,
                (mk.idx - first, px(mk.price)),
                fontsize=8,
                color=mk.color,
                xytext=(4, 4),
                textcoords="offset points",
            )
    step = max((last - first) // 10, 1)
    ticks = list(range(0, last - first + 1, step))
    ax.set_xticks(ticks)
    ax.set_xticklabels(
        [f"{bars[first + t].ts:%m-%d %H:%M}" for t in ticks], rotation=30, fontsize=8
    )
    ax.set_xlim(-1, last - first + 1)
    ax.set_title(spec.title, fontsize=11)
    ax.set_xlabel("UTC")
    ax.grid(alpha=0.2)
    if spec.notes:
        fig.text(0.01, 0.01, "\n".join(spec.notes), fontsize=8, va="bottom", family="monospace")
        fig.subplots_adjust(bottom=0.12 + 0.025 * len(spec.notes))
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path)
    plt.close(fig)
    return path
