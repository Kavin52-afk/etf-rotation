"""Layer 3 execution policy for target holdings and turnover control."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd

from .selector import has_sell_signal


@dataclass(frozen=True)
class ExecutionDecision:
    """Final execution-policy output."""

    target_holdings: list[str]
    kept_positions: list[str]
    added_positions: list[str]
    removed_positions: list[str]
    final_execution_list: pd.DataFrame
    execution_confidence: float = 0.0
    confidence_threshold: float = 0.0
    confidence_blocked: bool = False


def _as_list(values: Iterable[str] | None) -> list[str]:
    """Return a clean list of holding codes."""
    return [str(item) for item in values or [] if str(item)]


def _score(row: pd.Series | None) -> float:
    """Return a candidate score with a low fallback."""
    if row is None:
        return -9999.0
    value = row.get("score", -9999.0)
    return -9999.0 if pd.isna(value) else float(value)


def _rank(row: pd.Series | None) -> int:
    """Return a momentum rank with a high fallback."""
    if row is None:
        return 9999
    value = row.get("momentum_rank", 9999)
    return 9999 if pd.isna(value) else int(value)


def _allows_hold(row: pd.Series | None) -> bool:
    """Return whether the risk overlay permits preserving an existing holding."""
    return True if row is None else bool(row.get("allow_hold", True))


def _execution_rows(yesterday: list[str], target: list[str], reason: str) -> pd.DataFrame:
    """Build a simple execution action table."""
    rows: list[dict[str, object]] = []
    for code in yesterday:
        if code not in target:
            rows.append({"code": code, "action": "REMOVE", "reason": reason})
    for code in target:
        if code not in yesterday:
            rows.append({"code": code, "action": "ADD", "reason": reason})
    for code in target:
        if code in yesterday:
            rows.append({"code": code, "action": "KEEP", "reason": "preserved"})
    return pd.DataFrame(rows, columns=["code", "action", "reason"])


def _execution_confidence(
    risk_table: pd.DataFrame,
    target: list[str],
    yesterday: list[str],
    max_hold: int,
) -> float:
    """Compute execution confidence from signal, trend, risk, and turnover."""
    if not target:
        return 0.0
    rows = risk_table[risk_table["code"].astype(str).isin(target)].copy()
    if rows.empty:
        return 0.0
    scores = pd.to_numeric(rows.get("score", pd.Series(dtype=float)), errors="coerce").fillna(0.0)
    signal_strength = min(1.0, max(0.0, float(scores.mean()) / 30.0))
    trend_consistency = rows["trend"].astype(str).eq("↗").mean() if "trend" in rows.columns else 0.5
    allow_new = rows.get("allow_new_entry", pd.Series([True] * len(rows))).fillna(False).map(bool)
    allow_hold = rows.get("allow_hold", pd.Series([True] * len(rows))).fillna(False).map(bool)
    risk_overlay_clearance = (allow_new | allow_hold).mean()
    turnover = max(len(set(target) - set(yesterday)), len(set(yesterday) - set(target)))
    turnover_penalty = turnover / max(1, max_hold)
    return float(signal_strength + trend_consistency + risk_overlay_clearance - turnover_penalty)


def _confidence_threshold(strategy: dict) -> float:
    """Return the configured real-world execution confidence threshold."""
    return float(strategy.get("realworld_execution", {}).get("confidence_threshold", 0.0))


def apply_execution_policy(
    risk_table: pd.DataFrame,
    yesterday_holdings: Iterable[str] | None,
    strategy: dict,
    max_hold: int,
) -> ExecutionDecision:
    """Apply holding inertia, replacement threshold, and max turnover rules."""
    yesterday = _as_list(yesterday_holdings)
    rebalance = strategy.get("rebalance", {})
    keep_if_rank_le = int(rebalance.get("keep_if_rank_le", 4))
    replace_margin = float(rebalance.get("replace_only_if_new_score_better_by", 3.0))
    max_changes = 1

    ranking = risk_table.copy()
    row_by_code = {str(row.code): pd.Series(row._asdict()) for row in ranking.itertuples(index=False)}

    kept: list[str] = []
    non_preserved_old: list[str] = []
    for code in yesterday:
        row = row_by_code.get(code)
        must_keep = (
            row is not None
            and _rank(row) <= keep_if_rank_le
            and not has_sell_signal(row)
            and bool(row.get("allow_hold", True))
        )
        if must_keep:
            kept.append(code)
        else:
            non_preserved_old.append(code)

    if not yesterday:
        additions = []
        for row in ranking.itertuples(index=False):
            code = str(row.code)
            if bool(getattr(row, "allow_new_entry", False)) and code not in additions:
                additions.append(code)
            if len(additions) >= max_hold:
                break
        target = additions[:max_hold]
        confidence = _execution_confidence(ranking, target, [], max_hold)
        threshold = _confidence_threshold(strategy)
        blocked = confidence < threshold
        if blocked:
            target = []
        return ExecutionDecision(
            target_holdings=target,
            kept_positions=[],
            added_positions=target,
            removed_positions=[],
            final_execution_list=_execution_rows(
                [],
                target,
                "execution_confidence_below_threshold" if blocked else "initial_entry",
            ),
            execution_confidence=confidence,
            confidence_threshold=threshold,
            confidence_blocked=blocked,
        )

    # Max one broad-ETF change per day: remove at most one non-preserved old
    # holding, and keep additional old holdings until a later day.
    removable = sorted(non_preserved_old, key=lambda code: _score(row_by_code.get(code)))
    removed = removable[:max_changes]
    retained_due_turnover = [code for code in non_preserved_old if code not in removed]
    selected = kept + retained_due_turnover
    selected = sorted(set(selected), key=lambda code: _score(row_by_code.get(code)), reverse=True)

    added: list[str] = []
    removed_score = _score(row_by_code.get(removed[0])) if removed else None
    removed_for_risk = bool(removed and not _allows_hold(row_by_code.get(removed[0])))
    for row in ranking.itertuples(index=False):
        code = str(row.code)
        if len(selected) >= max_hold or len(added) >= max_changes:
            break
        if code in selected or code in yesterday:
            continue
        if not bool(getattr(row, "allow_new_entry", False)):
            continue
        if removed_score is not None and not removed_for_risk and float(row.score) - removed_score <= replace_margin:
            continue
        selected.append(code)
        added.append(code)

    target = selected[:max_hold]
    confidence = _execution_confidence(ranking, target, yesterday, max_hold)
    threshold = _confidence_threshold(strategy)
    blocked = confidence < threshold
    if blocked:
        target = yesterday
    # If one removal failed to receive a qualifying replacement, target may be
    # below max_hold. This is intentional: replacement threshold is binding.
    removed = [code for code in yesterday if code not in target]
    added = [code for code in target if code not in yesterday]
    return ExecutionDecision(
        target_holdings=target,
        kept_positions=[code for code in target if code in yesterday],
        added_positions=added,
        removed_positions=removed,
        final_execution_list=_execution_rows(
            yesterday,
            target,
            "execution_confidence_below_threshold" if blocked else "layer3_execution_policy",
        ),
        execution_confidence=confidence,
        confidence_threshold=threshold,
        confidence_blocked=blocked,
    )
