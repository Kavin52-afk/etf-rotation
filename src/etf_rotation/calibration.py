"""Calibration report against parsed source-document labels."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from .backtest import prepare_features, run_backtest
from .config import ProjectConfig
from .metrics import exact_match, hit_ratio, turnover_diff
from .strategy_pipeline import layer1_targets, layer2_targets, run_strategy_pipeline
from .universe import etf_maps, load_universe, normalize_name, names_for_codes
from .utils import ensure_dir, float_fmt, from_pipe_list, pct_fmt


def _as_bool(value: Any) -> bool:
    """Coerce CSV bool-like values."""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes"}


def _resolve_strategy_date(
    date_value: pd.Timestamp,
    target_history: dict[pd.Timestamp, list[str]],
) -> pd.Timestamp | None:
    """Resolve the latest strategy signal date on or before a label date."""
    dates = sorted(dt for dt in target_history if dt <= date_value)
    return dates[-1] if dates else None


def _resolve_strategy_names(
    date_value: pd.Timestamp,
    target_history: dict[pd.Timestamp, list[str]],
    code_map: dict,
) -> tuple[pd.Timestamp | None, list[str]]:
    """Resolve strategy target names on or before a label date."""
    strategy_date = _resolve_strategy_date(date_value, target_history)
    if strategy_date is None:
        return None, []
    return strategy_date, names_for_codes(target_history[strategy_date], code_map)


def _strategy_top5(date_value: pd.Timestamp, ranking_history: dict[pd.Timestamp, pd.DataFrame]) -> pd.DataFrame:
    """Return top-five strategy ranking rows on or before a label date."""
    dates = sorted(dt for dt in ranking_history if dt <= date_value)
    if not dates:
        return pd.DataFrame()
    ranking = ranking_history[dates[-1]].copy()
    columns = ["name", "code", "ret20_pct", "bias_pct", "trend", "market_signal", "convex", "premium_pb", "score"]
    for column in columns:
        if column not in ranking.columns:
            ranking[column] = None
    return ranking.sort_values(["score", "ret20_pct"], ascending=[False, False]).head(5)[columns]


def _doc_top5(date_text: str, doc_rows: pd.DataFrame) -> pd.DataFrame:
    """Return the source-document top-five broad ETF rows for a label date."""
    if doc_rows.empty:
        return pd.DataFrame()
    rows = doc_rows[
        doc_rows["date"].astype(str).eq(date_text) & doc_rows["module"].astype(str).eq("broad")
    ].copy()
    if rows.empty:
        return pd.DataFrame()
    sort_col = "row_order" if "row_order" in rows.columns else rows.index.name
    if sort_col:
        rows = rows.sort_values(sort_col)
    columns = ["name", "code_if_found", "mark", "pb", "ret20_pct", "bias_pct", "trend", "market_signal", "convex"]
    for column in columns:
        if column not in rows.columns:
            rows[column] = None
    return rows.head(5)[columns]


def _markdown_table(frame: pd.DataFrame) -> str:
    """Render a compact markdown table for report details."""
    if frame.empty:
        return "_无_"
    numeric_columns = [col for col in frame.columns if pd.api.types.is_numeric_dtype(frame[col])]
    table = frame.copy()
    for column in numeric_columns:
        table[column] = table[column].map(lambda value: float_fmt(value, 2))
    return table.to_markdown(index=False)


def _period_stats(rows: list[dict[str, Any]], start: str, end: str) -> dict[str, float | int]:
    """Compute calibration stats for one date range."""
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    selected = [row for row in rows if start_ts <= pd.Timestamp(row["date"]) <= end_ts]
    if not selected:
        return {"count": 0, "exact_rate": 0.0, "average_hit_ratio": 0.0}
    return {
        "count": len(selected),
        "exact_rate": sum(1 for row in selected if row["exact_match"]) / len(selected) * 100,
        "average_hit_ratio": sum(float(row["hit_ratio"]) for row in selected) / len(selected) * 100,
    }


def run_calibration(
    labels_path: Path,
    prices: pd.DataFrame,
    cfg: ProjectConfig,
    data_note: str = "",
) -> Path:
    """Compare strategy targets with parsed source-document labels and write markdown."""
    if not labels_path.exists():
        raise FileNotFoundError(f"Label CSV not found: {labels_path}")
    labels = pd.read_csv(labels_path)
    if labels.empty:
        raise ValueError(f"Label CSV is empty: {labels_path}")
    labels["date"] = pd.to_datetime(labels["date"]).dt.normalize()
    labels["broad_valid"] = labels.get("broad_valid", True)
    valid_labels = labels[labels["broad_valid"].map(_as_bool)].copy()
    if valid_labels.empty:
        raise ValueError("No valid broad ETF labels found for calibration.")

    doc_rows_path = labels_path.parent / "doc_rows.csv"
    doc_rows = pd.read_csv(doc_rows_path) if doc_rows_path.exists() else pd.DataFrame()
    if not doc_rows.empty:
        doc_rows["date"] = doc_rows["date"].astype(str)

    end = valid_labels["date"].max().strftime("%Y-%m-%d")
    result = run_backtest(prices, cfg, start=None, end=end, write_reports=False)
    code_map, _ = etf_maps(load_universe(cfg.universe, pools=["broad_etf"]))

    rows: list[dict[str, Any]] = []
    mismatches: list[dict[str, Any]] = []
    total_expected = 0
    total_hits = 0
    for label in valid_labels.sort_values("date").itertuples(index=False):
        date_value = pd.Timestamp(label.date).normalize()
        date_text = date_value.strftime("%Y-%m-%d")
        expected = [normalize_name(item) for item in from_pipe_list(label.target_holdings)]
        yesterday_expected = [normalize_name(item) for item in from_pipe_list(label.yesterday_holdings)]
        strategy_date, actual = _resolve_strategy_names(date_value, result.target_history, code_map)
        exact = exact_match(expected, actual)
        hit = hit_ratio(expected, actual)
        hits = len(set(expected) & set(actual))
        total_hits += hits
        total_expected += len(set(expected))
        row = {
            "date": date_text,
            "strategy_date": strategy_date.strftime("%Y-%m-%d") if strategy_date is not None else "",
            "expected": expected,
            "actual": actual,
            "exact_match": exact,
            "hit_ratio": hit,
            "turnover_diff": turnover_diff(yesterday_expected, expected, actual),
            "strategy_top5": _strategy_top5(date_value, result.ranking_history),
            "doc_top5": _doc_top5(date_text, doc_rows),
        }
        rows.append(row)
        if not exact:
            mismatches.append(row)

    label_total = len(labels)
    valid_total = len(valid_labels)
    coverage = len(rows)
    exact_rate = sum(1 for row in rows if row["exact_match"]) / coverage * 100 if coverage else 0.0
    avg_hit = sum(float(row["hit_ratio"]) for row in rows) / coverage * 100 if coverage else 0.0
    single_hit = total_hits / total_expected * 100 if total_expected else 0.0
    periods = {
        "2026-05-12 到 2026-05-31": _period_stats(rows, "2026-05-12", "2026-05-31"),
        "2026-06-01 到 2026-06-26": _period_stats(rows, "2026-06-01", "2026-06-26"),
    }

    lines = [
        "# 原始文档校准报告",
        "",
        "本报告比较复现策略生成的 target holdings 与原始文档“今日收盘组合应持仓”。",
        "",
    ]
    if data_note:
        lines.extend([f"> {data_note}", ""])
    lines.extend(
        [
            "## 总览",
            "",
            f"- 标签总日期数: {label_total}",
            f"- 有效 broad 标签数: {valid_total}",
            f"- 校准覆盖日期数: {coverage}",
            f"- exact_match: {pct_fmt(exact_rate)}",
            f"- average_hit_ratio: {pct_fmt(avg_hit)}",
            f"- 单只 ETF 命中率: {pct_fmt(single_hit)}",
            f"- 不匹配日期数量: {len(mismatches)}",
            f"- 不匹配日期列表: {[row['date'] for row in mismatches]}",
            "",
            "## 分阶段统计",
            "",
        ]
    )
    for period, stats in periods.items():
        lines.append(
            f"- {period}: count={stats['count']}, exact_match={pct_fmt(float(stats['exact_rate']))}, "
            f"average_hit_ratio={pct_fmt(float(stats['average_hit_ratio']))}"
        )

    lines.extend(["", "## 不匹配日期明细", ""])
    if not mismatches:
        lines.append("全部匹配。")
    else:
        for item in mismatches:
            lines.extend(
                [
                    f"### {item['date']}",
                    f"- 策略信号日期: {item['strategy_date']}",
                    f"- 原文 target_holdings: {item['expected']}",
                    f"- 本策略 target_holdings: {item['actual']}",
                    f"- 单日命中率: {pct_fmt(float(item['hit_ratio']) * 100)}",
                    f"- 调仓数量差异: {item['turnover_diff']}",
                    "",
                    "本策略 top5 排名：",
                    "",
                    _markdown_table(item["strategy_top5"]),
                    "",
                    "原文 doc_rows 前5强弱排序：",
                    "",
                    _markdown_table(item["doc_top5"]),
                    "",
                ]
            )

    ensure_dir(cfg.reports_dir)
    output = cfg.reports_dir / "calibration_report.md"
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output


def _rate(values: list[bool]) -> float:
    """Return a percentage rate for boolean values."""
    return sum(1 for value in values if value) / len(values) * 100 if values else 0.0


def _layered_period_stats(rows: list[dict[str, Any]], start: str, end: str) -> dict[str, float | int]:
    """Compute layered match statistics for a date range."""
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    selected = [row for row in rows if start_ts <= pd.Timestamp(row["date"]) <= end_ts]
    if not selected:
        return {
            "count": 0,
            "layer1_match_rate": 0.0,
            "layer2_match_rate": 0.0,
            "final_exact_match": 0.0,
            "avg_turnover": 0.0,
        }
    return {
        "count": len(selected),
        "layer1_match_rate": _rate([bool(row["layer1_exact"]) for row in selected]),
        "layer2_match_rate": _rate([bool(row["layer2_exact"]) for row in selected]),
        "final_exact_match": _rate([bool(row["final_exact"]) for row in selected]),
        "avg_turnover": sum(float(row["execution_turnover"]) for row in selected) / len(selected),
    }


def run_layered_calibration(
    labels_path: Path,
    prices: pd.DataFrame,
    cfg: ProjectConfig,
    data_note: str = "",
) -> Path:
    """Evaluate the three-layer decision pipeline against source-document labels."""
    if not labels_path.exists():
        raise FileNotFoundError(f"Label CSV not found: {labels_path}")
    labels = pd.read_csv(labels_path)
    if labels.empty:
        raise ValueError(f"Label CSV is empty: {labels_path}")
    labels["date"] = pd.to_datetime(labels["date"]).dt.normalize()
    labels["broad_valid"] = labels.get("broad_valid", True)
    valid_labels = labels[labels["broad_valid"].map(_as_bool)].copy()
    if valid_labels.empty:
        raise ValueError("No valid broad ETF labels found for layered calibration.")

    end_ts = valid_labels["date"].max()
    features, symbols = prepare_features(prices, cfg, pools=["broad_etf"])
    code_map, _ = etf_maps(symbols)
    max_hold = int(cfg.universe.get("broad_etf", {}).get("max_hold", cfg.strategy.get("max_hold_broad", 2)))
    label_by_date = {pd.Timestamp(row.date).normalize(): row for row in valid_labels.itertuples(index=False)}
    feature_dates = sorted(pd.Timestamp(dt).normalize() for dt in features["date"].drop_duplicates())

    yesterday: list[str] = []
    rows: list[dict[str, Any]] = []
    layer2_blocked_counts: list[int] = []
    for date_value in feature_dates:
        if date_value > end_ts:
            break
        latest_features = features[features["date"].eq(date_value)].copy()
        if latest_features.empty:
            continue
        pipeline = run_strategy_pipeline(latest_features, yesterday, cfg.strategy, max_hold=max_hold)
        l1_codes = layer1_targets(pipeline.layer1_candidates, max_hold)
        l2_codes = layer2_targets(pipeline.layer2_candidates, max_hold)
        blocked = int((~pipeline.layer2_candidates["allow_new_entry"].fillna(False)).sum())
        layer2_blocked_counts.append(blocked)

        if date_value in label_by_date:
            label = label_by_date[date_value]
            expected = [normalize_name(item) for item in from_pipe_list(label.target_holdings)]
            layer1_names = names_for_codes(l1_codes, code_map)
            layer2_names = names_for_codes(l2_codes, code_map)
            final_names = names_for_codes(pipeline.target_holdings, code_map)
            turnover = max(
                len(pipeline.execution_decision.added_positions),
                len(pipeline.execution_decision.removed_positions),
            )
            rows.append(
                {
                    "date": date_value.strftime("%Y-%m-%d"),
                    "expected": expected,
                    "layer1": layer1_names,
                    "layer2": layer2_names,
                    "final": final_names,
                    "layer1_exact": exact_match(expected, layer1_names),
                    "layer2_exact": exact_match(expected, layer2_names),
                    "final_exact": exact_match(expected, final_names),
                    "layer1_hit_ratio": hit_ratio(expected, layer1_names),
                    "layer2_hit_ratio": hit_ratio(expected, layer2_names),
                    "final_hit_ratio": hit_ratio(expected, final_names),
                    "layer2_blocked_count": blocked,
                    "execution_turnover": turnover,
                    "kept": names_for_codes(pipeline.execution_decision.kept_positions, code_map),
                    "added": names_for_codes(pipeline.execution_decision.added_positions, code_map),
                    "removed": names_for_codes(pipeline.execution_decision.removed_positions, code_map),
                }
            )
        yesterday = pipeline.target_holdings

    if not rows:
        raise ValueError("Layered calibration produced no overlapping label dates.")

    layer1_match_rate = _rate([bool(row["layer1_exact"]) for row in rows])
    layer2_match_rate = _rate([bool(row["layer2_exact"]) for row in rows])
    final_exact_match = _rate([bool(row["final_exact"]) for row in rows])
    layer2_filter_effect = layer2_match_rate - layer1_match_rate
    layer3_execution_effect = final_exact_match - layer2_match_rate
    execution_turnover = sum(float(row["execution_turnover"]) for row in rows) / len(rows)
    avg_blocked = sum(layer2_blocked_counts) / len(layer2_blocked_counts) if layer2_blocked_counts else 0.0

    may_stats = _layered_period_stats(rows, "2026-05-12", "2026-05-31")
    june_stats = _layered_period_stats(rows, "2026-06-01", "2026-06-26")
    may_deltas = {
        "layer2_filter": float(may_stats["layer2_match_rate"]) - float(may_stats["layer1_match_rate"]),
        "layer3_execution": float(may_stats["final_exact_match"]) - float(may_stats["layer2_match_rate"]),
    }
    biggest_may_layer = max(may_deltas, key=lambda key: abs(may_deltas[key]))

    mismatches = [row for row in rows if not row["final_exact"]]
    lines = [
        "# Layered Pipeline 校准报告",
        "",
        "本报告评估三层决策链路：Layer 1 selector candidates -> Layer 2 risk overlay -> Layer 3 execution policy。",
        "",
    ]
    if data_note:
        lines.extend([f"> {data_note}", ""])
    lines.extend(
        [
            "## 总览",
            "",
            f"- 标签总日期数: {len(labels)}",
            f"- 有效 broad 标签数: {len(valid_labels)}",
            f"- 校准覆盖日期数: {len(rows)}",
            f"- layer1_match_rate: {pct_fmt(layer1_match_rate)}",
            f"- layer2_match_rate: {pct_fmt(layer2_match_rate)}",
            f"- layer2_filter_effect: {pct_fmt(layer2_filter_effect)}",
            f"- execution_turnover: {execution_turnover:.2f}",
            f"- layer3_execution_effect: {pct_fmt(layer3_execution_effect)}",
            f"- final_exact_match: {pct_fmt(final_exact_match)}",
            f"- layer2 平均过滤候选数: {avg_blocked:.2f}",
            f"- final 不匹配日期数量: {len(mismatches)}",
            f"- final 不匹配日期列表: {[row['date'] for row in mismatches]}",
            "",
            "## 分阶段统计",
            "",
            (
                f"- 2026-05-12 到 2026-05-31: count={may_stats['count']}, "
                f"layer1={pct_fmt(float(may_stats['layer1_match_rate']))}, "
                f"layer2={pct_fmt(float(may_stats['layer2_match_rate']))}, "
                f"final={pct_fmt(float(may_stats['final_exact_match']))}, "
                f"avg_turnover={float(may_stats['avg_turnover']):.2f}"
            ),
            (
                f"- 2026-06-01 到 2026-06-26: count={june_stats['count']}, "
                f"layer1={pct_fmt(float(june_stats['layer1_match_rate']))}, "
                f"layer2={pct_fmt(float(june_stats['layer2_match_rate']))}, "
                f"final={pct_fmt(float(june_stats['final_exact_match']))}, "
                f"avg_turnover={float(june_stats['avg_turnover']):.2f}"
            ),
            "",
            "## 5月 mismatch 影响判断",
            "",
            f"- layer2_filter delta: {pct_fmt(may_deltas['layer2_filter'])}",
            f"- layer3_execution delta: {pct_fmt(may_deltas['layer3_execution'])}",
            f"- 影响最大的层: {biggest_may_layer}",
            "",
            "## 日期明细",
            "",
        ]
    )
    detail = pd.DataFrame(
        [
            {
                "date": row["date"],
                "expected": row["expected"],
                "layer1": row["layer1"],
                "layer2": row["layer2"],
                "final": row["final"],
                "layer1_hit": row["layer1_hit_ratio"],
                "layer2_hit": row["layer2_hit_ratio"],
                "final_hit": row["final_hit_ratio"],
                "turnover": row["execution_turnover"],
                "kept": row["kept"],
                "added": row["added"],
                "removed": row["removed"],
            }
            for row in rows
        ]
    )
    lines.append(detail.to_markdown(index=False))
    ensure_dir(cfg.reports_dir)
    output = cfg.reports_dir / "calibration_layered_report.md"
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output
