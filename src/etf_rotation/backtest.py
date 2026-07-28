"""Daily ETF rotation backtest engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .config import ProjectConfig
from .data_provider import load_premium_cache
from .indicators import compute_indicators
from .metrics import PerformanceSummary, drawdown, summarize_performance
from .position import determine_control_position, equal_weights, weight_delta
from .selector import SelectionResult, select_holdings
from .signals import add_signals
from .universe import ETF, etf_maps, load_universe, names_for_codes
from .utils import ensure_dir, float_fmt, parse_date, pct_fmt, to_pipe_list


@dataclass
class BacktestResult:
    """Full backtest output tables and metadata."""

    nav: pd.DataFrame
    trades: pd.DataFrame
    positions: pd.DataFrame
    summary: PerformanceSummary
    target_history: dict[pd.Timestamp, list[str]]
    ranking_history: dict[pd.Timestamp, pd.DataFrame]
    features: pd.DataFrame
    paths: dict[str, Path] = field(default_factory=dict)


def prepare_features(prices: pd.DataFrame, cfg: ProjectConfig, pools: list[str] | None = None) -> tuple[pd.DataFrame, list[ETF]]:
    """Compute indicators and signals for configured ETF pools."""
    selected_pools = pools or ["broad_etf"]
    symbols = load_universe(cfg.universe, pools=selected_pools)
    codes = {item.code for item in symbols}
    scoped_prices = prices[prices["code"].isin(codes)].copy()
    if scoped_prices.empty:
        raise ValueError(f"No prices found for pools: {selected_pools}")
    features = compute_indicators(scoped_prices, cfg.strategy, symbols, premium=load_premium_cache(cfg))
    return add_signals(features, cfg.strategy), symbols


def _date_bounds(features: pd.DataFrame, start: str | None, end: str | None) -> list[pd.Timestamp]:
    """Resolve inclusive backtest dates from feature data."""
    dates = pd.to_datetime(features["date"]).drop_duplicates().sort_values()
    if start:
        dates = dates[dates >= parse_date(start)]
    if end and str(end).lower() != "latest":
        dates = dates[dates <= parse_date(end)]
    return [pd.Timestamp(dt).normalize() for dt in dates]


def _daily_returns(today_prices: pd.DataFrame) -> dict[str, float]:
    """Compute same-day open-to-close returns by code."""
    returns: dict[str, float] = {}
    for row in today_prices.itertuples(index=False):
        if float(row.open) <= 0:
            returns[str(row.code)] = 0.0
        else:
            returns[str(row.code)] = float(row.close) / float(row.open) - 1
    return returns


def _portfolio_return(weights: dict[str, float], returns: dict[str, float]) -> float:
    """Compute weighted portfolio return from code returns."""
    return sum(weight * returns.get(code, 0.0) for code, weight in weights.items())


def _record_trades(
    date_value: pd.Timestamp,
    signal_date: pd.Timestamp | None,
    before: dict[str, float],
    after: dict[str, float],
    today_prices: pd.DataFrame,
    code_map: dict[str, ETF],
) -> list[dict[str, object]]:
    """Create trade records from weight changes at the execution open."""
    price_map = {str(row.code): float(row.open) for row in today_prices.itertuples(index=False)}
    rows: list[dict[str, object]] = []
    for code, delta in weight_delta(before, after).items():
        if abs(delta) < 1e-12:
            continue
        rows.append(
            {
                "date": date_value,
                "signal_date": signal_date,
                "action": "BUY" if delta > 0 else "SELL",
                "code": code,
                "name": code_map[code].name if code in code_map else code,
                "weight_before": before.get(code, 0.0),
                "weight_after": after.get(code, 0.0),
                "price": price_map.get(code),
                "reason": "next_open_rebalance",
            }
        )
    return rows


def run_backtest(
    prices: pd.DataFrame,
    cfg: ProjectConfig,
    start: str | None = None,
    end: str | None = "latest",
    write_reports: bool = True,
) -> BacktestResult:
    """Run the daily close-signal, next-open-rebalance ETF rotation backtest."""
    features, symbols = prepare_features(prices, cfg, pools=["broad_etf"])
    code_map, _ = etf_maps(symbols)
    max_hold = int(cfg.universe.get("broad_etf", {}).get("max_hold", cfg.strategy.get("max_hold_broad", 2)))
    dates = _date_bounds(features, start, end)
    if not dates:
        raise ValueError("No backtest dates after applying start/end filters.")

    initial_nav = float(cfg.strategy.get("backtest", {}).get("initial_nav", 1.0))
    transaction_cost = float(cfg.strategy.get("backtest", {}).get("transaction_cost", 0.0005))
    annual_days = int(cfg.strategy.get("backtest", {}).get("annual_trading_days", 244))
    default_scale = float(cfg.strategy.get("position_control", {}).get("default_position", 0.5))

    nav = initial_nav
    control_nav = initial_nav
    peak = initial_nav
    control_peak = initial_nav
    current_strategy_weights: dict[str, float] = {}
    current_control_weights: dict[str, float] = {}
    current_position_scale = default_scale
    pending_target: list[str] = []
    pending_scale = default_scale
    pending_signal_date: pd.Timestamp | None = None
    previous_target: list[str] = []
    target_history: dict[pd.Timestamp, list[str]] = {}
    ranking_history: dict[pd.Timestamp, pd.DataFrame] = {}

    nav_rows: list[dict[str, object]] = []
    trade_rows: list[dict[str, object]] = []
    position_rows: list[dict[str, object]] = []

    for date_value in dates:
        today_prices = prices[prices["date"].eq(date_value) & prices["code"].isin(code_map)].copy()
        if today_prices.empty:
            continue

        new_strategy_weights = equal_weights(pending_target, 1.0)
        new_control_weights = equal_weights(pending_target, pending_scale)
        trade_rows.extend(
            _record_trades(
                date_value,
                pending_signal_date,
                current_control_weights,
                new_control_weights,
                today_prices,
                code_map,
            )
        )

        strategy_turnover = sum(abs(v) for v in weight_delta(current_strategy_weights, new_strategy_weights).values())
        control_turnover = sum(abs(v) for v in weight_delta(current_control_weights, new_control_weights).values())
        current_strategy_weights = new_strategy_weights
        current_control_weights = new_control_weights
        current_position_scale = pending_scale

        returns = _daily_returns(today_prices)
        daily_return = _portfolio_return(current_strategy_weights, returns) - strategy_turnover * transaction_cost
        control_daily_return = _portfolio_return(current_control_weights, returns) - control_turnover * transaction_cost
        nav *= 1 + daily_return
        control_nav *= 1 + control_daily_return
        peak = max(peak, nav)
        control_peak = max(control_peak, control_nav)
        dd = (nav / peak - 1) * 100 if peak else 0.0
        control_dd = (control_nav / control_peak - 1) * 100 if control_peak else 0.0

        for code, weight in current_control_weights.items():
            position_rows.append(
                {
                    "date": date_value,
                    "code": code,
                    "name": code_map[code].name if code in code_map else code,
                    "weight": weight,
                    "strategy_weight": current_strategy_weights.get(code, 0.0),
                    "position_scale": current_position_scale,
                }
            )

        latest_features = features[features["date"].eq(date_value)].copy()
        selection: SelectionResult = select_holdings(
            latest_features=latest_features,
            yesterday_holdings=previous_target,
            history_holdings=target_history,
            strategy=cfg.strategy,
            max_hold=max_hold,
        )
        target_history[date_value] = selection.target_holdings
        ranking_history[date_value] = selection.ranking_table
        previous_target = selection.target_holdings
        target_features = latest_features[latest_features["code"].isin(selection.target_holdings)]
        is_new_high = abs(dd) < 1e-12
        pending_scale, control_label = determine_control_position(
            dd,
            target_features,
            current_position_scale,
            is_new_high,
            cfg.strategy,
        )
        pending_target = selection.target_holdings
        pending_signal_date = date_value

        nav_rows.append(
            {
                "date": date_value,
                "nav": nav,
                "control_nav": control_nav,
                "daily_return": daily_return,
                "control_daily_return": control_daily_return,
                "drawdown": dd,
                "control_drawdown": control_dd,
                "position_scale": current_position_scale,
                "next_position_scale": pending_scale,
                "control_label": control_label,
                "target_holdings": to_pipe_list(names_for_codes(selection.target_holdings, code_map)),
            }
        )

    nav_df = pd.DataFrame(nav_rows)
    if not nav_df.empty:
        nav_df["date"] = pd.to_datetime(nav_df["date"]).dt.normalize()
        nav_df["drawdown"] = drawdown(nav_df["nav"])
        nav_df["control_drawdown"] = drawdown(nav_df["control_nav"])
    trades = pd.DataFrame(trade_rows)
    positions = pd.DataFrame(position_rows)
    summary = summarize_performance(nav_df, len(trades), annual_days)
    result = BacktestResult(nav_df, trades, positions, summary, target_history, ranking_history, features)
    if write_reports:
        result.paths = write_backtest_outputs(result, cfg)
    return result


def write_backtest_outputs(result: BacktestResult, cfg: ProjectConfig) -> dict[str, Path]:
    """Write backtest CSV, markdown summary, and NAV plot files."""
    ensure_dir(cfg.reports_dir)
    paths = {
        "summary": cfg.reports_dir / "backtest_summary.md",
        "nav": cfg.reports_dir / "backtest_nav.csv",
        "trades": cfg.reports_dir / "backtest_trades.csv",
        "positions": cfg.reports_dir / "backtest_positions.csv",
        "plot": cfg.reports_dir / "backtest_plot.png",
    }
    result.nav.to_csv(paths["nav"], index=False)
    result.trades.to_csv(paths["trades"], index=False)
    result.positions.to_csv(paths["positions"], index=False)
    paths["summary"].write_text(render_backtest_summary(result), encoding="utf-8")
    write_nav_plot(result.nav, paths["plot"])
    return paths


def render_backtest_summary(result: BacktestResult) -> str:
    """Render the markdown backtest summary."""
    summary = result.summary
    lines = [
        "# ETF轮动策略复现版回测摘要",
        "",
        "本回测仅用于研究，不构成投资建议，不接入实盘交易。",
        "",
        f"- 组合净值: {float_fmt(summary.nav)}",
        f"- 控仓法净值: {float_fmt(summary.control_nav)}",
        f"- 平均年化: {pct_fmt(summary.annual_return)}",
        f"- 控仓法平均年化: {pct_fmt(summary.control_annual_return)}",
        f"- 当前回撤: {pct_fmt(summary.current_drawdown)}",
        f"- 控仓法当前回撤: {pct_fmt(summary.control_current_drawdown)}",
        f"- 最大回撤: {pct_fmt(summary.max_drawdown)}",
        f"- 控仓法最大回撤: {pct_fmt(summary.control_max_drawdown)}",
        f"- 夏普值: {float_fmt(summary.sharpe, 2)}",
        f"- 控仓法夏普值: {float_fmt(summary.control_sharpe, 2)}",
        f"- 交易天数: {summary.trade_count}",
        f"- 考察天数: {summary.observation_days}",
        "",
        "## 年度收益",
        "",
    ]
    for year, value in summary.yearly_returns.items():
        control = summary.control_yearly_returns.get(year, 0.0)
        lines.append(f"- {year}: {pct_fmt(value)}，控仓法 {pct_fmt(control)}")
    return "\n".join(lines) + "\n"


def write_nav_plot(nav_df: pd.DataFrame, path: Path) -> None:
    """Write a NAV plot to PNG."""
    if nav_df.empty:
        return
    import os

    os.environ.setdefault("MPLCONFIGDIR", "/tmp/etf_rotation_matplotlib")
    ensure_dir(Path(os.environ["MPLCONFIGDIR"]))
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(nav_df["date"], nav_df["nav"], label="nav")
    ax.plot(nav_df["date"], nav_df["control_nav"], label="control_nav")
    ax.set_title("ETF Rotation NAV")
    ax.set_xlabel("Date")
    ax.set_ylabel("NAV")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)
