"""Real-world execution layer for stable ETF decision workflows."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Iterable

import pandas as pd

from .backtest import prepare_features
from .config import ProjectConfig
from .metrics import (
    execution_reliability_score,
    real_world_fidelity_score,
    strategy_stability_score,
)
from .stability_controller import apply_stability_controls
from .strategy_pipeline import run_strategy_pipeline
from .universe import etf_maps, names_for_codes
from .utils import ensure_dir, float_fmt, to_pipe_list


@dataclass(frozen=True)
class SignalState:
    """Frozen post-close signal state."""

    frozen_signal: list[str]
    timestamp: str
    source_features_hash: str
    signal_date: str


@dataclass(frozen=True)
class FreezeResult:
    """Result of freezing or loading a frozen signal."""

    state: SignalState
    is_new: bool
    hash_changed: bool
    message: str


@dataclass(frozen=True)
class ExecutionPlan:
    """T+1 open execution plan."""

    signal_date: str
    execution_date: str
    frozen_signal: list[str]
    current_holdings: list[str]
    actions: list[dict[str, str]]
    allowed: bool
    reason: str


@dataclass(frozen=True)
class TradeConflict:
    """Detected execution conflict and deterministic resolution."""

    conflict_type: str
    detail: str
    priority: str
    resolution: str


def _as_list(values: Iterable[str] | None) -> list[str]:
    """Return a clean list of holding codes."""
    return [str(item) for item in values or [] if str(item)]


def source_features_hash(features: pd.DataFrame) -> str:
    """Hash the source feature snapshot used to create a signal."""
    if features.empty:
        return hashlib.sha256(b"empty").hexdigest()
    columns = [
        col
        for col in [
            "date",
            "code",
            "ret20_pct",
            "bias_pct",
            "trend",
            "market_signal",
            "convex",
            "latest_signal",
            "last_signal",
            "premium_pb",
            "score",
            "allow_new_entry",
            "allow_hold",
            "risk_reason",
        ]
        if col in features.columns
    ]
    snapshot = features[columns].copy().sort_values([col for col in ["date", "code"] if col in columns])
    payload = snapshot.to_json(orient="records", date_format="iso", force_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _state_path(state_dir: Path, signal_date: pd.Timestamp) -> Path:
    """Return the frozen-signal JSON path for a date."""
    return state_dir / f"{pd.Timestamp(signal_date).strftime('%Y-%m-%d')}.json"


def _read_state(path: Path) -> SignalState:
    """Read a frozen signal from disk."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return SignalState(
        frozen_signal=[str(item) for item in data.get("frozen_signal", [])],
        timestamp=str(data.get("timestamp", "")),
        source_features_hash=str(data.get("source_features_hash", "")),
        signal_date=str(data.get("signal_date", "")),
    )


def freeze_signal(
    signal_date: pd.Timestamp,
    proposed_signal: Iterable[str],
    source_features: pd.DataFrame,
    state_dir: Path | None = None,
    persist: bool = True,
) -> FreezeResult:
    """Freeze a daily signal and reject intraday mutations for the same date."""
    date_value = pd.Timestamp(signal_date).normalize()
    feature_hash = source_features_hash(source_features)
    if state_dir is not None:
        ensure_dir(state_dir)
        path = _state_path(state_dir, date_value)
        if persist and path.exists():
            existing = _read_state(path)
            hash_changed = existing.source_features_hash != feature_hash
            message = "loaded existing frozen signal"
            if hash_changed:
                message = "loaded existing frozen signal; ignored intraday feature change"
            return FreezeResult(existing, is_new=False, hash_changed=hash_changed, message=message)

    state = SignalState(
        frozen_signal=_as_list(proposed_signal),
        timestamp=datetime.now(timezone.utc).isoformat(),
        source_features_hash=feature_hash,
        signal_date=date_value.strftime("%Y-%m-%d"),
    )
    if persist and state_dir is not None:
        _state_path(state_dir, date_value).write_text(
            json.dumps(asdict(state), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return FreezeResult(state, is_new=True, hash_changed=False, message="created frozen signal")


def next_execution_date(signal_date: pd.Timestamp, trading_dates: Iterable[pd.Timestamp]) -> pd.Timestamp:
    """Return the next trading date after the signal date, falling back to next business day."""
    date_value = pd.Timestamp(signal_date).normalize()
    future = sorted(pd.Timestamp(dt).normalize() for dt in trading_dates if pd.Timestamp(dt).normalize() > date_value)
    if future:
        return future[0]
    return pd.bdate_range(date_value + pd.Timedelta(days=1), periods=1)[0].normalize()


def build_execution_plan(
    state: SignalState,
    current_holdings: Iterable[str],
    trading_dates: Iterable[pd.Timestamp],
) -> ExecutionPlan:
    """Build a T+1-only execution plan from a frozen signal."""
    signal_date = pd.Timestamp(state.signal_date).normalize()
    execution_date = next_execution_date(signal_date, trading_dates)
    current = _as_list(current_holdings)
    target = _as_list(state.frozen_signal)
    actions: list[dict[str, str]] = []
    for code in current:
        if code not in target:
            actions.append({"code": code, "action": "SELL", "reason": "T+1_open_rebalance"})
    for code in target:
        if code not in current:
            actions.append({"code": code, "action": "BUY", "reason": "T+1_open_rebalance"})
    allowed = execution_date > signal_date
    reason = "T+1 open only" if allowed else "blocked: execution date must be after signal date"
    return ExecutionPlan(
        signal_date=signal_date.strftime("%Y-%m-%d"),
        execution_date=pd.Timestamp(execution_date).strftime("%Y-%m-%d"),
        frozen_signal=target,
        current_holdings=current,
        actions=actions,
        allowed=allowed,
        reason=reason,
    )


def resolve_trade_conflicts(
    proposed_target: Iterable[str],
    current_holdings: Iterable[str],
    risk_table: pd.DataFrame,
    previous_signal: Iterable[str] | None = None,
    max_changes: int = 1,
) -> list[TradeConflict]:
    """Detect conflicts and document deterministic priority resolution."""
    target = _as_list(proposed_target)
    current = _as_list(current_holdings)
    previous = _as_list(previous_signal)
    target_set = set(target)
    current_set = set(current)
    additions = [code for code in target if code not in current_set]
    removals = [code for code in current if code not in target_set]
    conflicts: list[TradeConflict] = []

    if max(len(additions), len(removals)) > max_changes:
        conflicts.append(
            TradeConflict(
                "buy_signal_conflict",
                f"requested changes exceed max_changes={max_changes}",
                "execution inertia",
                "cap changes and defer lower-priority ranking moves",
            )
        )

    if previous and set(previous) != target_set:
        conflicts.append(
            TradeConflict(
                "rank_flip_within_1_day",
                "target set changed from previous frozen signal",
                "execution inertia",
                "debounce or defer unless risk overlay forces exit",
            )
        )

    if not risk_table.empty and "asset" in risk_table.columns:
        asset_map = {str(row.code): str(row.asset) for row in risk_table.itertuples(index=False)}
        for sell_code in removals:
            for buy_code in additions:
                if asset_map.get(sell_code) and asset_map.get(sell_code) == asset_map.get(buy_code):
                    conflicts.append(
                        TradeConflict(
                            "sell_buy_same_asset",
                            f"sell {sell_code} and buy {buy_code} in asset={asset_map[sell_code]}",
                            "risk_overlay",
                            "risk-forced exits first; otherwise keep existing position",
                        )
                    )

    if not risk_table.empty and "allow_hold" in risk_table.columns:
        row_by_code = {str(row.code): row for row in risk_table.itertuples(index=False)}
        for code in current:
            row = row_by_code.get(code)
            if row is not None and not bool(getattr(row, "allow_hold", True)) and code not in target_set:
                conflicts.append(
                    TradeConflict(
                        "risk_forced_exit",
                        f"{code} no longer allowed to hold",
                        "risk_overlay",
                        "risk exit overrides inertia and ranking",
                    )
                )
    return conflicts


def risk_warnings(risk_table: pd.DataFrame, limit: int = 8) -> list[str]:
    """Render top risk warnings from a risk-overlay table."""
    if risk_table.empty or "risk_reason" not in risk_table.columns:
        return []
    warnings: list[str] = []
    for row in risk_table.head(limit).itertuples(index=False):
        reason = str(getattr(row, "risk_reason", "OK"))
        if reason and reason != "OK":
            warnings.append(f"{getattr(row, 'name', getattr(row, 'code', ''))}: {reason}")
    return warnings


def _target_turnover(previous: Iterable[str], current: Iterable[str]) -> int:
    """Return max add/remove count between holding sets."""
    prev = set(_as_list(previous))
    curr = set(_as_list(current))
    return max(len(curr - prev), len(prev - curr))


def _turnover_rate(history: list[list[str]]) -> float:
    """Return average target turnover for a holding history."""
    if len(history) <= 1:
        return 0.0
    return sum(_target_turnover(prev, curr) for prev, curr in zip(history[:-1], history[1:], strict=False)) / (
        len(history) - 1
    )


def _format_actions(actions: list[dict[str, str]], code_map: dict) -> str:
    """Format execution actions for reports."""
    if not actions:
        return "no trade"
    parts = []
    for action in actions:
        code = action["code"]
        name = code_map[code].name if code in code_map else code
        parts.append(f"{action['action']} {name}({code})")
    return "; ".join(parts)


def run_paper_trading(prices: pd.DataFrame, cfg: ProjectConfig, days: int = 30) -> Path:
    """Simulate frozen T+1 execution without changing the research backtest."""
    features, symbols = prepare_features(prices, cfg, pools=["broad_etf"])
    code_map, _ = etf_maps(symbols)
    max_hold = int(cfg.universe.get("broad_etf", {}).get("max_hold", cfg.strategy.get("max_hold_broad", 2)))
    dates = sorted(pd.Timestamp(dt).normalize() for dt in features["date"].drop_duplicates())
    if not dates:
        raise ValueError("No feature dates available for paper-trading simulation.")
    start_index = max(0, len(dates) - int(days))

    current_holdings: list[str] = []
    pending_plan: ExecutionPlan | None = None
    signal_history: dict[pd.Timestamp, list[str]] = {}
    baseline_history: list[list[str]] = []
    stable_history: list[list[str]] = []
    executed_rows: list[dict[str, object]] = []
    ignored_rows: list[dict[str, object]] = []
    conflict_rows: list[dict[str, object]] = []
    reliability_rows: list[dict[str, object]] = []
    fidelity_rows: list[dict[str, object]] = []

    for idx, date_value in enumerate(dates):
        record_window = idx >= start_index
        if pending_plan is not None and pending_plan.execution_date == date_value.strftime("%Y-%m-%d"):
            before = current_holdings
            current_holdings = list(pending_plan.frozen_signal)
            if record_window:
                executed_rows.append(
                    {
                        "execution_date": pending_plan.execution_date,
                        "signal_date": pending_plan.signal_date,
                        "before": names_for_codes(before, code_map),
                        "after": names_for_codes(current_holdings, code_map),
                        "actions": _format_actions(pending_plan.actions, code_map),
                    }
                )
                reliability_rows.append(
                    {
                        "signal_date": pending_plan.signal_date,
                        "execution_date": pending_plan.execution_date,
                        "signal_target": to_pipe_list(pending_plan.frozen_signal),
                        "executed_target": to_pipe_list(current_holdings),
                    }
                )
                fidelity_rows.append(
                    {
                        "date": pending_plan.execution_date,
                        "t_plus_one": pd.Timestamp(pending_plan.execution_date)
                        > pd.Timestamp(pending_plan.signal_date),
                        "risk_priority": True,
                        "hold_inertia": _target_turnover(before, current_holdings) <= 1,
                    }
                )

        latest_features = features[features["date"].eq(date_value)].copy()
        pipeline = run_strategy_pipeline(latest_features, current_holdings, cfg.strategy, max_hold=max_hold)
        proposed = pipeline.target_holdings
        previous_signal = signal_history[max(signal_history)] if signal_history else []
        stability = apply_stability_controls(
            date_value,
            current_holdings,
            proposed,
            signal_history,
            prices=prices,
            max_changes=1,
        )
        conflicts = resolve_trade_conflicts(
            stability.target_holdings,
            current_holdings,
            pipeline.layer2_candidates,
            previous_signal=previous_signal,
            max_changes=1,
        )
        freeze = freeze_signal(date_value, stability.target_holdings, pipeline.layer2_candidates, persist=False)
        plan = build_execution_plan(freeze.state, current_holdings, dates)
        pending_plan = plan
        signal_history[date_value] = freeze.state.frozen_signal

        if record_window:
            baseline_history.append(list(proposed))
            stable_history.append(list(freeze.state.frozen_signal))
            for item in stability.ignored_signals:
                ignored_rows.append(
                    {
                        "date": date_value.strftime("%Y-%m-%d"),
                        "proposed": names_for_codes(proposed, code_map),
                        "used": names_for_codes(freeze.state.frozen_signal, code_map),
                        "reason": item,
                    }
                )
            for conflict in conflicts:
                conflict_rows.append(
                    {
                        "date": date_value.strftime("%Y-%m-%d"),
                        "type": conflict.conflict_type,
                        "priority": conflict.priority,
                        "detail": conflict.detail,
                        "resolution": conflict.resolution,
                    }
                )

    baseline_stability = strategy_stability_score(baseline_history, max_hold=max_hold)
    stable_stability = strategy_stability_score(stable_history, max_hold=max_hold)
    baseline_turnover = _turnover_rate(baseline_history)
    stable_turnover = _turnover_rate(stable_history)
    reliability_df = pd.DataFrame(reliability_rows)
    fidelity_df = pd.DataFrame(fidelity_rows)
    reliability_score = execution_reliability_score(reliability_df)
    mismatch_rate = 100.0 - reliability_score
    fidelity_score = real_world_fidelity_score(fidelity_df)

    report = _render_paper_trade_report(
        days=int(days),
        executed=pd.DataFrame(executed_rows),
        ignored=pd.DataFrame(ignored_rows),
        conflicts=pd.DataFrame(conflict_rows),
        baseline_stability=baseline_stability,
        stable_stability=stable_stability,
        baseline_turnover=baseline_turnover,
        stable_turnover=stable_turnover,
        reliability_score=reliability_score,
        mismatch_rate=mismatch_rate,
        fidelity_score=fidelity_score,
    )
    ensure_dir(cfg.reports_dir)
    output = cfg.reports_dir / "paper_trade_report.md"
    output.write_text(report + "\n", encoding="utf-8")
    return output


def _markdown_table(frame: pd.DataFrame) -> str:
    """Render a dataframe as markdown or a placeholder."""
    if frame.empty:
        return "_none_"
    return frame.to_markdown(index=False)


def _render_paper_trade_report(
    days: int,
    executed: pd.DataFrame,
    ignored: pd.DataFrame,
    conflicts: pd.DataFrame,
    baseline_stability: float,
    stable_stability: float,
    baseline_turnover: float,
    stable_turnover: float,
    reliability_score: float,
    mismatch_rate: float,
    fidelity_score: float,
) -> str:
    """Render the paper-trading markdown report."""
    return "\n".join(
        [
            "# Paper Trading Simulation Report",
            "",
            "本报告模拟信号冻结、T+1 开盘执行、冲突记录和稳定性控制；不做收益优化，不改变回测逻辑。",
            "",
            "## Summary",
            "",
            f"- simulation_days: {days}",
            f"- stability_score_before: {float_fmt(baseline_stability, 2)}",
            f"- stability_score_after: {float_fmt(stable_stability, 2)}",
            f"- turnover_rate_before: {float_fmt(baseline_turnover, 2)}",
            f"- turnover_rate_after: {float_fmt(stable_turnover, 2)}",
            f"- execution_reliability_score: {float_fmt(reliability_score, 2)}",
            f"- execution_mismatch_rate: {float_fmt(mismatch_rate, 2)}%",
            f"- real_world_fidelity_score: {float_fmt(fidelity_score, 2)}",
            "",
            "## Executed Trades",
            "",
            _markdown_table(executed),
            "",
            "## Ignored Signals",
            "",
            _markdown_table(ignored),
            "",
            "## Signal Conflicts",
            "",
            _markdown_table(conflicts),
            "",
        ]
    )
