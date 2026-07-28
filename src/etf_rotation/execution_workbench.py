"""Human-in-the-loop execution workbench for ETF decisions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Iterable

import pandas as pd

from .backtest import run_backtest
from .config import ProjectConfig
from .execution_logger import append_execution_log, read_execution_log, utc_now_iso
from .realworld_execution import build_execution_plan, freeze_signal, resolve_trade_conflicts
from .risk_disclosure import write_risk_notice
from .risk_overlay import apply_risk_overlay
from .selector import select_holdings
from .stability_controller import apply_stability_controls
from .universe import etf_maps, load_universe, names_for_codes
from .utils import ensure_dir, from_pipe_list, latest_available_date


@dataclass(frozen=True)
class TradeOrder:
    """One manual trade instruction row."""

    date: str
    action: str
    symbol: str
    name: str
    suggested_weight: float
    weight_change: str
    reason: str
    risk_flag: str
    priority: int
    confidence_score: float


@dataclass(frozen=True)
class TradeSheetResult:
    """Generated trade sheet and associated manual-execution artifacts."""

    execution_id: str
    signal_date: str
    execution_date: str
    trade_sheet_path: Path
    risk_notice_path: Path
    orders: list[TradeOrder]
    frozen_signal: list[str]
    current_holdings: list[str]
    ignored_signals: list[str]
    conflicts: list[str]
    turnover_estimate: int
    status: str


def _as_list(values: Iterable[str] | None) -> list[str]:
    """Return a clean list of codes."""
    return [str(item) for item in values or [] if str(item)]


def _resolve_report_date(prices: pd.DataFrame, date: str) -> pd.Timestamp:
    """Resolve requested date against available cached prices."""
    if str(date).lower() == "latest":
        return latest_available_date(prices["date"])
    requested = pd.Timestamp(date).normalize()
    available = pd.to_datetime(prices.loc[prices["date"] <= requested, "date"]).drop_duplicates()
    return latest_available_date(available)


def _load_holding_overrides(cfg: ProjectConfig) -> dict[pd.Timestamp, list[str]]:
    """Load manual holding-context overrides used by distilled daily reports."""
    path = cfg.project_root / "data" / "processed" / "holding_overrides.csv"
    if not path.exists():
        return {}
    frame = pd.read_csv(path)
    if not {"signal_date", "yesterday_holdings"}.issubset(frame.columns):
        return {}
    dates = pd.to_datetime(frame["signal_date"], errors="coerce").dt.normalize()
    overrides: dict[pd.Timestamp, list[str]] = {}
    for _, row in frame.assign(_date=dates).dropna(subset=["_date"]).iterrows():
        values = from_pipe_list(row["yesterday_holdings"])
        if values:
            overrides[pd.Timestamp(row["_date"]).normalize()] = values
    return overrides


def _lock_dir(cfg: ProjectConfig) -> Path:
    """Return execution lock directory."""
    return cfg.project_root / "data" / "processed" / "execution_locks"


def _lock_path(cfg: ProjectConfig, signal_date: str) -> Path:
    """Return lock path for one signal date."""
    return _lock_dir(cfg) / f"{signal_date}.json"


def _read_lock(path: Path) -> dict:
    """Read an execution lock if it exists."""
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_lock(cfg: ProjectConfig, signal_date: str, payload: dict) -> Path:
    """Write execution lock payload."""
    ensure_dir(_lock_dir(cfg))
    path = _lock_path(cfg, signal_date)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _execution_id(signal_date: str, source_hash: str) -> str:
    """Return stable execution id for a frozen signal."""
    digest = hashlib.sha256(f"{signal_date}|{source_hash}".encode("utf-8")).hexdigest()[:10]
    return f"EXE-{signal_date}-{digest}"


def _bind_execution_id(frozen_signal_dir: Path, signal_date: str, execution_id: str) -> None:
    """Bind frozen signal JSON to an execution id."""
    path = frozen_signal_dir / f"{signal_date}.json"
    if not path.exists():
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    data["execution_id"] = execution_id
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _target_weights(codes: Iterable[str]) -> dict[str, float]:
    """Return equal suggested weights for target holdings."""
    target = _as_list(codes)
    if not target:
        return {}
    weight = 1.0 / len(target)
    return {code: weight for code in target}


def _risk_flag(row: pd.Series | None) -> str:
    """Return compact risk flag for a trade sheet row."""
    if row is None:
        return "NORMAL"
    reason = str(row.get("risk_reason", ""))
    if "OVERHEAT" in reason:
        return "OVERHEAT"
    if "QDII" in reason or bool(row.get("qdii", False)):
        return "QDII"
    return "NORMAL"


def _priority(action: str, risk_flag: str) -> int:
    """Return manual execution priority from 1 highest to 5 lowest."""
    if action == "SELL" and risk_flag == "OVERHEAT":
        return 1
    if action == "SELL":
        return 2
    if action == "BUY":
        return 3
    if risk_flag != "NORMAL":
        return 4
    return 5


def _explain_trade(
    action: str,
    name: str,
    row: pd.Series | None,
    confidence: float,
) -> str:
    """Generate a human-readable trade explanation."""
    if action == "HOLD":
        headline = f"持有 {name}"
    elif action == "BUY":
        headline = f"买入 {name}"
    else:
        headline = f"卖出 {name}"
    if row is None:
        return f"{headline}: source row unavailable; confidence={confidence:.2f}"
    parts = [
        headline,
        "原因:",
        f"- 20日动量排名 {int(row.get('momentum_rank', 9999))}",
        f"- trend = {row.get('trend', '-')}",
        f"- risk overlay = {row.get('risk_reason', 'OK')}",
        f"- execution confidence = {confidence:.2f}",
    ]
    if action == "BUY":
        parts.append("- execution inertia allows entry")
    elif action == "SELL":
        parts.append("- execution policy requires removal or risk exit")
    else:
        parts.append("- execution inertia preserves position")
    return " ".join(parts)


def build_trade_orders(
    *,
    signal_date: str,
    current_holdings: Iterable[str],
    target_holdings: Iterable[str],
    risk_table: pd.DataFrame,
    code_map: dict,
    confidence_score: float,
) -> list[TradeOrder]:
    """Build manual trade orders from current and target holdings."""
    current = _as_list(current_holdings)
    target = _as_list(target_holdings)
    before_weights = _target_weights(current)
    after_weights = _target_weights(target)
    codes = list(dict.fromkeys([*current, *target]))
    row_by_code = {
        str(row.code): pd.Series(row._asdict()) for row in risk_table.itertuples(index=False)
    } if not risk_table.empty else {}
    orders: list[TradeOrder] = []
    for code in codes:
        before = before_weights.get(code, 0.0)
        after = after_weights.get(code, 0.0)
        if before == after and before > 0:
            action = "HOLD"
        elif after > before:
            action = "BUY"
        else:
            action = "SELL"
        row = row_by_code.get(code)
        name = code_map[code].name if code in code_map else str(row.get("name", code) if row is not None else code)
        risk_flag = _risk_flag(row)
        orders.append(
            TradeOrder(
                date=signal_date,
                action=action,
                symbol=code,
                name=name,
                suggested_weight=after,
                weight_change=f"{before:.2f} -> {after:.2f}",
                reason=_explain_trade(action, name, row, confidence_score),
                risk_flag=risk_flag,
                priority=_priority(action, risk_flag),
                confidence_score=confidence_score,
            )
        )
    return sorted(orders, key=lambda item: (item.priority, item.symbol))


def _orders_to_frame(orders: list[TradeOrder]) -> pd.DataFrame:
    """Convert trade orders to the required CSV schema."""
    action_map = {"BUY": "买", "SELL": "卖", "HOLD": "持有"}
    return pd.DataFrame(
        [
            {
                "ETF名称": item.name,
                "代码": item.symbol,
                "今日操作": action_map.get(item.action, item.action),
                "仓位变化": item.weight_change,
                "风险标签": item.risk_flag,
                "执行优先级": item.priority,
                "备注": item.reason,
                "suggested_weight": item.suggested_weight,
                "confidence_score": item.confidence_score,
            }
            for item in orders
        ]
    )


def _context_for_date(prices: pd.DataFrame, cfg: ProjectConfig, date: str) -> dict:
    """Build strategy context for a manual execution date."""
    as_of = _resolve_report_date(prices, date)
    result = run_backtest(prices, cfg, start=None, end=as_of.strftime("%Y-%m-%d"), write_reports=False)
    if as_of not in result.ranking_history:
        as_of = max(result.ranking_history)
    history_dates = sorted(result.target_history)
    idx = history_dates.index(as_of)
    yesterday = result.target_history[history_dates[idx - 1]] if idx > 0 else []
    proposed = result.target_history[as_of]
    ranking = result.ranking_history[as_of].copy()
    holding_overrides = _load_holding_overrides(cfg)
    override_used = False
    prior_history = {dt: result.target_history[dt] for dt in history_dates if dt < as_of}
    for override_date, override_codes in holding_overrides.items():
        if override_date < as_of:
            prior_history[override_date] = override_codes
    if as_of in holding_overrides or any(dt < as_of for dt in holding_overrides):
        override_used = True
        max_hold = int(cfg.universe.get("broad_etf", {}).get("max_hold", cfg.strategy.get("max_hold_broad", 2)))
        latest_features = result.features[result.features["date"].eq(as_of)].copy()
        yesterday = holding_overrides.get(as_of, yesterday)
        selection = select_holdings(
            latest_features=latest_features,
            yesterday_holdings=yesterday,
            history_holdings=prior_history,
            strategy=cfg.strategy,
            max_hold=max_hold,
        )
        proposed = selection.target_holdings
        ranking = selection.ranking_table
    risk_table = apply_risk_overlay(ranking, cfg.strategy)
    stability = apply_stability_controls(as_of, yesterday, proposed, prior_history, prices=prices, max_changes=1)
    frozen_dir = cfg.project_root / "data" / "processed" / "frozen_signals"
    freeze = freeze_signal(as_of, stability.target_holdings, risk_table, state_dir=frozen_dir, persist=not override_used)
    trading_dates = sorted(pd.Timestamp(dt).normalize() for dt in prices["date"].drop_duplicates())
    plan = build_execution_plan(freeze.state, yesterday, trading_dates)
    conflicts = resolve_trade_conflicts(
        freeze.state.frozen_signal,
        yesterday,
        risk_table,
        previous_signal=yesterday,
        max_changes=1,
    )
    symbols = load_universe(cfg.universe, pools=["broad_etf"])
    code_map, _ = etf_maps(symbols)
    return {
        "as_of": as_of,
        "yesterday": yesterday,
        "proposed": proposed,
        "risk_table": risk_table,
        "freeze": freeze,
        "plan": plan,
        "conflicts": conflicts,
        "ignored_signals": stability.ignored_signals,
        "override_used": override_used,
        "code_map": code_map,
    }


def generate_trade_sheet(prices: pd.DataFrame, cfg: ProjectConfig, date: str = "latest") -> TradeSheetResult:
    """Generate a manual trade sheet and risk notice for one frozen signal."""
    context = _context_for_date(prices, cfg, date)
    as_of = pd.Timestamp(context["as_of"]).normalize()
    signal_date = as_of.strftime("%Y-%m-%d")
    freeze = context["freeze"]
    plan = context["plan"]
    risk_table = context["risk_table"]
    code_map = context["code_map"]
    execution_id = _execution_id(signal_date, freeze.state.source_features_hash)
    lock_path = _lock_path(cfg, signal_date)
    existing_lock = _read_lock(lock_path)
    if existing_lock.get("status") == "executed":
        trade_sheet_path = Path(existing_lock.get("trade_sheet", cfg.reports_dir / f"trade_sheet_{signal_date}.csv"))
        risk_notice_path = Path(existing_lock.get("risk_notice", cfg.reports_dir / f"risk_notice_{signal_date}.md"))
        return TradeSheetResult(
            execution_id=str(existing_lock.get("execution_id", execution_id)),
            signal_date=signal_date,
            execution_date=str(existing_lock.get("execution_date", plan.execution_date)),
            trade_sheet_path=trade_sheet_path,
            risk_notice_path=risk_notice_path,
            orders=[],
            frozen_signal=list(freeze.state.frozen_signal),
            current_holdings=list(context["yesterday"]),
            ignored_signals=list(context["ignored_signals"]),
            conflicts=[item.conflict_type for item in context["conflicts"]],
            turnover_estimate=0,
            status="executed",
        )

    confidence = 0.0
    if "score" in risk_table.columns:
        selected = risk_table[risk_table["code"].astype(str).isin(freeze.state.frozen_signal)]
        confidence = float(pd.to_numeric(selected["score"], errors="coerce").fillna(0.0).mean()) if not selected.empty else 0.0
    orders = build_trade_orders(
        signal_date=signal_date,
        current_holdings=context["yesterday"],
        target_holdings=freeze.state.frozen_signal,
        risk_table=risk_table,
        code_map=code_map,
        confidence_score=confidence,
    )
    ensure_dir(cfg.reports_dir)
    trade_sheet_path = cfg.reports_dir / f"trade_sheet_{signal_date}.csv"
    _orders_to_frame(orders).to_csv(trade_sheet_path, index=False)
    turnover_estimate = max(
        len(set(freeze.state.frozen_signal) - set(context["yesterday"])),
        len(set(context["yesterday"]) - set(freeze.state.frozen_signal)),
    )
    risk_notice_path = write_risk_notice(cfg, as_of, risk_table, turnover_estimate)
    if not context["override_used"]:
        _bind_execution_id(cfg.project_root / "data" / "processed" / "frozen_signals", signal_date, execution_id)
    lock_payload = {
        "execution_id": execution_id,
        "signal_date": signal_date,
        "execution_date": plan.execution_date,
        "status": existing_lock.get("status", "generated"),
        "trade_sheet": str(trade_sheet_path),
        "risk_notice": str(risk_notice_path),
        "symbols": [item.symbol for item in orders],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_lock(cfg, signal_date, lock_payload)
    return TradeSheetResult(
        execution_id=execution_id,
        signal_date=signal_date,
        execution_date=plan.execution_date,
        trade_sheet_path=trade_sheet_path,
        risk_notice_path=risk_notice_path,
        orders=orders,
        frozen_signal=list(freeze.state.frozen_signal),
        current_holdings=list(context["yesterday"]),
        ignored_signals=list(context["ignored_signals"]),
        conflicts=[f"{item.conflict_type}: {item.resolution}" for item in context["conflicts"]],
        turnover_estimate=turnover_estimate,
        status=lock_payload["status"],
    )


def summarize_trade_sheet(result: TradeSheetResult, code_map: dict | None = None) -> str:
    """Return a concise human-readable trade-sheet summary."""
    executed = [item for item in result.orders if item.action in {"BUY", "SELL"}]
    holds = [item for item in result.orders if item.action == "HOLD"]
    risk_counts: dict[str, int] = {}
    for item in result.orders:
        risk_counts[item.risk_flag] = risk_counts.get(item.risk_flag, 0) + 1
    lines = [
        f"execution_id: {result.execution_id}",
        f"signal_date: {result.signal_date}",
        f"execution_date: {result.execution_date} open (T+1)",
        f"status: {result.status}",
        f"trade_sheet: {result.trade_sheet_path}",
        f"risk_notice: {result.risk_notice_path}",
        f"frozen_signals: {result.frozen_signal}",
        f"today_orders: {[(item.action, item.name, item.weight_change) for item in result.orders]}",
        f"risk_summary: {risk_counts or '-'}",
        f"executed_or_pending_list: {[(item.action, item.symbol) for item in executed] or '-'}",
        f"hold_list: {[item.symbol for item in holds] or '-'}",
        f"ignored_signals: {result.ignored_signals or '-'}",
        f"signal_conflicts: {result.conflicts or '-'}",
        f"turnover_estimate: {result.turnover_estimate}",
    ]
    return "\n".join(lines)


def finalize_execution(
    cfg: ProjectConfig,
    result: TradeSheetResult,
    confirmation: str,
) -> dict:
    """Mark a generated trade sheet as executed or rejected after human confirmation."""
    value = confirmation.strip().upper()
    if value not in {"YES", "NO"}:
        raise ValueError("Confirmation must be YES or NO.")
    lock_path = _lock_path(cfg, result.signal_date)
    lock = _read_lock(lock_path)
    if lock.get("status") == "executed":
        raise RuntimeError(f"Execution already marked executed: {result.execution_id}")
    decision_time = utc_now_iso()
    executed_signals = [item.symbol for item in result.orders if item.action in {"BUY", "SELL"}]
    rejected_signals: list[str] = []
    status = "executed" if value == "YES" else "rejected"
    execution_time = utc_now_iso() if value == "YES" else ""
    if value == "NO":
        rejected_signals = list(result.frozen_signal)
        executed_signals = []
    lock.update(
        {
            "execution_id": result.execution_id,
            "signal_date": result.signal_date,
            "execution_date": result.execution_date,
            "status": status,
            "confirmed_at": decision_time,
            "trade_sheet": str(result.trade_sheet_path),
            "risk_notice": str(result.risk_notice_path),
            "executed_symbols": executed_signals,
            "rejected_symbols": rejected_signals,
        }
    )
    _write_lock(cfg, result.signal_date, lock)
    signal_path = cfg.project_root / "data" / "processed" / "frozen_signals" / f"{result.signal_date}.json"
    signal_time = decision_time
    if signal_path.exists():
        signal_data = json.loads(signal_path.read_text(encoding="utf-8"))
        signal_time = str(signal_data.get("timestamp", decision_time))
    append_execution_log(
        cfg,
        event="manual_execution_decision",
        execution_id=result.execution_id,
        signal_date=result.signal_date,
        signal_time=signal_time,
        decision_time=decision_time,
        execution_time=execution_time,
        ignored_signals=result.ignored_signals,
        executed_signals=executed_signals,
        rejected_signals=rejected_signals,
        status=status,
        trade_sheet=str(result.trade_sheet_path),
        risk_notice=str(result.risk_notice_path),
    )
    return lock


def review_executions(cfg: ProjectConfig, start: str | None, end: str | None) -> pd.DataFrame:
    """Return execution audit history for CLI review."""
    return read_execution_log(cfg, start=start, end=end)
