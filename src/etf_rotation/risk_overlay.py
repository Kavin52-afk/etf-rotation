"""Layer 2 rule-based risk overlay for ETF rotation candidates."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .indicators import DOWN, WEAK
from .selector import overheat_take_profit


@dataclass(frozen=True)
class RiskState:
    """Risk permissions for a single ETF candidate."""

    allow_new_entry: bool
    allow_hold: bool
    allow_exit: bool
    reason: str


def evaluate_risk_state(row: pd.Series, strategy: dict) -> RiskState:
    """Evaluate rule-based risk permissions for one ranked candidate."""
    score_cfg = strategy.get("score", {})
    overheat_threshold = float(score_cfg.get("overheat_bias_threshold", 12.0))
    extreme_overheat_threshold = float(score_cfg.get("extreme_overheat_bias_threshold", 18.0))
    qdii_premium_block = 1 + float(score_cfg.get("qdii_premium_block", 8.0)) / 100

    reasons: list[str] = []
    allow_new_entry = True
    allow_hold = True
    allow_exit = True

    market_signal = str(row.get("market_signal", ""))
    if market_signal == WEAK:
        allow_new_entry = False
        reasons.append("MARKET_SIGNAL_WEAK")

    bias = pd.to_numeric(pd.Series([row.get("bias_pct")]), errors="coerce").iloc[0]
    overheat = pd.notna(bias) and float(bias) > overheat_threshold
    if overheat:
        allow_new_entry = False
        reasons.append("OVERHEAT")
        if overheat_take_profit(row, strategy):
            allow_hold = False
            reasons.append("TAKE_PROFIT_OVERHEAT")
        if float(bias) > extreme_overheat_threshold:
            allow_hold = False
            reasons.append("EXTREME_OVERHEAT")

    premium_pb = pd.to_numeric(pd.Series([row.get("premium_pb", 1.0)]), errors="coerce").fillna(1.0).iloc[0]
    if bool(row.get("qdii", False)) and float(premium_pb) > qdii_premium_block:
        allow_new_entry = False
        reasons.append("BLOCK_NEW_ENTRY_QDII_PREMIUM")

    if row.get("trend") == DOWN:
        allow_new_entry = False
        reasons.append("TREND_DOWN_EXISTING_ONLY")

    return RiskState(
        allow_new_entry=allow_new_entry,
        allow_hold=allow_hold,
        allow_exit=allow_exit,
        reason="|".join(reasons) if reasons else "OK",
    )


def apply_risk_overlay(candidates: pd.DataFrame, strategy: dict) -> pd.DataFrame:
    """Apply Layer 2 risk overlay to a ranking table."""
    if candidates.empty:
        return candidates.copy()
    rows = []
    for _, row in candidates.iterrows():
        state = evaluate_risk_state(row, strategy)
        rows.append(
            {
                "code": row.get("code"),
                "allow_new_entry": state.allow_new_entry,
                "allow_hold": state.allow_hold,
                "allow_exit": state.allow_exit,
                "risk_reason": state.reason,
                "OVERHEAT": "OVERHEAT" in state.reason,
                "BLOCK_NEW_ENTRY": "BLOCK_NEW_ENTRY" in state.reason,
            }
        )
    risk = pd.DataFrame(rows)
    return candidates.merge(risk, on="code", how="left")


def risk_filtered_new_entries(risk_table: pd.DataFrame) -> pd.DataFrame:
    """Return candidates allowed for new entry after risk overlay."""
    if risk_table.empty:
        return risk_table.copy()
    return risk_table[risk_table["allow_new_entry"].fillna(False)].copy()
