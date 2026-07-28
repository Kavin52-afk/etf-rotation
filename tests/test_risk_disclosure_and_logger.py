from __future__ import annotations

import pandas as pd

from etf_rotation.config import ProjectConfig
from etf_rotation.execution_logger import append_execution_log, read_execution_log
from etf_rotation.risk_disclosure import render_risk_notice


def test_render_risk_notice_contains_required_sections() -> None:
    risk_table = pd.DataFrame(
        [
            {"name": "纳指", "qdii": True, "market_signal": "★", "trend": "↗"},
            {"name": "科创50", "qdii": False, "market_signal": "●", "trend": "↘"},
        ]
    )

    notice = render_risk_notice(pd.Timestamp("2026-06-26"), risk_table, turnover_estimate=1)

    assert "QDII Premium Risk" in notice
    assert "Trend Reversal Risk" in notice
    assert "High Turnover Risk" in notice
    assert "Model Non-Predictive Statement" in notice


def test_execution_logger_appends_and_reads_jsonl(tmp_path) -> None:
    cfg = ProjectConfig(project_root=tmp_path, universe={}, strategy={}, data={})
    append_execution_log(
        cfg,
        event="manual_execution_decision",
        execution_id="EXE-1",
        signal_date="2026-06-26",
        signal_time="2026-06-26T00:00:00+00:00",
        decision_time="2026-06-26T00:01:00+00:00",
        execution_time="",
        ignored_signals=[],
        executed_signals=["A"],
        rejected_signals=[],
        status="executed",
        trade_sheet="sheet.csv",
        risk_notice="notice.md",
    )

    rows = read_execution_log(cfg, start="2026-01-01", end="latest")

    assert len(rows) == 1
    assert rows.iloc[0]["execution_id"] == "EXE-1"
    assert rows.iloc[0]["decision_latency"] == 60.0
