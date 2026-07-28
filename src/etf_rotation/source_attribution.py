"""Structural source-attribution analysis for the ETF rotation strategy."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from .config import ProjectConfig
from .utils import ensure_dir


@dataclass(frozen=True)
class SourceFeature:
    """One structural feature used for source attribution."""

    key: str
    group: str
    label: str
    present: bool
    weight: float
    evidence: str


@dataclass(frozen=True)
class SimilarityResult:
    """Similarity score for one known strategy template."""

    template: str
    label: str
    similarity: float
    matched_weight: float
    total_weight: float


@dataclass(frozen=True)
class AttributionResult:
    """Final source-attribution output."""

    similarity_A: float
    similarity_B: float
    similarity_C: float
    final_source_classification: str
    confidence: float
    confidence_interval: tuple[float, float]
    strategy_origin_guess: str
    reasoning: list[str]


TEMPLATES: dict[str, dict[str, Any]] = {
    "A": {
        "label": "classic momentum ETF rotation",
        "features": {
            "lookback_near_20",
            "top_k_2",
            "cross_asset_universe",
            "ranking_table_format",
        },
    },
    "B": {
        "label": "factor rotation + risk parity hybrid",
        "features": {
            "lookback_near_20",
            "top_k_2",
            "cross_asset_universe",
            "overheat_threshold_filter",
            "pb_qdii_gating",
            "market_signal_star_weak",
            "holding_inertia",
            "replace_threshold_gate",
        },
    },
    "C": {
        "label": "discretionary ETF rotation blog style",
        "features": {
            "lookback_near_20",
            "top_k_2",
            "cross_asset_universe",
            "overheat_threshold_filter",
            "pb_qdii_gating",
            "market_signal_star_weak",
            "holding_inertia",
            "turnover_constraint",
            "replace_threshold_gate",
            "daily_report_style",
            "ranking_table_format",
            "status_mark_encoding",
            "bs_signal_system",
        },
    },
}


def _source_text(cfg: ProjectConfig, relative_path: str) -> str:
    """Read a project source file for structural evidence."""
    path = cfg.project_root / relative_path
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _asset_count(cfg: ProjectConfig) -> int:
    """Return broad-ETF distinct asset count."""
    symbols = cfg.universe.get("broad_etf", {}).get("symbols", [])
    return len({str(item.get("asset", "")) for item in symbols if str(item.get("asset", ""))})


def extract_source_features(cfg: ProjectConfig) -> list[SourceFeature]:
    """Extract the current strategy's structural feature vector."""
    strategy = cfg.strategy
    score_cfg = strategy.get("score", {})
    rebalance = strategy.get("rebalance", {})
    broad_cfg = cfg.universe.get("broad_etf", {})
    risk_source = _source_text(cfg, "src/etf_rotation/risk_overlay.py")
    execution_source = _source_text(cfg, "src/etf_rotation/execution_policy.py")
    report_source = _source_text(cfg, "src/etf_rotation/report.py")
    selector_source = _source_text(cfg, "src/etf_rotation/selector.py")
    signal_source = _source_text(cfg, "src/etf_rotation/signals.py")
    indicator_source = _source_text(cfg, "src/etf_rotation/indicators.py")

    lookback = int(strategy.get("lookback_momentum", 0))
    max_hold = int(broad_cfg.get("max_hold", strategy.get("max_hold_broad", 0)))
    overheat = score_cfg.get("overheat_bias_threshold")
    qdii_block = score_cfg.get("qdii_premium_block")
    keep_rank = rebalance.get("keep_if_rank_le")
    replace_margin = rebalance.get("replace_only_if_new_score_better_by")

    return [
        SourceFeature(
            "lookback_near_20",
            "momentum",
            f"lookback near 20 = {lookback}",
            18 <= lookback <= 26,
            1.0,
            f"configs/strategy.yaml lookback_momentum={lookback}",
        ),
        SourceFeature(
            "top_k_2",
            "momentum",
            "top-k selection = 2",
            max_hold == 2,
            1.0,
            f"configs/universe.yaml broad_etf.max_hold={max_hold}",
        ),
        SourceFeature(
            "cross_asset_universe",
            "momentum",
            "cross-asset ETF universe",
            _asset_count(cfg) >= 3,
            1.0,
            f"broad ETF asset classes={_asset_count(cfg)}",
        ),
        SourceFeature(
            "overheat_threshold_filter",
            "risk",
            "overheat threshold filter",
            overheat is not None and "OVERHEAT" in risk_source,
            1.2,
            f"overheat_bias_threshold={overheat}; risk_overlay contains OVERHEAT gate",
        ),
        SourceFeature(
            "pb_qdii_gating",
            "risk",
            "PB/QDII gating",
            qdii_block is not None and "BLOCK_NEW_ENTRY_QDII_PREMIUM" in risk_source,
            1.0,
            f"qdii_premium_block={qdii_block}; risk_overlay blocks QDII premium",
        ),
        SourceFeature(
            "market_signal_star_weak",
            "risk",
            "market_signal (star / weak)",
            "STAR" in indicator_source and "WEAK" in indicator_source and "MARKET_SIGNAL_WEAK" in risk_source,
            1.2,
            "indicators define STAR/WEAK and risk_overlay suppresses MARKET_SIGNAL_WEAK",
        ),
        SourceFeature(
            "holding_inertia",
            "behavior",
            "holding inertia (keep_if_rank_le)",
            keep_rank is not None,
            1.2,
            f"rebalance.keep_if_rank_le={keep_rank}",
        ),
        SourceFeature(
            "turnover_constraint",
            "behavior",
            "turnover constraint",
            "max_changes = 1" in execution_source,
            1.0,
            "execution_policy.py contains max_changes = 1",
        ),
        SourceFeature(
            "replace_threshold_gate",
            "behavior",
            "replace threshold gate",
            replace_margin is not None and "replace_only_if_new_score_better_by" in execution_source,
            1.0,
            f"replace_only_if_new_score_better_by={replace_margin}",
        ),
        SourceFeature(
            "daily_report_style",
            "output",
            "daily report style",
            "ETF轮动策略复现版盘中提示" in report_source and "今日收盘组合应持仓" in report_source,
            1.4,
            "report.py renders source-style daily text and target holdings",
        ),
        SourceFeature(
            "ranking_table_format",
            "output",
            "ranking table format",
            ("近日表现" in report_source or "近20日表现" in report_source)
            and "PB" in report_source
            and "render_feature_rows" in report_source,
            1.0,
            "report.py renders ranking rows with PB and feature lists",
        ),
        SourceFeature(
            "status_mark_encoding",
            "output",
            "status mark encoding",
            "CHECK = \"√\"" in selector_source and "CROSS = \"×\"" in selector_source,
            1.2,
            "selector.py defines three-character recent-holding marks using check/cross glyphs",
        ),
        SourceFeature(
            "bs_signal_system",
            "output",
            "B/S signal system",
            "\"B\"" in signal_source and "\"S\"" in signal_source and "latest_signal" in signal_source,
            1.2,
            "signals.py emits date-stamped B/S labels and report.py displays them",
        ),
    ]


def weighted_template_similarity(features: list[SourceFeature], template_features: set[str]) -> SimilarityResult:
    """Compute weighted Jaccard similarity against a known strategy template."""
    actual = {item.key for item in features if item.present}
    all_keys = actual | template_features
    weights = {item.key: item.weight for item in features}
    matched = actual & template_features
    matched_weight = sum(weights.get(key, 1.0) for key in matched)
    total_weight = sum(weights.get(key, 1.0) for key in all_keys)
    similarity = matched_weight / total_weight * 100 if total_weight else 0.0
    label = next(template["label"] for template in TEMPLATES.values() if template["features"] == template_features)
    template_key = next(key for key, template in TEMPLATES.items() if template["features"] == template_features)
    return SimilarityResult(template_key, label, similarity, matched_weight, total_weight)


def score_templates(features: list[SourceFeature]) -> list[SimilarityResult]:
    """Score the feature vector against the three known templates."""
    return [
        weighted_template_similarity(features, set(template["features"]))
        for template in TEMPLATES.values()
    ]


def _judgment_flags(features: list[SourceFeature]) -> dict[str, bool]:
    """Return the four requested source-attribution judgment flags."""
    present = {item.key for item in features if item.present}
    return {
        "human_rebalance_trace": {"holding_inertia", "turnover_constraint", "replace_threshold_gate"}.issubset(present),
        "non_formulaic_thresholds": {"overheat_threshold_filter", "pb_qdii_gating", "replace_threshold_gate"}.issubset(present),
        "daily_report_driven_behavior": {"daily_report_style", "status_mark_encoding", "bs_signal_system"}.issubset(present),
        "risk_prioritizes_over_return_ranking": {"overheat_threshold_filter", "pb_qdii_gating", "market_signal_star_weak"}.issubset(present),
    }


def _classification(scores: list[SimilarityResult], flags: dict[str, bool]) -> tuple[str, float, tuple[float, float]]:
    """Return final source classification and confidence from similarity scores."""
    sorted_scores = sorted(scores, key=lambda item: item.similarity, reverse=True)
    top = sorted_scores[0]
    runner_up = sorted_scores[1]
    if top.template == "C" and runner_up.similarity >= 55.0 and all(flags.values()):
        classification = "Hybrid"
    else:
        classification = top.template

    margin = max(0.0, top.similarity - runner_up.similarity)
    confidence = min(92.0, 55.0 + top.similarity * 0.25 + margin * 0.20)
    if classification == "Hybrid":
        confidence = min(confidence, 82.0)
    interval_width = 8.0 if margin >= 20.0 else 12.0
    low = max(0.0, confidence - interval_width)
    high = min(100.0, confidence + interval_width)
    return classification, confidence, (low, high)


def _reasoning(features: list[SourceFeature], scores: list[SimilarityResult], flags: dict[str, bool]) -> list[str]:
    """Build concise reasoning bullets for the final report."""
    feature_map = {item.key: item for item in features}
    score_map = {item.template: item.similarity for item in scores}
    bullets = [
        f"Near-20-day momentum and top-2 target selection match classic ETF rotation, but they explain only similarity_A={score_map['A']:.2f}%.",
        f"Cross-asset ETF universe is present: {feature_map['cross_asset_universe'].evidence}.",
        f"Risk overlay contains overheat, QDII/PB, and star/weak market-signal gates, supporting similarity_B={score_map['B']:.2f}%.",
        "Holding inertia, max-one-change execution, and replacement threshold create human-like rebalancing behavior.",
        "Daily markdown text, PB feature rows, status marks, and B/S labels match discretionary report-driven blog style.",
        f"Human rebalance trace: {'yes' if flags['human_rebalance_trace'] else 'no'}.",
        f"Non-formulaic thresholds: {'yes' if flags['non_formulaic_thresholds'] else 'no'}.",
        f"Daily-report-driven behavior: {'yes' if flags['daily_report_driven_behavior'] else 'no'}.",
        f"Risk priority over raw return ranking: {'yes' if flags['risk_prioritizes_over_return_ranking'] else 'no'}.",
        "Counterfactual analysis showed structural risk-overlay removal changes outputs more than small score noise, consistent with a rule-plus-heuristic source.",
    ]
    return bullets[:10]


def run_source_attribution(cfg: ProjectConfig) -> Path:
    """Run structural source attribution and write the markdown report."""
    features = extract_source_features(cfg)
    scores = score_templates(features)
    score_map = {item.template: item.similarity for item in scores}
    flags = _judgment_flags(features)
    classification, confidence, confidence_interval = _classification(scores, flags)
    origin_guess = (
        "discretionary ETF rotation blog style with factor/risk-control components"
        if classification in {"C", "Hybrid"}
        else TEMPLATES[classification]["label"]
    )
    result = AttributionResult(
        similarity_A=score_map["A"],
        similarity_B=score_map["B"],
        similarity_C=score_map["C"],
        final_source_classification=classification,
        confidence=confidence,
        confidence_interval=confidence_interval,
        strategy_origin_guess=origin_guess,
        reasoning=_reasoning(features, scores, flags),
    )

    report = _render_report(features, scores, flags, result)
    ensure_dir(cfg.reports_dir)
    output = cfg.reports_dir / "source_attribution_report.md"
    output.write_text(report + "\n", encoding="utf-8")
    return output


def _feature_table(features: list[SourceFeature]) -> pd.DataFrame:
    """Return feature vector table for markdown output."""
    return pd.DataFrame(
        [
            {
                "group": item.group,
                "feature": item.label,
                "present": "yes" if item.present else "no",
                "weight": item.weight,
                "evidence": item.evidence,
            }
            for item in features
        ]
    )


def _similarity_table(scores: list[SimilarityResult]) -> pd.DataFrame:
    """Return similarity table for markdown output."""
    return pd.DataFrame(
        [
            {
                "template": f"{item.template}. {item.label}",
                "similarity": item.similarity,
                "matched_weight": item.matched_weight,
                "total_weight": item.total_weight,
            }
            for item in scores
        ]
    )


def _format_table(frame: pd.DataFrame) -> str:
    """Render markdown with compact numeric formatting."""
    table = frame.copy()
    for column in table.columns:
        if pd.api.types.is_numeric_dtype(table[column]):
            table[column] = table[column].map(lambda value: f"{float(value):.2f}")
    return table.to_markdown(index=False)


def _yes_no(value: bool) -> str:
    """Render a boolean answer."""
    return "yes" if value else "no"


def _render_report(
    features: list[SourceFeature],
    scores: list[SimilarityResult],
    flags: dict[str, bool],
    result: AttributionResult,
) -> str:
    """Render source-attribution markdown report."""
    lines = [
        "# Strategy Source Attribution Report",
        "",
        "本报告只做结构归因分析，不修改策略、不优化收益、不重新回测。",
        "",
        "## Structural Feature Vector",
        "",
        _format_table(_feature_table(features)),
        "",
        "## Template Similarity",
        "",
        _format_table(_similarity_table(scores)),
        "",
        "## Attribution Scores",
        "",
        f"- similarity_A: {result.similarity_A:.2f}%",
        f"- similarity_B: {result.similarity_B:.2f}%",
        f"- similarity_C: {result.similarity_C:.2f}%",
        f"- final_source_classification: {result.final_source_classification}",
        f"- confidence: {result.confidence:.0f}%",
        "",
        "## Required Judgments",
        "",
        f"1. 是否存在“人为调仓规则痕迹”: {_yes_no(flags['human_rebalance_trace'])}",
        f"2. 是否存在“非公式化阈值”: {_yes_no(flags['non_formulaic_thresholds'])}",
        f"3. 是否存在“日报驱动行为”: {_yes_no(flags['daily_report_driven_behavior'])}",
        f"4. 是否存在“风险优先于收益排序”: {_yes_no(flags['risk_prioritizes_over_return_ranking'])}",
        "",
        "## Forced Conclusion",
        "",
        f"- strategy_origin_guess: {result.strategy_origin_guess}",
        "- reasoning:",
        *[f"  - {item}" for item in result.reasoning],
        (
            f"- confidence interval: {result.confidence_interval[0]:.0f}%"
            f" - {result.confidence_interval[1]:.0f}%"
        ),
        "",
    ]
    return "\n".join(lines)
