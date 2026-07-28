"""Stability controls for real-world ETF decision execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd


@dataclass(frozen=True)
class StabilityDecision:
    """Result of applying stability controls to one signal."""

    target_holdings: list[str]
    ignored_signals: list[str]
    max_changes_allowed: int
    volatility_guard_active: bool


def _as_list(values: Iterable[str] | None) -> list[str]:
    """Return a clean list of codes."""
    return [str(item) for item in values or [] if str(item)]


def signal_changed(left: Iterable[str] | None, right: Iterable[str] | None) -> bool:
    """Return whether two holding signals differ as sets."""
    return set(_as_list(left)) != set(_as_list(right))


def apply_signal_debounce(
    signal_date: pd.Timestamp,
    proposed_holdings: Iterable[str],
    signal_history: dict[pd.Timestamp, list[str]],
    debounce_days: int = 2,
) -> tuple[list[str], list[str]]:
    """Ignore a proposed signal if the previous signal changed within N days."""
    proposed = _as_list(proposed_holdings)
    current_date = pd.Timestamp(signal_date).normalize()
    prior_dates = sorted(pd.Timestamp(dt).normalize() for dt in signal_history if pd.Timestamp(dt).normalize() < current_date)
    if not prior_dates:
        return proposed, []
    last_date = prior_dates[-1]
    last_signal = _as_list(signal_history[last_date])
    if signal_changed(last_signal, proposed) and (current_date - last_date).days <= debounce_days:
        return last_signal, [f"signal_debounce: ignored change within {debounce_days} days of {last_date.date()}"]
    return proposed, []


def enforce_churn_control(
    current_holdings: Iterable[str],
    proposed_holdings: Iterable[str],
    max_changes: int = 1,
) -> tuple[list[str], list[str]]:
    """Limit broad ETF turnover to at most ``max_changes`` additions/removals."""
    current = _as_list(current_holdings)
    proposed = _as_list(proposed_holdings)
    current_set = set(current)
    proposed_set = set(proposed)
    additions = [code for code in proposed if code not in current_set]
    removals = [code for code in current if code not in proposed_set]
    change_count = max(len(additions), len(removals))
    if change_count <= max_changes:
        return proposed, []

    target = [code for code in current if code not in removals[max_changes:]]
    for code in additions[:max_changes]:
        if code not in target:
            target.append(code)
    target = target[: max(len(current), len(proposed))]
    return target, [f"churn_control: capped changes from {change_count} to {max_changes}"]


def portfolio_volatility_guard(
    prices: pd.DataFrame,
    holdings: Iterable[str],
    as_of: pd.Timestamp,
    lookback: int = 20,
    spike_multiplier: float = 1.5,
) -> tuple[bool, float, float]:
    """Detect whether recent portfolio volatility is elevated.

    The guard is deterministic and uses only prices on or before ``as_of``.
    """
    codes = set(_as_list(holdings))
    if not codes or prices.empty:
        return False, 0.0, 0.0
    frame = prices[prices["code"].isin(codes)].copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    frame = frame[frame["date"] <= pd.Timestamp(as_of).normalize()]
    if frame.empty:
        return False, 0.0, 0.0
    pivot = frame.pivot_table(index="date", columns="code", values="close").sort_index()
    returns = pivot.pct_change().dropna(how="all")
    if len(returns) < lookback:
        return False, 0.0, 0.0
    portfolio_returns = returns.mean(axis=1)
    rolling_vol = portfolio_returns.rolling(lookback, min_periods=lookback).std()
    current_vol = float(rolling_vol.iloc[-1]) if pd.notna(rolling_vol.iloc[-1]) else 0.0
    baseline = float(rolling_vol.dropna().median()) if not rolling_vol.dropna().empty else 0.0
    active = bool(baseline > 0 and current_vol > baseline * spike_multiplier)
    return active, current_vol, baseline


def apply_stability_controls(
    signal_date: pd.Timestamp,
    current_holdings: Iterable[str],
    proposed_holdings: Iterable[str],
    signal_history: dict[pd.Timestamp, list[str]],
    prices: pd.DataFrame | None = None,
    max_changes: int = 1,
) -> StabilityDecision:
    """Apply debounce, churn control, and volatility guard in order."""
    target, ignored = apply_signal_debounce(signal_date, proposed_holdings, signal_history)
    target, churn_ignored = enforce_churn_control(current_holdings, target, max_changes=max_changes)
    ignored.extend(churn_ignored)
    guard_active = False
    if prices is not None:
        guard_active, current_vol, baseline_vol = portfolio_volatility_guard(prices, current_holdings, signal_date)
        if guard_active and signal_changed(current_holdings, target):
            target = _as_list(current_holdings)
            ignored.append(
                "volatility_guard: suppressed turnover "
                f"(current_vol={current_vol:.6f}, baseline_vol={baseline_vol:.6f})"
            )
    return StabilityDecision(target, ignored, max_changes, guard_active)
