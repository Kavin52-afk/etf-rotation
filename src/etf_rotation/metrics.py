"""Performance and calibration metrics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class PerformanceSummary:
    """Backtest performance summary."""

    nav: float
    control_nav: float
    annual_return: float
    control_annual_return: float
    max_drawdown: float
    control_max_drawdown: float
    current_drawdown: float
    control_current_drawdown: float
    sharpe: float
    control_sharpe: float
    trade_count: int
    observation_days: int
    yearly_returns: dict[str, float]
    control_yearly_returns: dict[str, float]


def annualized_return(nav: float, periods: int, annual_days: int) -> float:
    """Compute annualized return in percentage scale."""
    if periods <= 0 or nav <= 0:
        return 0.0
    return (nav ** (annual_days / periods) - 1) * 100


def sharpe_ratio(returns: pd.Series, annual_days: int) -> float:
    """Compute annualized Sharpe ratio using zero risk-free rate."""
    clean = pd.to_numeric(returns, errors="coerce").dropna()
    if clean.empty or clean.std(ddof=0) == 0:
        return 0.0
    return float(clean.mean() / clean.std(ddof=0) * np.sqrt(annual_days))


def drawdown(nav: pd.Series) -> pd.Series:
    """Compute drawdown in percentage scale."""
    clean = pd.to_numeric(nav, errors="coerce")
    peak = clean.cummax()
    return (clean / peak - 1) * 100


def yearly_returns(nav_df: pd.DataFrame, nav_col: str) -> dict[str, float]:
    """Compute calendar-year returns from a NAV table."""
    if nav_df.empty:
        return {}
    df = nav_df[["date", nav_col]].dropna().copy()
    df["year"] = pd.to_datetime(df["date"]).dt.year.astype(str)
    result: dict[str, float] = {}
    for year, group in df.groupby("year"):
        first = float(group[nav_col].iloc[0])
        last = float(group[nav_col].iloc[-1])
        result[year] = (last / first - 1) * 100 if first else 0.0
    return result


def summarize_performance(nav_df: pd.DataFrame, trade_count: int, annual_days: int) -> PerformanceSummary:
    """Create a performance summary from the backtest NAV table."""
    if nav_df.empty:
        return PerformanceSummary(1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0, 0, {}, {})
    nav = float(nav_df["nav"].iloc[-1])
    control_nav = float(nav_df["control_nav"].iloc[-1])
    periods = len(nav_df)
    dd = drawdown(nav_df["nav"])
    control_dd = drawdown(nav_df["control_nav"])
    return PerformanceSummary(
        nav=nav,
        control_nav=control_nav,
        annual_return=annualized_return(nav, periods, annual_days),
        control_annual_return=annualized_return(control_nav, periods, annual_days),
        max_drawdown=float(dd.min()),
        control_max_drawdown=float(control_dd.min()),
        current_drawdown=float(dd.iloc[-1]),
        control_current_drawdown=float(control_dd.iloc[-1]),
        sharpe=sharpe_ratio(nav_df["daily_return"], annual_days),
        control_sharpe=sharpe_ratio(nav_df["control_daily_return"], annual_days),
        trade_count=trade_count,
        observation_days=periods,
        yearly_returns=yearly_returns(nav_df, "nav"),
        control_yearly_returns=yearly_returns(nav_df, "control_nav"),
    )


def exact_match(expected: Iterable[str], actual: Iterable[str]) -> bool:
    """Return whether two holdings sets match exactly, ignoring order."""
    return set(expected) == set(actual)


def hit_ratio(expected: Iterable[str], actual: Iterable[str]) -> float:
    """Compute target holding hit ratio against expected holdings."""
    expected_set = set(expected)
    if not expected_set:
        return 1.0
    return len(expected_set & set(actual)) / len(expected_set)


def turnover_diff(yesterday_expected: Iterable[str], expected: Iterable[str], actual: Iterable[str]) -> int:
    """Compute an approximate turnover difference against the original target."""
    original_turnover = len(set(yesterday_expected) ^ set(expected))
    actual_turnover = len(set(yesterday_expected) ^ set(actual))
    return actual_turnover - original_turnover


def _holding_sets(history: Iterable[Iterable[str]]) -> list[set[str]]:
    """Normalize a holding-history iterable into sets."""
    return [{str(item) for item in holdings if str(item)} for holdings in history]


def _set_distance(left: set[str], right: set[str]) -> float:
    """Return Jaccard distance for two holding sets."""
    if not left and not right:
        return 0.0
    union = left | right
    return 1.0 - len(left & right) / len(union) if union else 0.0


def strategy_stability_score(holding_history: Iterable[Iterable[str]], max_hold: int = 2) -> float:
    """Score signal stability from volatility, turnover, and position flips.

    Higher is more stable. Inputs are target holdings in chronological order.
    This metric does not use returns or future labels.
    """
    sets = _holding_sets(holding_history)
    if len(sets) <= 1:
        return 100.0
    changes = [_set_distance(prev, curr) for prev, curr in zip(sets[:-1], sets[1:], strict=False)]
    signal_volatility = sum(changes) / len(changes)
    denom = max(1, int(max_hold))
    turnover_rate = sum(len(prev ^ curr) / denom for prev, curr in zip(sets[:-1], sets[1:], strict=False)) / len(changes)
    flips = 0
    opportunities = 0
    for idx in range(2, len(sets)):
        opportunities += 1
        if sets[idx] == sets[idx - 2] and sets[idx] != sets[idx - 1]:
            flips += 1
    position_flip_frequency = flips / opportunities if opportunities else 0.0
    instability = 0.4 * signal_volatility + 0.4 * min(1.0, turnover_rate) + 0.2 * position_flip_frequency
    return max(0.0, min(100.0, (1.0 - instability) * 100))


def execution_reliability_score(executions: pd.DataFrame) -> float:
    """Score signal-to-execution consistency for delayed execution records.

    Expected columns are ``signal_date``, ``execution_date``, ``signal_target``,
    and ``executed_target``. Missing or empty records are treated as fully
    reliable because there is no executed action to contradict a signal.
    """
    if executions.empty:
        return 100.0
    frame = executions.copy()
    mismatch_count = 0
    delay_violations = 0
    for row in frame.itertuples(index=False):
        signal_target = set(str(getattr(row, "signal_target", "")).split("|")) - {""}
        executed_target = set(str(getattr(row, "executed_target", "")).split("|")) - {""}
        if signal_target != executed_target:
            mismatch_count += 1
        signal_date = pd.Timestamp(getattr(row, "signal_date")).normalize()
        execution_date = pd.Timestamp(getattr(row, "execution_date")).normalize()
        if execution_date <= signal_date:
            delay_violations += 1
    mismatch_rate = mismatch_count / len(frame)
    delay_violation_rate = delay_violations / len(frame)
    return max(0.0, min(100.0, (1.0 - 0.6 * mismatch_rate - 0.4 * delay_violation_rate) * 100))


def real_world_fidelity_score(records: pd.DataFrame) -> float:
    """Score conformance to T+1 execution, risk priority, and hold inertia."""
    if records.empty:
        return 100.0
    frame = records.copy()
    required = ["t_plus_one", "risk_priority", "hold_inertia"]
    for column in required:
        if column not in frame.columns:
            frame[column] = True
    t_plus_one = frame["t_plus_one"].map(bool).mean()
    risk_priority = frame["risk_priority"].map(bool).mean()
    hold_inertia = frame["hold_inertia"].map(bool).mean()
    return max(0.0, min(100.0, (0.4 * t_plus_one + 0.35 * risk_priority + 0.25 * hold_inertia) * 100))
