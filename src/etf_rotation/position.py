"""Position-control rules for the research strategy."""

from __future__ import annotations

import pandas as pd

from .indicators import UP


def determine_control_position(
    drawdown_pct: float,
    target_features: pd.DataFrame,
    previous_scale: float,
    is_new_high: bool,
    strategy: dict,
) -> tuple[float, str]:
    """Determine half/full position scale from drawdown and target trends."""
    cfg = strategy.get("position_control", {})
    default = float(cfg.get("default_position", 0.5))
    full = float(cfg.get("full_position", 1.0))
    add_dd = float(cfg.get("add_when_drawdown_below", -4.0))
    reduce_dd = float(cfg.get("reduce_when_drawdown_below", -12.0))
    target_trends = target_features["trend"].tolist() if not target_features.empty else []
    up_count = sum(1 for trend in target_trends if trend == UP)

    if bool(cfg.get("half_when_new_high", True)) and is_new_high:
        return default, "现在半仓"
    if drawdown_pct <= reduce_dd and up_count < len(target_trends) / 2:
        return default, "现在半仓"
    if drawdown_pct <= add_dd and up_count >= 1:
        return full, "现在满仓"
    scale = previous_scale if previous_scale else default
    label = "现在满仓" if scale >= full else "现在半仓"
    return scale, label


def equal_weights(codes: list[str], total_weight: float) -> dict[str, float]:
    """Return equal weights for target ETF codes."""
    if not codes or total_weight <= 0:
        return {}
    weight = total_weight / len(codes)
    return {code: weight for code in codes}


def weight_delta(before: dict[str, float], after: dict[str, float]) -> dict[str, float]:
    """Return after-before weight changes for all touched codes."""
    codes = set(before) | set(after)
    return {code: after.get(code, 0.0) - before.get(code, 0.0) for code in codes}
