"""Append-only execution audit log for human-in-the-loop workflows."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

import pandas as pd

from .config import ProjectConfig
from .utils import ensure_dir, parse_date


def execution_log_path(cfg: ProjectConfig) -> Path:
    """Return the append-only execution log path."""
    return cfg.project_root / "data" / "processed" / "execution_log.jsonl"


def utc_now_iso() -> str:
    """Return a UTC timestamp string."""
    return datetime.now(timezone.utc).isoformat()


def decision_latency_seconds(signal_time: str, decision_time: str) -> float:
    """Return latency between signal freeze and human decision in seconds."""
    try:
        start = datetime.fromisoformat(signal_time)
        end = datetime.fromisoformat(decision_time)
    except ValueError:
        return 0.0
    return max(0.0, (end - start).total_seconds())


def append_execution_log(
    cfg: ProjectConfig,
    *,
    event: str,
    execution_id: str,
    signal_date: str,
    signal_time: str,
    decision_time: str,
    execution_time: str | None,
    ignored_signals: list[str],
    executed_signals: list[str],
    rejected_signals: list[str],
    status: str,
    trade_sheet: str,
    risk_notice: str,
) -> Path:
    """Append one execution workflow event to JSONL."""
    path = execution_log_path(cfg)
    ensure_dir(path.parent)
    row: dict[str, Any] = {
        "event": event,
        "execution_id": execution_id,
        "signal_date": signal_date,
        "signal_time": signal_time,
        "decision_time": decision_time,
        "execution_time": execution_time or "",
        "decision_latency": decision_latency_seconds(signal_time, decision_time),
        "ignored_signals": ignored_signals,
        "executed_signals": executed_signals,
        "rejected_signals": rejected_signals,
        "status": status,
        "trade_sheet": trade_sheet,
        "risk_notice": risk_notice,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def read_execution_log(cfg: ProjectConfig, start: str | None = None, end: str | None = "latest") -> pd.DataFrame:
    """Read execution log rows filtered by signal_date."""
    path = execution_log_path(cfg)
    if not path.exists():
        return pd.DataFrame()
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            rows.append(json.loads(text))
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    frame["signal_date"] = pd.to_datetime(frame["signal_date"]).dt.normalize()
    if start:
        frame = frame[frame["signal_date"] >= parse_date(start)]
    if end and str(end).lower() != "latest":
        frame = frame[frame["signal_date"] <= parse_date(end)]
    return frame.sort_values(["signal_date", "decision_time"]).reset_index(drop=True)
