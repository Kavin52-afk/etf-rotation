"""Utility helpers shared across the ETF rotation project."""

from __future__ import annotations

from datetime import date, datetime
import json
from pathlib import Path
from typing import Iterable, Sequence

import pandas as pd


def ensure_dir(path: Path) -> Path:
    """Create a directory if it does not already exist and return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def parse_date(value: str | date | datetime | pd.Timestamp, latest: date | None = None) -> pd.Timestamp:
    """Parse a CLI date value, accepting the literal ``latest``."""
    if isinstance(value, pd.Timestamp):
        return value.normalize()
    if isinstance(value, datetime):
        return pd.Timestamp(value.date())
    if isinstance(value, date):
        return pd.Timestamp(value)
    if str(value).lower() == "latest":
        return pd.Timestamp(latest or date.today())
    return pd.Timestamp(str(value)).normalize()


def latest_available_date(dates: Iterable[pd.Timestamp]) -> pd.Timestamp:
    """Return the latest normalized date from an iterable."""
    date_index = pd.to_datetime(list(dates)).normalize()
    if len(date_index) == 0:
        raise ValueError("No available dates found.")
    return pd.Timestamp(date_index.max()).normalize()


def pct_fmt(value: float | int | None, digits: int = 2) -> str:
    """Format a number as a percentage string without changing scale."""
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):.{digits}f}%"


def float_fmt(value: float | int | None, digits: int = 3) -> str:
    """Format a float for reports."""
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):.{digits}f}"


def to_pipe_list(values: Sequence[str]) -> str:
    """Serialize a list of strings as a stable pipe-delimited value."""
    return "|".join(str(v) for v in values if str(v))


def from_pipe_list(value: object) -> list[str]:
    """Deserialize a JSON, pipe-delimited, or bracketed string list."""
    if value is None or pd.isna(value):
        return []
    text = str(value).strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                if parsed and isinstance(parsed[0], dict):
                    return [str(item.get("name") or item.get("clean_name") or item.get("code")) for item in parsed]
                return [str(item) for item in parsed]
        except json.JSONDecodeError:
            pass
    if "|" in text:
        return [item.strip() for item in text.split("|") if item.strip()]
    return [item.strip().strip("'\"") for item in text.strip("[]").replace("，", ",").split(",") if item.strip()]


def safe_round(value: object, digits: int = 2) -> float | str:
    """Round numeric values while preserving report placeholders."""
    try:
        if pd.isna(value):
            return "-"
        return round(float(value), digits)
    except (TypeError, ValueError):
        return "-"


def yyyymmdd(value: pd.Timestamp) -> str:
    """Format a timestamp as YYYYMMDD for data-provider APIs."""
    return pd.Timestamp(value).strftime("%Y%m%d")
