"""Daily markdown and CSV report generation."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
import re

import pandas as pd

from .backtest import prepare_features, run_backtest
from .config import ProjectConfig
from .indicators import FLAT
from .metrics import PerformanceSummary, strategy_stability_score
from .realworld_execution import build_execution_plan, freeze_signal, resolve_trade_conflicts, risk_warnings
from .risk_overlay import apply_risk_overlay
from .selector import annotate_holding_changes, rank_candidates, select_holdings
from .stability_controller import apply_stability_controls
from .universe import etf_maps, load_universe, names_for_codes
from .utils import ensure_dir, float_fmt, from_pipe_list, latest_available_date, pct_fmt, safe_round, to_pipe_list


MAX_SIGNAL_REPORT_GAP_DAYS = 3
SIGNAL_LABEL_PATTERN = re.compile(r"^(?P<month>\d{2})(?P<day>\d{2})_(?P<side>[BS])$")


def _value_list(row: pd.Series) -> str:
    """Render one ETF feature list in the source-report style."""
    profit = row.get("profit_since_last_signal", "-")
    profit_value = safe_round(profit, 1) if profit != "-" else "-"
    values = [
        safe_round(row.get("ret20_pct"), 1),
        safe_round(row.get("bias_pct"), 1),
        str(row.get("trend", FLAT)),
        str(row.get("market_signal", FLAT)),
        str(row.get("convex", FLAT)),
        safe_round(row.get("nav_like"), 1),
        str(row.get("last_signal", FLAT)),
        profit_value,
        str(row.get("latest_signal", FLAT)),
    ]
    rendered = []
    for value in values:
        if isinstance(value, str):
            rendered.append(f"'{value}'")
        else:
            rendered.append(str(value))
    return "[" + ", ".join(rendered) + "]"


def render_feature_rows(ranking: pd.DataFrame, limit: int | None = None) -> list[str]:
    """Render ranking rows in source-report style."""
    rows: list[str] = []
    table = ranking.head(limit) if limit else ranking
    for _, row in table.iterrows():
        mark = str(row.get("status_mark", "×××"))
        pb = float(row.get("premium_pb", 1.0))
        rows.append(f"{mark}{row.get('name')}PB{pb:.2f}:{_value_list(row)}")
    return rows


def render_market_feature_rows(ranking: pd.DataFrame, limit: int | None = None) -> list[str]:
    """Render A-share market-index rows in the source-report style."""
    rows: list[str] = []
    table = ranking.head(limit) if limit else ranking
    for _, row in table.iterrows():
        rows.append(f"{row.get('name')}_:{_value_list(row)}")
    return rows


def build_market_index_ranking(prices: pd.DataFrame, cfg: ProjectConfig, as_of: pd.Timestamp) -> pd.DataFrame:
    """Build the A-share market-index calibration block for one date."""
    features, _ = prepare_features(prices, cfg, pools=["market_index"])
    features = features[pd.to_datetime(features["date"]).dt.normalize().le(pd.Timestamp(as_of).normalize())].copy()
    if features.empty:
        return pd.DataFrame()
    snapshot_date = pd.to_datetime(features["date"]).max()
    latest = features[features["date"].eq(snapshot_date)].copy()
    if latest.empty:
        return pd.DataFrame()
    latest["ret20_pct"] = pd.to_numeric(latest["ret20_pct"], errors="coerce")
    latest["status_mark"] = ""
    return latest.sort_values(["ret20_pct", "code"], ascending=[False, True]).reset_index(drop=True)


def sort_report_ranking(ranking: pd.DataFrame) -> pd.DataFrame:
    """Return report rows in the source-document strong-to-weak momentum order."""
    if ranking.empty or "ret20_pct" not in ranking.columns:
        return ranking.copy()
    table = ranking.copy()
    table["_ret20_sort"] = pd.to_numeric(table["ret20_pct"], errors="coerce").fillna(float("-inf"))
    return (
        table.sort_values(["_ret20_sort", "code"], ascending=[False, True])
        .drop(columns=["_ret20_sort"])
        .reset_index(drop=True)
    )


def relabel_current_signals_for_report(
    ranking: pd.DataFrame,
    signal_date: pd.Timestamp,
    report_date: pd.Timestamp,
    max_gap_days: int = MAX_SIGNAL_REPORT_GAP_DAYS,
) -> pd.DataFrame:
    """Display current-day signals with the report date used by source notes."""
    if ranking.empty or "latest_signal" not in ranking.columns:
        return ranking.copy()
    table = ranking.copy()
    if is_stale_report_context(signal_date, report_date, max_gap_days=max_gap_days):
        return table
    signal_prefix = pd.Timestamp(signal_date).strftime("%m%d")
    report_prefix = pd.Timestamp(report_date).strftime("%m%d")

    def relabel_latest(value: object) -> object:
        text = str(value)
        if text.startswith(f"{signal_prefix}_") and text.endswith(("_B", "_S")):
            return f"{report_prefix}_{text[-1]}"
        return value

    def relabel_last(value: object) -> object:
        text = str(value)
        match = SIGNAL_LABEL_PATTERN.match(text)
        if not match:
            return value
        source_date = pd.Timestamp(
            year=pd.Timestamp(signal_date).year,
            month=int(match.group("month")),
            day=int(match.group("day")),
        )
        if source_date > pd.Timestamp(signal_date):
            source_date = pd.Timestamp(
                year=pd.Timestamp(signal_date).year - 1,
                month=int(match.group("month")),
                day=int(match.group("day")),
            )
        display_date = source_date + pd.offsets.BDay(1)
        return f"{display_date.strftime('%m%d')}_{match.group('side')}"

    table["latest_signal"] = table["latest_signal"].map(relabel_latest)
    if "last_signal" in table.columns:
        table["last_signal"] = table["last_signal"].map(relabel_last)
    return table


def is_stale_report_context(
    signal_date: pd.Timestamp,
    report_date: pd.Timestamp,
    max_gap_days: int = MAX_SIGNAL_REPORT_GAP_DAYS,
) -> bool:
    """Return true when cached feature data is too old for the requested report date."""
    gap_days = (pd.Timestamp(report_date).normalize() - pd.Timestamp(signal_date).normalize()).days
    return gap_days > max_gap_days


def _signal_names(ranking: pd.DataFrame, suffix: str) -> list[str]:
    """Return source-style current-day B/S signal labels."""
    values = []
    for _, row in ranking.iterrows():
        signal = str(row.get("latest_signal", FLAT))
        if signal.endswith(suffix):
            values.append(f"{row.get('code')}({row.get('name')})")
    return values


def _signal_list_text(values: list[str]) -> str:
    """Render signal labels without Python list syntax."""
    return "、".join(values) if values else "-"


def _recent_years(summary: PerformanceSummary, annual_days: int) -> str:
    """Return a compact period label for report text."""
    years = summary.observation_days / annual_days if annual_days else 0
    return f"{years:.1f}"


def resolve_report_dates(prices: pd.DataFrame, report_date: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Return display date and signal date using data through yesterday."""
    available = pd.to_datetime(prices["date"]).drop_duplicates().sort_values()
    if available.empty:
        raise ValueError("No available price dates found.")
    if str(report_date).lower() == "latest":
        display_date = latest_available_date(available)
    else:
        display_date = pd.Timestamp(report_date).normalize()

    cutoff = display_date - timedelta(days=1)
    signal_dates = available[available <= cutoff]
    if signal_dates.empty:
        signal_dates = available[available <= display_date]
    signal_date = latest_available_date(signal_dates)
    return pd.Timestamp(display_date).normalize(), pd.Timestamp(signal_date).normalize()


def load_holding_overrides(cfg: ProjectConfig) -> dict[pd.Timestamp, list[str]]:
    """Load optional manual holding-context overrides for distillation."""
    path = cfg.project_root / "data" / "processed" / "holding_overrides.csv"
    if not path.exists():
        return {}
    frame = pd.read_csv(path)
    if not {"signal_date", "yesterday_holdings"}.issubset(frame.columns):
        return {}
    dates = pd.to_datetime(frame["signal_date"], errors="coerce").dt.normalize()
    overrides: dict[pd.Timestamp, list[str]] = {}
    for idx, row in frame.assign(_date=dates).dropna(subset=["_date"]).iterrows():
        values = from_pipe_list(row["yesterday_holdings"])
        if values:
            overrides[pd.Timestamp(row["_date"]).normalize()] = values
    return overrides


def load_yesterday_holding_override(cfg: ProjectConfig, signal_date: pd.Timestamp) -> list[str] | None:
    """Load an optional manual yesterday-holdings override for distillation."""
    values = load_holding_overrides(cfg).get(pd.Timestamp(signal_date).normalize())
    return values or None


def generate_daily_report(
    prices: pd.DataFrame,
    cfg: ProjectConfig,
    report_date: str = "latest",
    sample: bool = False,
    execution_stability: bool = True,
) -> dict[str, Path]:
    """Generate daily markdown and CSV reports from cached prices."""
    display_date, as_of = resolve_report_dates(prices, report_date)
    stale_context = is_stale_report_context(as_of, display_date)
    stale_warning = ""
    if stale_context:
        stale_warning = (
            f"数据滞后：请求报告日 {display_date.strftime('%Y-%m-%d')} 与行情截止日 "
            f"{as_of.strftime('%Y-%m-%d')} 间隔 {(display_date - as_of).days} 天；"
            f"以下不是 {display_date.strftime('%Y-%m-%d')} 的实时/最新信号。"
        )

    result = run_backtest(prices, cfg, start=None, end=as_of.strftime("%Y-%m-%d"), write_reports=False)
    if as_of not in result.ranking_history:
        as_of = max(result.ranking_history)
    ranking = result.ranking_history[as_of].copy()
    broad_symbols = load_universe(cfg.universe, pools=["broad_etf"])
    code_map, _ = etf_maps(broad_symbols)

    history_dates = sorted(result.target_history)
    idx = history_dates.index(as_of)
    yesterday_codes = result.target_history[history_dates[idx - 1]] if idx > 0 else []
    today_codes = result.target_history[as_of]
    holding_overrides = load_holding_overrides(cfg)
    holding_override = holding_overrides.get(as_of)
    override_used = holding_override is not None
    prior_history = {dt: result.target_history[dt] for dt in history_dates if dt < as_of}
    for override_date, override_codes in holding_overrides.items():
        if override_date < as_of:
            prior_history[override_date] = override_codes
    if holding_override is not None or any(dt < as_of for dt in holding_overrides):
        max_hold = int(cfg.universe.get("broad_etf", {}).get("max_hold", cfg.strategy.get("max_hold_broad", 2)))
        latest_features = result.features[result.features["date"].eq(as_of)].copy()
        selection = select_holdings(
            latest_features=latest_features,
            yesterday_holdings=holding_override or yesterday_codes,
            history_holdings=prior_history,
            strategy=cfg.strategy,
            max_hold=max_hold,
        )
        if holding_override is not None:
            yesterday_codes = holding_override
        today_codes = selection.target_holdings
        ranking = selection.ranking_table
    yesterday_names = names_for_codes(yesterday_codes, code_map)
    today_names = names_for_codes(today_codes, code_map)
    risk_table = apply_risk_overlay(ranking, cfg.strategy)
    if execution_stability:
        stability_decision = apply_stability_controls(
            as_of,
            yesterday_codes,
            today_codes,
            prior_history,
            prices=prices,
            max_changes=1,
        )
        state_dir = cfg.project_root / "data" / "processed" / "frozen_signals"
        freeze = freeze_signal(
            as_of,
            stability_decision.target_holdings,
            risk_table,
            state_dir=state_dir,
            persist=not override_used,
        )
        final_today_codes = list(freeze.state.frozen_signal)
        final_today_names = names_for_codes(final_today_codes, code_map)
        yesterday_display, today_display = annotate_holding_changes(yesterday_names, final_today_names)
        trading_dates = sorted(pd.Timestamp(dt).normalize() for dt in prices["date"].drop_duplicates())
        execution_plan = build_execution_plan(freeze.state, yesterday_codes, trading_dates)
        previous_signal = result.target_history[history_dates[idx - 1]] if idx > 0 else []
        conflicts = resolve_trade_conflicts(
            freeze.state.frozen_signal,
            yesterday_codes,
            risk_table,
            previous_signal=previous_signal,
            max_changes=1,
        )
        recent_history = [result.target_history[dt] for dt in history_dates[-29:]] + [freeze.state.frozen_signal]
        stability_score = strategy_stability_score(
            recent_history,
            max_hold=int(cfg.strategy.get("max_hold_broad", 2)),
        )
        realworld_context = {
            "mode": "stable",
            "recommended_holdings": today_names,
            "frozen_signal": final_today_names,
            "freeze_message": freeze.message,
            "source_features_hash": freeze.state.source_features_hash[:12],
            "execution_date": execution_plan.execution_date,
            "execution_actions": [
                f"{item['action']} {code_map[item['code']].name if item['code'] in code_map else item['code']}"
                for item in execution_plan.actions
            ],
            "ignored_signals": stability_decision.ignored_signals
            + ([freeze.message] if freeze.hash_changed else []),
            "signal_conflicts": [f"{item.conflict_type}: {item.resolution}" for item in conflicts],
            "risk_warnings": risk_warnings(risk_table),
            "turnover_estimate": max(
                len(set(freeze.state.frozen_signal) - set(yesterday_codes)),
                len(set(yesterday_codes) - set(freeze.state.frozen_signal)),
            ),
            "stability_score": stability_score,
            "execution_confidence": float(getattr(result, "execution_confidence", 0.0) or 0.0),
            "data_warning": stale_warning,
        }
        if override_used:
            realworld_context["ignored_signals"] = list(realworld_context["ignored_signals"]) + [
                f"manual_holding_override: {names_for_codes(holding_override, code_map)}"
            ]
    else:
        final_today_codes = list(today_codes)
        final_today_names = names_for_codes(final_today_codes, code_map)
        yesterday_display, today_display = annotate_holding_changes(yesterday_names, final_today_names)
        context_notes = []
        if override_used:
            context_notes.append(f"manual_holding_override: {names_for_codes(holding_override, code_map)}")
        realworld_context = {
            "mode": "direct",
            "target_holdings": final_today_names,
            "context_notes": context_notes,
            "risk_warnings": risk_warnings(risk_table),
            "turnover_estimate": max(
                len(set(final_today_codes) - set(yesterday_codes)),
                len(set(yesterday_codes) - set(final_today_codes)),
            ),
            "data_warning": stale_warning,
        }

    market_index_ranking = pd.DataFrame()
    try:
        market_index_ranking = build_market_index_ranking(prices, cfg, as_of)
        market_index_ranking = relabel_current_signals_for_report(market_index_ranking, as_of, display_date)
    except Exception:
        market_index_ranking = pd.DataFrame()

    sector_ranking = pd.DataFrame()
    try:
        sector_features, _ = prepare_features(prices, cfg, pools=["sector_etf"])
        sector_latest = sector_features[sector_features["date"].eq(as_of)].copy()
        sector_ranking = rank_candidates(sector_latest, cfg.strategy, yesterday_holdings=[])
        sector_ranking["status_mark"] = "×××"
        sector_ranking = relabel_current_signals_for_report(sector_ranking, as_of, display_date)
        sector_ranking = sort_report_ranking(sector_ranking)
    except Exception:
        sector_ranking = pd.DataFrame()

    report_ranking = relabel_current_signals_for_report(ranking, as_of, display_date)
    report_ranking = sort_report_ranking(report_ranking)

    annual_days = int(cfg.strategy.get("backtest", {}).get("annual_trading_days", 244))
    markdown = render_daily_markdown(
        report_date=display_date,
        signal_date=as_of,
        ranking=report_ranking,
        market_index_ranking=market_index_ranking,
        sector_ranking=sector_ranking,
        yesterday_display=yesterday_display,
        today_display=today_display,
        summary=result.summary,
        sample=sample,
        annual_days=annual_days,
        position_label=str(result.nav["control_label"].iloc[-1]) if not result.nav.empty else "现在半仓",
        realworld_context=realworld_context,
    )

    ensure_dir(cfg.reports_dir)
    suffix = "" if execution_stability else "_no_stability"
    md_path = cfg.reports_dir / f"daily_{display_date.strftime('%Y-%m-%d')}{suffix}.md"
    csv_path = cfg.reports_dir / f"daily_{display_date.strftime('%Y-%m-%d')}{suffix}.csv"
    md_path.write_text(markdown, encoding="utf-8")
    export = report_ranking.copy()
    export["target_holdings"] = to_pipe_list(final_today_names)
    export.to_csv(csv_path, index=False)
    return {"markdown": md_path, "csv": csv_path}


def render_daily_markdown(
    report_date: pd.Timestamp,
    signal_date: pd.Timestamp,
    ranking: pd.DataFrame,
    market_index_ranking: pd.DataFrame,
    sector_ranking: pd.DataFrame,
    yesterday_display: list[str],
    today_display: list[str],
    summary: PerformanceSummary,
    sample: bool,
    annual_days: int,
    position_label: str,
    realworld_context: dict[str, object] | None = None,
) -> str:
    """Render the daily report markdown body."""
    date_text = pd.Timestamp(report_date).strftime("%Y-%m-%d")
    signal_date_text = pd.Timestamp(signal_date).strftime("%Y-%m-%d")
    china_block = market_index_ranking
    buy_signals = _signal_names(ranking, "_B")
    sell_signals = _signal_names(ranking, "_S")
    add_line = "可以加仓!★" if position_label == "现在满仓" else ""
    years = _recent_years(summary, annual_days)
    notes = [
        f"本报告特征使用截至 {signal_date_text} 收盘的数据。",
        "注：PB/溢价字段第一版可能为缺省估算值，QDII溢价需后续接入净值或IOPV数据校正。"
    ]
    if realworld_context and realworld_context.get("data_warning"):
        notes.insert(0, str(realworld_context["data_warning"]))
    if sample:
        notes.insert(0, "当前使用 synthetic sample data，不代表真实行情。")
    rw = realworld_context or {}
    execution_actions = rw.get("execution_actions") or ["no trade"]
    ignored_signals = rw.get("ignored_signals") or ["-"]
    signal_conflicts = rw.get("signal_conflicts") or ["-"]
    warnings = rw.get("risk_warnings") or ["-"]
    if rw.get("mode") == "direct":
        notes.insert(1 if notes else 0, "本版本为蒸馏策略直出，未使用冻结信号、防抖或 T+1 执行覆盖。")

    lines = [
        f"您好！今天是 {date_text}",
        "ETF轮动策略复现版盘中提示如下：",
        "（投资有风险，入市需谨慎；本报告仅用于研究，不构成投资建议。）",
        "",
    ]
    if rw.get("data_warning"):
        lines.extend([str(rw["data_warning"]), ""])
    if sample:
        lines.extend(["当前使用 synthetic sample data，不代表真实行情。", ""])

    lines.extend(
        [
            "A股大盘截至昨日强弱排序：",
            "大盘上升趋势时，个股更容易上涨！",
            "近日表现:[涨幅%，乖离率%，现趋势，多空信号，趋势凹凸，净值，上次信号，盈利%，最新信号]",
            *(render_market_feature_rows(china_block) if not china_block.empty else ["A股大盘数据暂不可用。"]),
            "",
            "大类 ETF 截至昨日强弱排序：",
            "以下为最多选取2只标的组合操作的收益特征，本组合为复现研究版。",
        ]
    )
    if add_line:
        lines.append(add_line)
    lines.extend(
        [
            "",
            f"昨日收盘组合持仓{yesterday_display}",
            f"今日收盘组合应持仓{today_display}",
            "",
        ]
    )
    if rw.get("mode") == "direct":
        context_notes = rw.get("context_notes") or ["-"]
        lines.extend(
            [
                "蒸馏策略直出：",
                f"1. target holdings: {rw.get('target_holdings', '-')}",
                f"2. context notes: {context_notes}",
                f"3. risk warnings: {warnings}",
                f"4. turnover estimate: {rw.get('turnover_estimate', 0)}",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "实盘执行稳定层：",
                f"1. recommended holdings: {rw.get('recommended_holdings', '-')}",
                f"2. frozen signals: {rw.get('frozen_signal', '-')}",
                f"   - freeze state: {rw.get('freeze_message', '-')}",
                f"   - source_features_hash: {rw.get('source_features_hash', '-')}",
                f"3. execution plan (T+1): {rw.get('execution_date', '-')} open -> {execution_actions}",
                f"4. ignored unstable signals: {ignored_signals}",
                f"5. signal conflicts: {signal_conflicts}",
                f"6. risk warnings: {warnings}",
                f"7. turnover estimate: {rw.get('turnover_estimate', 0)}",
                f"8. stability score: {float_fmt(rw.get('stability_score', 0), 2)}",
                "",
            ]
        )
    lines.extend(
        [
            f"最近{years}年组合净值由 1.00 变化到 {float_fmt(summary.nav)}，控仓法 {float_fmt(summary.control_nav)}",
            f"平均年化 {pct_fmt(summary.annual_return)}，控仓法 {pct_fmt(summary.control_annual_return)}",
            f"最近{years}年年化 {pct_fmt(summary.annual_return)}，控仓法 {pct_fmt(summary.control_annual_return)}",
            f"当前回撤 {pct_fmt(summary.current_drawdown)}，控仓法 {pct_fmt(summary.control_current_drawdown)}",
            f"最大回撤 {pct_fmt(summary.max_drawdown)}，控仓法 {pct_fmt(summary.control_max_drawdown)}",
            f"夏普值 {float_fmt(summary.sharpe, 2)}，控仓法 {float_fmt(summary.control_sharpe, 2)}",
            f"交易天数 {summary.trade_count}/考察天数 {summary.observation_days}，{position_label}。",
            "",
            "单品种近日表现:[涨幅%，乖离率%，现趋势，多空信号，趋势凹凸，净值，上次信号，盈利%，最新信号]",
            *render_feature_rows(ranking),
            "",
            "单只操作时需要根据买卖关键点做出决策！",
            f"今日买入信号：{_signal_list_text(buy_signals)}",
            f"今日卖出信号：{_signal_list_text(sell_signals)}",
            "",
            "行业 ETF 截至昨日强弱排序：",
            "以下为最多选取10只标的组合操作的观察特征，本模块第一版仅供行业观察，不参与主策略交易。",
        ]
    )
    if sector_ranking.empty:
        lines.append("行业 ETF 数据暂不可用。")
    else:
        lines.extend(render_feature_rows(sector_ranking, limit=10))
    lines.extend(["", "数据源和实现备注：", *[f"{idx}. {note}" for idx, note in enumerate(notes, start=1)]])
    return "\n".join(lines) + "\n"
