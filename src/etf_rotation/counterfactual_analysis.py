"""Counterfactual ablation analysis for the layered ETF strategy."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any

import pandas as pd

from .backtest import prepare_features
from .config import ProjectConfig
from .execution_policy import apply_execution_policy
from .metrics import exact_match, hit_ratio
from .risk_overlay import apply_risk_overlay, risk_filtered_new_entries
from .selector import rank_candidates
from .strategy_pipeline import run_strategy_pipeline
from .universe import etf_maps, names_for_codes, normalize_name
from .utils import ensure_dir, from_pipe_list, pct_fmt


NOISE_SEED = 20260628
NOISE_BAND = 0.05


@dataclass(frozen=True)
class CounterfactualResult:
    """Aggregated result for one counterfactual scenario."""

    scenario: str
    display_name: str
    description: str
    exact_match: float
    hit_ratio: float
    turnover: float
    stability_index: float
    rows: list[dict[str, Any]]


@dataclass(frozen=True)
class IdentifiabilityResult:
    """Final strategy-identifiability judgment."""

    strategy_identifiability_score: float
    conclusion: str
    confidence: float
    small_perturbation_impact: float
    structural_impact: float


SCENARIOS: dict[str, tuple[str, str]] = {
    "baseline": (
        "baseline (current system)",
        "Current layered pipeline: ranking + risk overlay + execution policy.",
    ),
    "no_risk_overlay": (
        "no risk overlay",
        "Risk overlay disabled: OVERHEAT, PB block, and market_signal=● suppression are bypassed.",
    ),
    "no_execution_policy": (
        "no execution policy",
        "Execution policy disabled: no holding inertia, no replacement threshold, pure risk-filtered top-k.",
    ),
    "noisy_scoring": (
        "noisy scoring",
        "Ret20 score input receives deterministic row-level +/-5% noise before ranking.",
    ),
}


def _as_bool(value: Any) -> bool:
    """Coerce CSV bool-like values."""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes"}


def _load_valid_labels(labels_path: Path) -> pd.DataFrame:
    """Load valid broad-ETF source-document labels."""
    if not labels_path.exists():
        raise FileNotFoundError(f"Label CSV not found: {labels_path}")
    labels = pd.read_csv(labels_path)
    if labels.empty:
        raise ValueError(f"Label CSV is empty: {labels_path}")
    labels["date"] = pd.to_datetime(labels["date"]).dt.normalize()
    labels["broad_valid"] = labels.get("broad_valid", True)
    valid_labels = labels[labels["broad_valid"].map(_as_bool)].copy()
    if valid_labels.empty:
        raise ValueError("No valid broad ETF labels found for counterfactual analysis.")
    return valid_labels


def _holding_similarity(left: list[str], right: list[str]) -> float:
    """Return Jaccard similarity for two holding-code lists."""
    left_set = set(left)
    right_set = set(right)
    if not left_set and not right_set:
        return 1.0
    union = left_set | right_set
    return len(left_set & right_set) / len(union) if union else 1.0


def _stable_noise(date_value: pd.Timestamp, code: str, seed: int = NOISE_SEED) -> float:
    """Return deterministic uniform noise in [-NOISE_BAND, NOISE_BAND]."""
    key = f"{seed}|{pd.Timestamp(date_value).strftime('%Y-%m-%d')}|{code}".encode("utf-8")
    digest = hashlib.sha256(key).digest()
    unit = int.from_bytes(digest[:8], byteorder="big", signed=False) / 2**64
    return unit * (NOISE_BAND * 2) - NOISE_BAND


def _inject_ret20_noise(features: pd.DataFrame) -> pd.DataFrame:
    """Apply deterministic +/-5% noise to ret20_pct before scoring."""
    noisy = features.copy()
    ret20 = pd.to_numeric(noisy["ret20_pct"], errors="coerce")
    multipliers = [
        1.0 + _stable_noise(pd.Timestamp(row.date), str(row.code)) for row in noisy.itertuples(index=False)
    ]
    noisy["ret20_pct"] = ret20 * pd.Series(multipliers, index=noisy.index)
    return noisy


def _disabled_risk_overlay(layer1_candidates: pd.DataFrame) -> pd.DataFrame:
    """Return a Layer 2-compatible table with all risk gates opened."""
    table = layer1_candidates.copy()
    table["allow_new_entry"] = True
    table["allow_hold"] = True
    table["allow_exit"] = True
    table["risk_reason"] = "RISK_OVERLAY_DISABLED"
    table["OVERHEAT"] = False
    table["BLOCK_NEW_ENTRY"] = False
    return table


def _pure_top_k_after_risk(layer2_candidates: pd.DataFrame, max_hold: int) -> list[str]:
    """Select pure top-k candidates after risk filtering, without execution policy."""
    if layer2_candidates.empty:
        return []
    return risk_filtered_new_entries(layer2_candidates).head(max_hold)["code"].astype(str).tolist()


def _decide_targets(
    latest_features: pd.DataFrame,
    yesterday: list[str],
    strategy: dict,
    max_hold: int,
    scenario: str,
) -> list[str]:
    """Run one scenario decision for a single date."""
    if scenario == "baseline":
        return run_strategy_pipeline(latest_features, yesterday, strategy, max_hold=max_hold).target_holdings

    if scenario == "no_risk_overlay":
        layer1 = rank_candidates(latest_features, strategy, yesterday)
        layer2 = _disabled_risk_overlay(layer1)
        return apply_execution_policy(layer2, yesterday, strategy, max_hold).target_holdings

    if scenario == "no_execution_policy":
        layer1 = rank_candidates(latest_features, strategy, yesterday_holdings=[])
        layer2 = apply_risk_overlay(layer1, strategy)
        return _pure_top_k_after_risk(layer2, max_hold)

    if scenario == "noisy_scoring":
        noisy_features = _inject_ret20_noise(latest_features)
        return run_strategy_pipeline(noisy_features, yesterday, strategy, max_hold=max_hold).target_holdings

    raise ValueError(f"Unsupported counterfactual scenario: {scenario}")


def _evaluate_scenario(
    scenario: str,
    features: pd.DataFrame,
    valid_labels: pd.DataFrame,
    code_map: dict,
    strategy: dict,
    max_hold: int,
    baseline_targets: dict[str, list[str]] | None = None,
) -> CounterfactualResult:
    """Evaluate one scenario against parsed document labels."""
    label_by_date = {pd.Timestamp(row.date).normalize(): row for row in valid_labels.itertuples(index=False)}
    end_ts = valid_labels["date"].max()
    feature_dates = sorted(pd.Timestamp(dt).normalize() for dt in features["date"].drop_duplicates())

    yesterday: list[str] = []
    rows: list[dict[str, Any]] = []
    for date_value in feature_dates:
        if date_value > end_ts:
            break
        latest_features = features[features["date"].eq(date_value)].copy()
        if latest_features.empty:
            continue

        target = _decide_targets(latest_features, yesterday, strategy, max_hold, scenario)
        if date_value in label_by_date:
            date_text = date_value.strftime("%Y-%m-%d")
            label = label_by_date[date_value]
            expected = [normalize_name(item) for item in from_pipe_list(label.target_holdings)]
            actual = names_for_codes(target, code_map)
            baseline_target = target if baseline_targets is None else baseline_targets.get(date_text, [])
            rows.append(
                {
                    "date": date_text,
                    "expected": expected,
                    "actual": actual,
                    "target_codes": target,
                    "exact_match": exact_match(expected, actual),
                    "hit_ratio": hit_ratio(expected, actual),
                    "turnover": max(len(set(target) - set(yesterday)), len(set(yesterday) - set(target))),
                    "stability": _holding_similarity(target, baseline_target),
                }
            )
        yesterday = target

    if not rows:
        raise ValueError(f"Counterfactual scenario produced no overlapping label dates: {scenario}")

    exact_rate = sum(1 for row in rows if row["exact_match"]) / len(rows) * 100
    average_hit = sum(float(row["hit_ratio"]) for row in rows) / len(rows) * 100
    turnover = sum(float(row["turnover"]) for row in rows) / len(rows)
    stability = sum(float(row["stability"]) for row in rows) / len(rows) * 100
    display_name, description = SCENARIOS[scenario]
    return CounterfactualResult(
        scenario=scenario,
        display_name=display_name,
        description=description,
        exact_match=exact_rate,
        hit_ratio=average_hit,
        turnover=turnover,
        stability_index=stability,
        rows=rows,
    )


def _impact_score(baseline: CounterfactualResult, variant: CounterfactualResult) -> float:
    """Combine label-match collapse and baseline-output instability."""
    exact_collapse = max(0.0, baseline.exact_match - variant.exact_match)
    stability_loss = max(0.0, 100.0 - variant.stability_index)
    return exact_collapse * 0.7 + stability_loss * 0.3


def _identifiability(results: list[CounterfactualResult]) -> IdentifiabilityResult:
    """Classify whether the strategy behaves like a unique deterministic rule system."""
    by_name = {item.scenario: item for item in results}
    baseline = by_name["baseline"]
    noisy = by_name["noisy_scoring"]
    structural_variants = [by_name["no_risk_overlay"], by_name["no_execution_policy"]]
    small_impact = _impact_score(baseline, noisy)
    structural_impact = max(_impact_score(baseline, item) for item in structural_variants)
    score = min(100.0, max(small_impact * 2.0, structural_impact))

    if small_impact >= 20.0 and score >= 50.0:
        conclusion = "A. deterministic rule-based ETF strategy"
        confidence = min(95.0, 65.0 + score * 0.30)
    elif small_impact >= 8.0 or structural_impact >= 15.0:
        conclusion = "B. hybrid rule + heuristic"
        confidence = min(90.0, 60.0 + score * 0.25)
    else:
        conclusion = "C. non-deterministic / manual-like system"
        confidence = min(85.0, 58.0 + max(0.0, 35.0 - score) * 0.30)

    return IdentifiabilityResult(
        strategy_identifiability_score=score,
        conclusion=conclusion,
        confidence=confidence,
        small_perturbation_impact=small_impact,
        structural_impact=structural_impact,
    )


def _summary_table(results: list[CounterfactualResult]) -> pd.DataFrame:
    """Build the full scenario-level ablation table."""
    baseline = next(item for item in results if item.scenario == "baseline")
    return pd.DataFrame(
        [
            {
                "scenario": item.display_name,
                "exact_match": item.exact_match,
                "hit_ratio": item.hit_ratio,
                "turnover": item.turnover,
                "stability_index": item.stability_index,
                "exact_delta_vs_baseline": item.exact_match - baseline.exact_match,
                "hit_delta_vs_baseline": item.hit_ratio - baseline.hit_ratio,
            }
            for item in results
        ]
    )


def _date_level_table(results: list[CounterfactualResult]) -> pd.DataFrame:
    """Build date-level comparison rows for the report appendix."""
    rows: list[dict[str, Any]] = []
    for item in results:
        for row in item.rows:
            rows.append(
                {
                    "scenario": item.display_name,
                    "date": row["date"],
                    "expected": row["expected"],
                    "actual": row["actual"],
                    "exact": row["exact_match"],
                    "hit_ratio": row["hit_ratio"],
                    "turnover": row["turnover"],
                    "stability": row["stability"],
                }
            )
    return pd.DataFrame(rows)


def _format_table(frame: pd.DataFrame) -> str:
    """Render markdown with compact numeric formatting."""
    table = frame.copy()
    for column in table.columns:
        if pd.api.types.is_numeric_dtype(table[column]):
            table[column] = table[column].map(lambda value: f"{float(value):.2f}")
    return table.to_markdown(index=False)


def _build_report(
    labels_path: Path,
    valid_labels: pd.DataFrame,
    results: list[CounterfactualResult],
    identifiability: IdentifiabilityResult,
    data_note: str = "",
) -> str:
    """Render the counterfactual analysis markdown report."""
    by_name = {item.scenario: item for item in results}
    baseline = by_name["baseline"]
    no_risk = by_name["no_risk_overlay"]
    no_execution = by_name["no_execution_policy"]
    noisy = by_name["noisy_scoring"]
    summary = _summary_table(results)
    detail = _date_level_table(results)

    lines = [
        "# Counterfactual Strategy Uniqueness Report",
        "",
        "本报告只做结构消融实验，不优化收益、不调整参数、不改默认回测逻辑。",
        "",
        "## Experiment Setup",
        "",
        f"- Label file: `{labels_path}`",
        f"- Valid broad labels: {len(valid_labels)}",
        f"- Noise injection: ret20_pct multiplied by deterministic row-level noise in +/-{NOISE_BAND * 100:.0f}%",
        "- stability_index: average Jaccard similarity versus baseline same-date holdings",
        "- turnover: average daily target-holding change count on covered label dates",
        "",
    ]
    if data_note:
        lines.extend([f"> {data_note}", ""])

    lines.extend(
        [
            "## Baseline (Current System)",
            "",
            f"- exact_match: {pct_fmt(baseline.exact_match)}",
            f"- hit_ratio: {pct_fmt(baseline.hit_ratio)}",
            f"- turnover: {baseline.turnover:.2f}",
            f"- stability_index: {pct_fmt(baseline.stability_index)}",
            "",
            "## No Risk Overlay",
            "",
            no_risk.description,
            "",
            f"- exact_match: {pct_fmt(no_risk.exact_match)}",
            f"- hit_ratio: {pct_fmt(no_risk.hit_ratio)}",
            f"- turnover: {no_risk.turnover:.2f}",
            f"- stability_index: {pct_fmt(no_risk.stability_index)}",
            "",
            "## No Execution Policy",
            "",
            no_execution.description,
            "",
            f"- exact_match: {pct_fmt(no_execution.exact_match)}",
            f"- hit_ratio: {pct_fmt(no_execution.hit_ratio)}",
            f"- turnover: {no_execution.turnover:.2f}",
            f"- stability_index: {pct_fmt(no_execution.stability_index)}",
            "",
            "## Noisy Scoring",
            "",
            noisy.description,
            "",
            f"- exact_match: {pct_fmt(noisy.exact_match)}",
            f"- hit_ratio: {pct_fmt(noisy.hit_ratio)}",
            f"- turnover: {noisy.turnover:.2f}",
            f"- stability_index: {pct_fmt(noisy.stability_index)}",
            "",
            "## Full Ablation Table",
            "",
            _format_table(summary),
            "",
            "## Strategy Identifiability",
            "",
            "Interpretation rule: if small perturbation causes large label-match collapse and output instability, "
            "the system is treated as a deterministic rule-based strategy; otherwise it is treated as fuzzy or hybrid.",
            "",
            f"- strategy_identifiability_score: {identifiability.strategy_identifiability_score:.2f}",
            f"- small_perturbation_impact: {identifiability.small_perturbation_impact:.2f}",
            f"- structural_impact: {identifiability.structural_impact:.2f}",
            f"- conclusion: {identifiability.conclusion}",
            f"- confidence: {identifiability.confidence:.0f}%",
            "",
            "## Date-Level Ablation Detail",
            "",
            _format_table(detail),
            "",
        ]
    )
    return "\n".join(lines)


def run_counterfactual_analysis(
    labels_path: Path,
    prices: pd.DataFrame,
    cfg: ProjectConfig,
    data_note: str = "",
) -> Path:
    """Run counterfactual ablations and write the markdown report."""
    valid_labels = _load_valid_labels(labels_path)
    features, symbols = prepare_features(prices, cfg, pools=["broad_etf"])
    code_map, _ = etf_maps(symbols)
    max_hold = int(cfg.universe.get("broad_etf", {}).get("max_hold", cfg.strategy.get("max_hold_broad", 2)))

    baseline = _evaluate_scenario("baseline", features, valid_labels, code_map, cfg.strategy, max_hold)
    baseline_targets = {row["date"]: row["target_codes"] for row in baseline.rows}
    results = [baseline]
    for scenario in ["no_risk_overlay", "no_execution_policy", "noisy_scoring"]:
        results.append(
            _evaluate_scenario(
                scenario,
                features,
                valid_labels,
                code_map,
                cfg.strategy,
                max_hold,
                baseline_targets=baseline_targets,
            )
        )

    identifiability = _identifiability(results)
    report = _build_report(labels_path, valid_labels, results, identifiability, data_note=data_note)
    ensure_dir(cfg.reports_dir)
    output = cfg.reports_dir / "counterfactual_report.md"
    output.write_text(report + "\n", encoding="utf-8")
    return output
