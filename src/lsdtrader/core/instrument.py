"""Contract specifications and price <-> tick conversion."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal


@dataclass(frozen=True, slots=True)
class Instrument:
    root: str
    tick_size: Decimal
    tick_value: float  # USD per tick per contract
    commission_per_side: float  # USD per contract per side
    slippage_ticks: int = 1
    spread_ticks: int = 0  # CFDs: bid/ask spread paid once per trade (bars are bid prices)

    def to_ticks(self, price: float | Decimal | str) -> int:
        """Exact tick count of a price; raises if the price is off the tick grid."""
        q = Decimal(str(price)) / self.tick_size
        ticks = q.to_integral_value(rounding=ROUND_HALF_EVEN)
        if abs(q - ticks) > Decimal("1e-6"):
            raise ValueError(f"{price} is not on the {self.tick_size} grid of {self.root}")
        return int(ticks)

    def to_price(self, ticks: int) -> Decimal:
        return ticks * self.tick_size


def _spec(root: str, tick: str, value: float, commission: float) -> Instrument:
    return Instrument(root, Decimal(tick), value, commission)


def _cfd(root: str, spread: str) -> Instrument:
    """CFD quoted to 0.001, one unit per 'contract', cost = spread only."""
    tick = Decimal("0.001")
    return Instrument(root, tick, float(tick), 0.0, 0, int(Decimal(spread) / tick))


# Commissions are PLACEHOLDERS until the prop firm / broker is chosen (Strategy Spec §12).
INSTRUMENTS: dict[str, Instrument] = {
    i.root: i
    for i in (
        _spec("ES", "0.25", 12.50, 2.50),
        _spec("NQ", "0.25", 5.00, 2.50),
        _spec("YM", "1", 5.00, 2.50),
        _spec("RTY", "0.1", 5.00, 2.50),
        _spec("GC", "0.1", 10.00, 2.50),
        _spec("SI", "0.005", 25.00, 2.50),
        _spec("CL", "0.01", 10.00, 2.50),
        _spec("MES", "0.25", 1.25, 1.24),
        _spec("MNQ", "0.25", 0.50, 1.24),
        _spec("MYM", "1", 0.50, 1.24),
        _spec("M2K", "0.1", 0.50, 1.24),
        _spec("MGC", "0.1", 1.00, 1.24),
        _spec("SIL", "0.005", 5.00, 1.24),
        _spec("MCL", "0.01", 1.00, 1.24),
        # CFDs (HistData / Dukascopy). Spreads are PLACEHOLDERS for typical retail quotes.
        _cfd("SPXUSD", "0.4"),
        _cfd("NSXUSD", "1.0"),
        _cfd("XAUUSD", "0.25"),
        _cfd("XAGUSD", "0.02"),
        _cfd("WTIUSD", "0.03"),
    )
}

# Other names for the same CFD (Dukascopy symbols).
ALIASES = {
    "USA500IDXUSD": "SPXUSD",
    "USATECHIDXUSD": "NSXUSD",
    "LIGHTCMDUSD": "WTIUSD",
}


def get_instrument(root: str) -> Instrument:
    try:
        key = root.upper().replace(".", "").replace("/", "")
        return INSTRUMENTS[ALIASES.get(key, key)]
    except KeyError:
        raise KeyError(f"unknown instrument {root!r}; known: {sorted(INSTRUMENTS)}") from None
