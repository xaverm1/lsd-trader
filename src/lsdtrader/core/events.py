"""Named rule events: every rejected or killed object leaves one."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Event:
    bar_index: int
    kind: str
    detail: dict[str, object] = field(default_factory=dict)
    side: str = ""


class EventLog:
    """Collects events; the engine sets `bar_index` before processing each bar."""

    def __init__(self) -> None:
        self.events: list[Event] = []
        self.bar_index = -1

    def emit(self, kind: str, **detail: object) -> None:
        self.events.append(Event(self.bar_index, kind, dict(detail)))

    def kinds(self) -> list[str]:
        return [e.kind for e in self.events]

    def drain(self) -> list[Event]:
        out, self.events = self.events, []
        return out
