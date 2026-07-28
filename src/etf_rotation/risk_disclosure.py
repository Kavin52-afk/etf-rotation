"""Daily risk-disclosure generation for manual ETF execution."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .config import ProjectConfig
from .indicators import DOWN, WEAK
from .utils import ensure_dir


def _names_matching(risk_table: pd.DataFrame, mask: pd.Series, limit: int = 8) -> list[str]:
    """Return display names matching a risk mask."""
    if risk_table.empty:
        return []
    names = risk_table.loc[mask.fillna(False), "name"] if "name" in risk_table.columns else pd.Series(dtype=str)
    return [str(item) for item in names.head(limit).tolist()]


def render_risk_notice(
    report_date: pd.Timestamp,
    risk_table: pd.DataFrame,
    turnover_estimate: int,
) -> str:
    """Render the daily manual-execution risk notice."""
    date_text = pd.Timestamp(report_date).strftime("%Y-%m-%d")
    qdii_names = _names_matching(risk_table, risk_table.get("qdii", pd.Series(False, index=risk_table.index)).map(bool))
    weak_mask = risk_table.get("market_signal", pd.Series("", index=risk_table.index)).astype(str).eq(WEAK)
    down_mask = risk_table.get("trend", pd.Series("", index=risk_table.index)).astype(str).eq(DOWN)
    reversal_names = _names_matching(risk_table, weak_mask | down_mask)
    turnover_level = "HIGH" if turnover_estimate >= 2 else "NORMAL" if turnover_estimate == 1 else "LOW"

    lines = [
        "# Daily Risk Notice",
        "",
        f"- date: {date_text}",
        f"- turnover_estimate: {turnover_estimate}",
        f"- turnover_risk_level: {turnover_level}",
        "",
        "## QDII Premium Risk",
        "",
        "QDII ETF may trade at a premium/discount to indicative net value. Manual execution must check current premium, suspension status, and cross-market trading calendar before placing any order.",
        f"- QDII candidates in current universe snapshot: {qdii_names or '-'}",
        "",
        "## Trend Reversal Risk",
        "",
        "Trend labels and B/S signals are rule-based summaries, not predictions. A recent uptrend can reverse before the next open.",
        f"- Weak/down candidates in current snapshot: {reversal_names or '-'}",
        "",
        "## High Turnover Risk",
        "",
        "Higher turnover can increase slippage, taxes/fees, and execution error. The workbench caps broad ETF changes and requires human review before marking execution.",
        "",
        "## Model Non-Predictive Statement",
        "",
        "This system is a deterministic decision aid based on historical prices and rule filters. It does not forecast returns and does not guarantee execution price, liquidity, or future performance.",
        "",
    ]
    return "\n".join(lines)


def write_risk_notice(
    cfg: ProjectConfig,
    report_date: pd.Timestamp,
    risk_table: pd.DataFrame,
    turnover_estimate: int,
) -> Path:
    """Write the daily risk notice markdown."""
    ensure_dir(cfg.reports_dir)
    path = cfg.reports_dir / f"risk_notice_{pd.Timestamp(report_date).strftime('%Y-%m-%d')}.md"
    path.write_text(render_risk_notice(report_date, risk_table, turnover_estimate), encoding="utf-8")
    return path
