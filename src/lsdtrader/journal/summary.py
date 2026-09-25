"""Descriptive statistics of a run. No verdict: that is sub-project 3."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from lsdtrader.core.events import Event
from lsdtrader.execution.broker import Trade


@dataclass(frozen=True, slots=True)
class Summary:
    n: int
    wins: int
    win_rate: float
    total_net_r: float
    avg_net_r: float
    avg_gross_r: float
    avg_cost_r: float
    longest_losing_streak: int
    exits: dict[str, int]


def summarize(trades: Sequence[Trade]) -> Summary:
    n = len(trades)
    wins = sum(1 for t in trades if t.net_r > 0)
    streak = longest = 0
    for t in sorted(trades, key=lambda t: t.exit_ts):
        streak = streak + 1 if t.net_r <= 0 else 0
        longest = max(longest, streak)

    def avg(values: list[float]) -> float:
        return sum(values) / n if n else 0.0

    return Summary(
        n=n,
        wins=wins,
        win_rate=wins / n if n else 0.0,
        total_net_r=sum(t.net_r for t in trades),
        avg_net_r=avg([t.net_r for t in trades]),
        avg_gross_r=avg([t.gross_r for t in trades]),
        avg_cost_r=avg([t.cost_r for t in trades]),
        longest_losing_streak=longest,
        exits=dict(Counter(t.exit_reason for t in trades)),
    )


def render_markdown(title: str, summary: Summary, n_bars: int, events: Sequence[Event]) -> str:
    s = summary
    exits = ", ".join(f"{k}: {v}" for k, v in sorted(s.exits.items())) or "-"
    lines = [
        f"# {title}",
        "",
        "Descriptive only. Whether this is an edge is decided in sub-project 3.",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Bars | {n_bars} |",
        f"| Trades (N) | {s.n} |",
        f"| Win rate | {s.win_rate:.1%} |",
        f"| Total net R | {s.total_net_r:+.2f} |",
        f"| Avg net R | {s.avg_net_r:+.3f} |",
        f"| Avg gross R | {s.avg_gross_r:+.3f} |",
        f"| Avg cost R | {s.avg_cost_r:.3f} |",
        f"| Longest losing streak | {s.longest_losing_streak} |",
        f"| Exits | {exits} |",
        "",
        "## Top events",
        "",
        "| Event | Count |",
        "|---|---|",
    ]
    for kind, count in Counter(e.kind for e in events).most_common(15):
        lines.append(f"| {kind} | {count} |")
    return "\n".join(lines) + "\n"
