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
    # close_inside: a close inside the zone or a wick below it; close_beyond: a close below it;
    # wick_beyond: any trade below the zone (a close below included), checked every minute in
    # the 1-minute entry modes
    zone_kill: Literal["close_inside", "close_beyond", "wick_beyond"] = "close_inside"
    liq_max_dist_atr: float | None = None
    # any: every unswept swing low above a left zone is liquidity for it; nearest: only the one
    # closest to the zone (no other open swing low formed after the zone origin in between)
    liq_rule: Literal["any", "nearest"] = "any"
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
    # "bar": entry on the close of a strategy bar (Spec §7). "reclaim_1m": after a tap bar has
    # closed, entry on the close of the first 1-minute bar back beyond the swept liquidity.
    # "sweep_1m_cisd": zones and liquidity from the strategy bars, but sweep, tap and entry on
    # 1-minute bars; entry on the first minute after the tap that closes beyond the swept
    # liquidity and beyond the CISD level.
    # "absorption_1m": like sweep_1m_cisd, but after the tap a buying-absorption minute (volume
    # score >= absorb_min and a long lower wick, as the TradingView "Absorption Bubbles") arms
    # the setup; entry on the first later minute closing above that minute's high, within
    # absorb_wait_min minutes. A lower low disarms; a new absorption minute re-arms.
    entry_mode: Literal["bar", "reclaim_1m", "sweep_1m_cisd", "absorption_1m"] = "bar"
    absorb_min: float = 1.3  # volume / stdev(volume, absorb_len), population stdev
    absorb_len: int = 100
    absorb_wait_min: int = 15
    stop_ref: Literal["extreme", "absorption"] = "extreme"  # absorption_1m: stop at the lowest
    # low since the sweep, or at the low of the absorption minute

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
