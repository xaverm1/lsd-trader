"""Strategy parameters (Strategy Spec §9). Defaults are the primary hypothesis."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class StrategyConfig:
    piv_len: int = 1
    bos_confirm: Literal["close", "wick"] = "close"
    bos_max_bars: int | None = None
    zone_lookback: int = 20
    doji_tol_ticks: int = 0
    zone_mode: Literal["auto", "normal"] = "auto"
    extra_zones: Literal["none", "last", "all"] = "none"
    zone_kill: Literal["close_inside", "close_beyond"] = "close_inside"
    liq_max_dist_atr: float | None = None
    atr_len: int = 14
    max_bars_sweep_to_tap: int = 12  # one hour of 5-minute bars (Spec §7)
    tap_tol_ticks: int = 0
    max_bars_tap_to_entry: int = 3
    entry_trigger: Literal["bullish", "above_tap_high", "above_liq", "min_body"] = "bullish"
    min_body_ticks: int = 1
    sl_buffer_ticks: int = 0
    sl_mode: Literal["wick", "zone_bottom", "zone_mid"] = "wick"
    rr: float = 4.0
    max_trades_per_zone: int = 1

    def __post_init__(self) -> None:
        if self.piv_len < 1:
            raise ValueError("piv_len must be >= 1")
        if self.bos_max_bars is not None and self.bos_max_bars < 1:
            raise ValueError("bos_max_bars must be >= 1 or None")
        if self.zone_lookback < 1:
            raise ValueError("zone_lookback must be >= 1")
        if self.atr_len < 1:
            raise ValueError("atr_len must be >= 1")
        if self.liq_max_dist_atr is not None and self.liq_max_dist_atr <= 0:
            raise ValueError("liq_max_dist_atr must be > 0 or None")
        for name in (
            "doji_tol_ticks",
            "max_bars_sweep_to_tap",
            "tap_tol_ticks",
            "max_bars_tap_to_entry",
            "sl_buffer_ticks",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be >= 0")
        if self.min_body_ticks < 1:
            raise ValueError("min_body_ticks must be >= 1")
        if self.rr <= 0:
            raise ValueError("rr must be > 0")
        if self.max_trades_per_zone < 1:
            raise ValueError("max_trades_per_zone must be >= 1")
