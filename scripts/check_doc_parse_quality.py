"""Generate a quality report for parsed source DOCX labels and rows."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LABELS_PATH = PROJECT_ROOT / "data" / "labels" / "doc_labels.csv"
ROWS_PATH = PROJECT_ROOT / "data" / "labels" / "doc_rows.csv"
REPORT_PATH = PROJECT_ROOT / "data" / "reports" / "doc_parse_quality_report.md"


def _load_json(value: Any, default: Any) -> Any:
    """Load a JSON CSV cell with a fallback."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return default
    text = str(value).strip()
    if not text:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default


def _as_bool(value: Any) -> bool:
    """Coerce bool-like CSV values."""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes"}


def _row_for(labels: pd.DataFrame, date: str) -> pd.Series | None:
    """Return one label row by date."""
    matched = labels[labels["date"].astype(str).eq(date)]
    return matched.iloc[0] if not matched.empty else None


def _rows_for(rows: pd.DataFrame, date: str) -> pd.DataFrame:
    """Return broad ETF rows for one date."""
    return rows[rows["date"].astype(str).eq(date) & rows["module"].astype(str).eq("broad")].copy()


def _same_list(actual: list[str], expected: list[str]) -> bool:
    """Compare ordered clean-name lists."""
    return actual == expected


def _same_set(actual: list[str], expected: list[str]) -> bool:
    """Compare clean-name sets."""
    return set(actual) == set(expected)


def _approx(actual: Any, expected: float, tolerance: float = 0.15) -> bool:
    """Compare a numeric value with tolerance."""
    try:
        return abs(float(actual) - expected) <= tolerance
    except (TypeError, ValueError):
        return False


def _signals_include(signals: list[dict[str, str]], code: str, name: str) -> bool:
    """Return whether parsed signals include one code/name pair."""
    return any(item.get("code") == code and item.get("name") == name for item in signals)


def _check_row(
    rows: pd.DataFrame,
    date: str,
    name: str,
    expected: dict[str, Any],
    failures: list[str],
) -> None:
    """Check one parsed single-ETF row."""
    matched = _rows_for(rows, date)
    matched = matched[matched["name"].astype(str).eq(name)]
    if matched.empty:
        failures.append(f"{date} missing row: {name}")
        return
    row = matched.iloc[0]
    for field, expected_value in expected.items():
        actual = row.get(field)
        if field in {"ret20_pct", "pb", "bias_pct", "current_drawdown_pct"}:
            if not _approx(actual, float(expected_value)):
                failures.append(f"{date} {name}.{field}: expected approx {expected_value}, got {actual}")
        elif actual != expected_value:
            failures.append(f"{date} {name}.{field}: expected {expected_value}, got {actual}")


def _check_anchor(labels: pd.DataFrame, rows: pd.DataFrame, date: str, spec: dict[str, Any]) -> tuple[bool, list[str]]:
    """Check one anchor date and return pass/failure details."""
    failures: list[str] = []
    label = _row_for(labels, date)
    if label is None:
        return False, [f"{date} missing from doc_labels.csv"]

    broad_valid = _as_bool(label.get("broad_valid"))
    if "broad_valid" in spec and broad_valid != spec["broad_valid"]:
        failures.append(f"{date} broad_valid: expected {spec['broad_valid']}, got {broad_valid}")

    yesterday = _load_json(label.get("yesterday_holdings"), [])
    target = _load_json(label.get("target_holdings"), [])
    added = _load_json(label.get("added_names"), [])
    removed = _load_json(label.get("removed_names"), [])
    buy_signals = _load_json(label.get("buy_signals"), [])
    sell_signals = _load_json(label.get("sell_signals"), [])

    if "yesterday_holdings" in spec and not _same_set(yesterday, spec["yesterday_holdings"]):
        failures.append(f"{date} yesterday_holdings: expected {spec['yesterday_holdings']}, got {yesterday}")
    if "target_holdings" in spec:
        comparator = _same_list if spec.get("target_ordered", False) else _same_set
        if not comparator(target, spec["target_holdings"]):
            failures.append(f"{date} target_holdings: expected {spec['target_holdings']}, got {target}")
    if "added_names" in spec and not set(spec["added_names"]).issubset(set(added)):
        failures.append(f"{date} added_names: expected contains {spec['added_names']}, got {added}")
    if "removed_names" in spec and not set(spec["removed_names"]).issubset(set(removed)):
        failures.append(f"{date} removed_names: expected contains {spec['removed_names']}, got {removed}")
    if "position_state" in spec and label.get("position_state") != spec["position_state"]:
        failures.append(f"{date} position_state: expected {spec['position_state']}, got {label.get('position_state')}")
    if "add_position_signal" in spec and _as_bool(label.get("add_position_signal")) != spec["add_position_signal"]:
        failures.append(
            f"{date} add_position_signal: expected {spec['add_position_signal']}, got {label.get('add_position_signal')}"
        )
    if "current_drawdown_pct" in spec and not _approx(label.get("current_drawdown_pct"), spec["current_drawdown_pct"]):
        failures.append(
            f"{date} current_drawdown_pct: expected approx {spec['current_drawdown_pct']}, got {label.get('current_drawdown_pct')}"
        )
    if "buy_signal" in spec:
        code, name = spec["buy_signal"]
        if not _signals_include(buy_signals, code, name):
            failures.append(f"{date} buy_signals: expected {code}({name}), got {buy_signals}")
    if spec.get("buy_empty") and buy_signals:
        failures.append(f"{date} buy_signals: expected empty, got {buy_signals}")
    if "sell_signal" in spec:
        code, name = spec["sell_signal"]
        if not _signals_include(sell_signals, code, name):
            failures.append(f"{date} sell_signals: expected {code}({name}), got {sell_signals}")
    if spec.get("sell_empty") and sell_signals:
        failures.append(f"{date} sell_signals: expected empty, got {sell_signals}")

    for name, row_spec in spec.get("rows", {}).items():
        _check_row(rows, date, name, row_spec, failures)

    if spec.get("target_empty") and target:
        failures.append(f"{date} target_holdings: expected empty, got {target}")
    return not failures, failures


def main() -> int:
    """Generate the quality report and print its path."""
    if not LABELS_PATH.exists() or not ROWS_PATH.exists():
        raise FileNotFoundError("doc_labels.csv/doc_rows.csv do not exist. Run parse-doc first.")

    labels = pd.read_csv(LABELS_PATH)
    rows = pd.read_csv(ROWS_PATH)
    labels["date"] = labels["date"].astype(str)
    rows["date"] = rows["date"].astype(str)
    broad_rows = rows[rows["module"].astype(str).eq("broad")]
    invalid_dates = labels.loc[~labels["broad_valid"].map(_as_bool), "date"].tolist()

    anchors: dict[str, dict[str, Any]] = {
        "2026-06-26": {
            "broad_valid": True,
            "yesterday_holdings": ["日经225", "科创50"],
            "target_holdings": ["日经225", "科创50"],
            "position_state": "half",
            "buy_signal": ("159338.SZ", "中证A500"),
            "sell_empty": True,
            "rows": {
                "日经225": {"pb": 1.06, "ret20_pct": 22.4, "mark": "√√√"},
                "科创50": {"pb": 1.0, "ret20_pct": 14.9, "mark": "√√√"},
                "创业板50": {"ret20_pct": 10.6, "mark": "×××"},
                "纳指": {"pb": 1.09, "ret20_pct": 4.6, "mark": "×××"},
            },
        },
        "2026-06-23": {
            "broad_valid": True,
            "yesterday_holdings": ["日经225", "科创50"],
            "target_holdings": ["日经225", "创业板50"],
            "added_names": ["创业板50"],
            "removed_names": ["科创50"],
            "position_state": "full",
            "buy_signal": ("159338.SZ", "中证A500"),
            "sell_signal": ("164824.SZ", "印度"),
            "rows": {
                "日经225": {"mark": "√√√"},
                "创业板50": {"mark": "××√"},
                "科创50": {"mark": "×√×"},
                "纳指": {"mark": "√××"},
            },
        },
        "2026-06-22": {
            "broad_valid": True,
            "yesterday_holdings": ["日经225", "纳指"],
            "target_holdings": ["日经225", "科创50"],
            "added_names": ["科创50"],
            "removed_names": ["纳指"],
            "position_state": "full",
            "rows": {
                "日经225": {"mark": "√√√"},
                "科创50": {"mark": "××√"},
                "创业板50": {"mark": "×××"},
                "纳指": {"mark": "√√×"},
            },
        },
        "2026-06-15": {
            "broad_valid": True,
            "add_position_signal": True,
            "yesterday_holdings": ["日经225", "纳指"],
            "target_holdings": ["纳指", "日经225"],
            "target_ordered": True,
            "position_state": "full",
            "current_drawdown_pct": -6.81,
            "rows": {
                "日经225": {"mark": "√√√", "ret20_pct": 8.0},
                "纳指": {"mark": "√√√", "ret20_pct": 3.8},
            },
        },
        "2026-06-10": {
            "broad_valid": False,
            "target_empty": True,
        },
        "2026-05-29": {
            "broad_valid": True,
        },
        "2026-05-20": {
            "broad_valid": True,
            "yesterday_holdings": ["科创50", "创业板50"],
            "target_holdings": ["创业板50", "纳指"],
            "added_names": ["纳指"],
            "removed_names": ["科创50"],
            "rows": {
                "科创50": {"mark": "√√×", "ret20_pct": 30.4},
                "创业板50": {"mark": "√√√", "ret20_pct": 15.1},
                "纳指": {"mark": "××√", "ret20_pct": 12.6},
            },
        },
    }

    anchor_results: list[tuple[str, bool, list[str]]] = []
    for date, spec in anchors.items():
        passed, failures = _check_anchor(labels, rows, date, spec)
        anchor_results.append((date, passed, failures))

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# DOCX解析质量报告",
        "",
        f"- doc_labels.csv 行数: {len(labels)}",
        f"- doc_rows.csv 行数: {len(rows)}",
        f"- broad ETF 单品种记录数量: {len(broad_rows)}",
        f"- 日期范围: {labels['date'].min()} 到 {labels['date'].max()}",
        f"- 有效 broad ETF 标签数量: {int(labels['broad_valid'].map(_as_bool).sum())}",
        f"- broad_valid=false 的日期列表: {invalid_dates}",
        "",
        "## 锚点校验",
        "",
    ]
    for date, passed, failures in anchor_results:
        lines.append(f"- {date}: {'PASS' if passed else 'FAIL'}")
        for failure in failures:
            lines.append(f"  - {failure}")
    lines.extend(["", "## 前10条 label", "", labels.head(10).to_markdown(index=False), "", "## 后10条 label", "", labels.tail(10).to_markdown(index=False), ""])
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"quality report written: {REPORT_PATH}")
    all_passed = all(passed for _, passed, _ in anchor_results)
    print(f"anchors all passed: {all_passed}")
    return 0 if all_passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
