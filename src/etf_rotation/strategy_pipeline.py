"""Three-layer ETF rotation decision pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd

from .execution_policy import ExecutionDecision, apply_execution_policy
from .risk_overlay import apply_risk_overlay, risk_filtered_new_entries
from .selector import rank_candidates


@dataclass(frozen=True)
class StrategyPipelineResult:
    """Output of the three-layer decision pipeline."""

    target_holdings: list[str]
    risk_filtered_candidates: pd.DataFrame
    final_execution_list: pd.DataFrame
    layer1_candidates: pd.DataFrame
    layer2_candidates: pd.DataFrame
    execution_decision: ExecutionDecision


def run_strategy_pipeline(
    features: pd.DataFrame,
    yesterday_holdings: Iterable[str] | None,
    config: dict,
    max_hold: int | None = None,
) -> StrategyPipelineResult:
    """Run selector, risk overlay, and execution policy for one date."""
    max_hold_value = int(max_hold or config.get("max_hold_broad", 2))
    layer1_candidates = rank_candidates(features, config, yesterday_holdings)
    layer2_candidates = apply_risk_overlay(layer1_candidates, config)
    risk_filtered = risk_filtered_new_entries(layer2_candidates)
    execution = apply_execution_policy(layer2_candidates, yesterday_holdings, config, max_hold_value)
    return StrategyPipelineResult(
        target_holdings=execution.target_holdings,
        risk_filtered_candidates=risk_filtered,
        final_execution_list=execution.final_execution_list,
        layer1_candidates=layer1_candidates,
        layer2_candidates=layer2_candidates,
        execution_decision=execution,
    )


def layer1_targets(layer1_candidates: pd.DataFrame, max_hold: int) -> list[str]:
    """Return raw Layer 1 top targets from candidate score ranking."""
    if layer1_candidates.empty:
        return []
    return layer1_candidates.head(max_hold)["code"].astype(str).tolist()


def layer2_targets(layer2_candidates: pd.DataFrame, max_hold: int) -> list[str]:
    """Return Layer 2 top targets after new-entry risk filtering."""
    if layer2_candidates.empty:
        return []
    filtered = risk_filtered_new_entries(layer2_candidates)
    return filtered.head(max_hold)["code"].astype(str).tolist()
