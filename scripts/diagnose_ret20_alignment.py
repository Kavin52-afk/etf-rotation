"""Diagnose which ret20 convention best matches source-strategy labels."""

from __future__ import annotations

from dataclasses import dataclass
import math
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from etf_rotation.config import load_project_config
from etf_rotation.data_provider import load_prices
from etf_rotation.utils import ensure_dir


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOC_ROWS_PATH = PROJECT_ROOT / "data" / "labels" / "doc_rows.csv"
MANUAL_TARGETS_PATH = PROJECT_ROOT / "data" / "labels" / "manual_ret20_targets.csv"
REPORT_PATH = PROJECT_ROOT / "data" / "reports" / "ret20_alignment_report.md"
DETAIL_PATH = PROJECT_ROOT / "data" / "reports" / "ret20_alignment_details.csv"


@dataclass(frozen=True)
class Hypothesis:
    """One ret20 calculation convention."""

    price_field: str
    window: int
    signal_offset: int


@dataclass(frozen=True)
class CodeSeries:
    """Cached price arrays for one symbol."""

    dates: list[pd.Timestamp]
    fields: dict[str, list[float]]
    index_by_date: dict[pd.Timestamp, int]


def _load_targets() -> pd.DataFrame:
    """Load parsed DOCX rows and optional manual targets."""
    frames: list[pd.DataFrame] = []
    if DOC_ROWS_PATH.exists():
        rows = pd.read_csv(DOC_ROWS_PATH)
        rows = rows[rows["module"].astype(str).eq("broad")].copy()
        rows = rows[["date", "module", "name", "code_if_found", "ret20_pct"]].rename(
            columns={"code_if_found": "code"}
        )
        rows["source"] = "doc_rows"
        frames.append(rows)
    if MANUAL_TARGETS_PATH.exists():
        manual = pd.read_csv(MANUAL_TARGETS_PATH)
        manual = manual[["date", "module", "name", "code", "ret20_pct"]].copy()
        manual["source"] = "manual"
        frames.append(manual)
    if not frames:
        raise FileNotFoundError("No ret20 target labels found.")
    targets = pd.concat(frames, ignore_index=True)
    targets["date"] = pd.to_datetime(targets["date"]).dt.normalize()
    targets["ret20_pct"] = pd.to_numeric(targets["ret20_pct"], errors="coerce")
    targets = targets.dropna(subset=["date", "code", "ret20_pct"])
    return targets[targets["code"].astype(str).ne("")].reset_index(drop=True)


def _build_price_cache(prices: pd.DataFrame) -> dict[str, CodeSeries]:
    """Build fast lookup structures for repeated hypothesis evaluation."""
    cache: dict[str, CodeSeries] = {}
    for code, frame in prices.sort_values(["code", "date"]).groupby("code", sort=False):
        dates = [pd.Timestamp(dt).normalize() for dt in frame["date"].tolist()]
        fields = {
            field: pd.to_numeric(frame[field], errors="coerce").astype(float).tolist()
            for field in ["open", "high", "low", "close"]
            if field in frame.columns
        }
        cache[str(code)] = CodeSeries(
            dates=dates,
            fields=fields,
            index_by_date={date: idx for idx, date in enumerate(dates)},
        )
    return cache


def _signal_date_for(report_date: pd.Timestamp, trading_dates: list[pd.Timestamp], offset: int) -> pd.Timestamp | None:
    """Return the trading date offset from the report date."""
    available = [date for date in trading_dates if date <= report_date]
    if not available:
        return None
    idx = len(available) - 1 + offset
    if idx < 0 or idx >= len(available):
        return None
    return available[idx]


def _ret_for(cache: dict[str, CodeSeries], code: str, signal_date: pd.Timestamp, field: str, window: int) -> tuple[float, str, float, float] | None:
    """Calculate one return and expose the base date and prices."""
    series = cache.get(str(code))
    if series is None or field not in series.fields:
        return None
    idx = series.index_by_date.get(pd.Timestamp(signal_date).normalize())
    if idx is None:
        return None
    base_idx = idx - window
    if base_idx < 0:
        return None
    values = series.fields[field]
    current = float(values[idx])
    base = float(values[base_idx])
    if base <= 0:
        return None
    value = (current / base - 1) * 100
    return value, series.dates[base_idx].strftime("%Y-%m-%d"), current, base


def _evaluate(
    price_cache: dict[str, CodeSeries],
    trading_dates: list[pd.Timestamp],
    targets: pd.DataFrame,
    hypothesis: Hypothesis,
) -> pd.DataFrame:
    """Evaluate one hypothesis across all targets."""
    records: list[dict[str, object]] = []
    for row in targets.itertuples(index=False):
        report_date = pd.Timestamp(row.date).normalize()
        signal_date = _signal_date_for(report_date, trading_dates, hypothesis.signal_offset)
        if signal_date is None:
            continue
        result = _ret_for(price_cache, str(row.code), signal_date, hypothesis.price_field, hypothesis.window)
        if result is None:
            continue
        predicted, base_date, current_price, base_price = result
        error = predicted - float(row.ret20_pct)
        records.append(
            {
                "source": row.source,
                "module": row.module,
                "report_date": report_date.strftime("%Y-%m-%d"),
                "signal_date": signal_date.strftime("%Y-%m-%d"),
                "base_date": base_date,
                "code": row.code,
                "name": row.name,
                "target_ret20_pct": float(row.ret20_pct),
                "predicted_ret20_pct": predicted,
                "error": error,
                "abs_error": abs(error),
                "squared_error": error * error,
                "price_field": hypothesis.price_field,
                "window": hypothesis.window,
                "signal_offset": hypothesis.signal_offset,
                "current_price": current_price,
                "base_price": base_price,
            }
        )
    return pd.DataFrame(records)


def _summarize(details: pd.DataFrame) -> pd.DataFrame:
    """Summarize hypothesis performance."""
    if details.empty:
        return pd.DataFrame()
    group_cols = ["source", "module", "price_field", "window", "signal_offset"]
    grouped = details.groupby(group_cols, dropna=False).agg(
        count=("error", "size"),
        mae=("abs_error", "mean"),
        rmse=("squared_error", lambda value: math.sqrt(float(value.mean()))),
        median_abs_error=("abs_error", "median"),
        max_abs_error=("abs_error", "max"),
    )
    return grouped.reset_index().sort_values(["source", "module", "rmse", "mae"]).reset_index(drop=True)


def _render_report(summary: pd.DataFrame, details: pd.DataFrame, targets: pd.DataFrame) -> str:
    """Render the markdown diagnostics report."""
    lines = [
        "# ret20 Alignment Diagnostics",
        "",
        "This report tests ret20 hypotheses against parsed DOCX labels and manual source-text targets.",
        "",
        "Formula tested:",
        "",
        "`ret = (price[t] / price[t-window] - 1) * 100`",
        "",
        "Hypothesis dimensions:",
        "",
        "- `price_field`: close/open/high/low",
        "- `window`: 5 to 40 trading rows",
        "- `signal_offset`: 0 means report-date trading row, -1 means previous trading row",
        "",
        f"- target rows: {len(targets)}",
        f"- evaluated rows: {len(details)}",
        "",
        "## Best Hypotheses",
        "",
    ]
    if summary.empty:
        lines.append("No hypothesis could be evaluated.")
        return "\n".join(lines) + "\n"

    for (source, module), group in summary.groupby(["source", "module"], sort=False):
        lines.extend([f"### {source} / {module}", ""])
        show = group.head(10).copy()
        for col in ["mae", "rmse", "median_abs_error", "max_abs_error"]:
            show[col] = show[col].map(lambda value: f"{float(value):.3f}")
        lines.append(show.to_markdown(index=False))
        lines.append("")

    lines.extend(["## Current Strict Formula Snapshot", ""])
    strict = summary[
        summary["price_field"].eq("close")
        & summary["window"].eq(20)
        & summary["signal_offset"].eq(-1)
    ].copy()
    if strict.empty:
        lines.append("No strict close/window20/previous-day hypothesis rows.")
    else:
        for col in ["mae", "rmse", "median_abs_error", "max_abs_error"]:
            strict[col] = strict[col].map(lambda value: f"{float(value):.3f}")
        lines.append(strict.to_markdown(index=False))
    lines.append("")

    lines.extend(["## Worst Rows For Strict Formula", ""])
    strict_details = details[
        details["price_field"].eq("close")
        & details["window"].eq(20)
        & details["signal_offset"].eq(-1)
    ].copy()
    if strict_details.empty:
        lines.append("No strict details.")
    else:
        cols = [
            "source",
            "module",
            "report_date",
            "signal_date",
            "base_date",
            "name",
            "code",
            "target_ret20_pct",
            "predicted_ret20_pct",
            "error",
        ]
        show = strict_details.sort_values("abs_error", ascending=False).head(20)[cols].copy()
        for col in ["target_ret20_pct", "predicted_ret20_pct", "error"]:
            show[col] = show[col].map(lambda value: f"{float(value):.2f}")
        lines.append(show.to_markdown(index=False))
    lines.append("")
    lines.extend(
        [
            "## Interpretation Checklist",
            "",
            "- If one global hypothesis wins consistently, promote it to strategy config.",
            "- If manual source-text samples want a different best hypothesis than historical DOCX rows, do not tune only to a single day.",
            "- If no global hypothesis is stable, the remaining gap is likely source price data, adjusted series, or mixed field/date cutoffs.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    """Run ret20 diagnostics."""
    cfg = load_project_config(PROJECT_ROOT)
    prices = load_prices(cfg)
    prices = prices.copy()
    prices["date"] = pd.to_datetime(prices["date"]).dt.normalize()
    price_cache = _build_price_cache(prices)
    trading_dates = sorted(pd.Timestamp(dt).normalize() for dt in prices["date"].drop_duplicates())
    targets = _load_targets()

    frames: list[pd.DataFrame] = []
    for field in ["close", "open", "high", "low"]:
        for window in range(5, 41):
            for offset in [0, -1, -2]:
                frames.append(_evaluate(price_cache, trading_dates, targets, Hypothesis(field, window, offset)))
    details = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    summary = _summarize(details)

    ensure_dir(REPORT_PATH.parent)
    details.to_csv(DETAIL_PATH, index=False)
    REPORT_PATH.write_text(_render_report(summary, details, targets), encoding="utf-8")
    print(f"ret20 detail CSV written: {DETAIL_PATH}")
    print(f"ret20 report written: {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
