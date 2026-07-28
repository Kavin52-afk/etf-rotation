"""Fit strategy parameters against distilled object labels.

This is an offline calibration utility. It optimizes the decision rules against
parsed DOCX labels plus manually supplied object-strategy labels where local
price data is available.
"""

from __future__ import annotations

from copy import deepcopy
from itertools import product
from pathlib import Path
import sys
from typing import Any

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from etf_rotation.backtest import prepare_features  # noqa: E402
from etf_rotation.config import ProjectConfig, load_project_config  # noqa: E402
from etf_rotation.data_provider import load_prices  # noqa: E402
from etf_rotation.metrics import exact_match, hit_ratio  # noqa: E402
from etf_rotation.strategy_pipeline import layer1_targets, layer2_targets, run_strategy_pipeline  # noqa: E402
from etf_rotation.universe import codes_for_names, etf_maps, load_universe, names_for_codes  # noqa: E402
from etf_rotation.utils import ensure_dir, from_pipe_list  # noqa: E402


def _patched_cfg(cfg: ProjectConfig, strategy: dict[str, Any]) -> ProjectConfig:
    return ProjectConfig(
        project_root=cfg.project_root,
        universe=cfg.universe,
        strategy=strategy,
        data=cfg.data,
    )


def _set_nested(strategy: dict[str, Any], dotted_key: str, value: Any) -> None:
    node = strategy
    parts = dotted_key.split(".")
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value


def _strategy_variant(base: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    strategy = deepcopy(base)
    for key, value in params.items():
        _set_nested(strategy, key, value)
    return strategy


def _load_doc_cases(cfg: ProjectConfig) -> list[dict[str, Any]]:
    labels_path = cfg.labels_dir / "doc_labels.csv"
    labels = pd.read_csv(labels_path)
    labels["date"] = pd.to_datetime(labels["date"]).dt.normalize()
    labels = labels[labels.get("broad_valid", True).astype(str).str.lower().isin(["true", "1", "yes"])].copy()
    symbols = load_universe(cfg.universe, pools=["broad_etf"])
    _, name_map = etf_maps(symbols)
    cases: list[dict[str, Any]] = []
    for row in labels.itertuples(index=False):
        expected = codes_for_names(from_pipe_list(row.target_holdings), name_map)
        yesterday = codes_for_names(from_pipe_list(row.yesterday_holdings), name_map)
        if expected:
            cases.append(
                {
                    "source": "docx",
                    "label_date": pd.Timestamp(row.date).normalize(),
                    "signal_date": pd.Timestamp(row.date).normalize(),
                    "yesterday": yesterday,
                    "expected": expected,
                    "expected_buy": set(),
                    "expected_sell": set(),
                }
            )
    return cases


def _load_manual_cases(cfg: ProjectConfig, price_dates: list[pd.Timestamp]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    path = cfg.labels_dir / "manual_object_signals_2026-07.csv"
    if not path.exists():
        return [], []
    frame = pd.read_csv(path).fillna("")
    frame["report_date"] = pd.to_datetime(frame["report_date"]).dt.normalize()
    available = sorted(pd.Timestamp(dt).normalize() for dt in price_dates)
    cases: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for row in frame.itertuples(index=False):
        report_date = pd.Timestamp(row.report_date).normalize()
        cutoff = report_date - pd.Timedelta(days=1)
        possible = [dt for dt in available if dt <= cutoff]
        signal_date = possible[-1] if possible else None
        if signal_date is None or (report_date - signal_date).days > 3:
            skipped.append(
                {
                    "report_date": report_date.strftime("%Y-%m-%d"),
                    "reason": "price data unavailable for report-date context",
                }
            )
            continue
        expected = from_pipe_list(row.target_holdings)
        yesterday = from_pipe_list(row.yesterday_holdings)
        if expected:
            cases.append(
                {
                    "source": "manual",
                    "label_date": report_date,
                    "signal_date": signal_date,
                    "yesterday": yesterday,
                    "expected": expected,
                    "expected_buy": set(from_pipe_list(row.buy_signals)),
                    "expected_sell": set(from_pipe_list(row.sell_signals)),
                }
            )
    return cases, skipped


def _param_grid() -> list[dict[str, Any]]:
    grid = {
        "lookback_momentum": [20, 21, 22, 23, 24, 25],
        "signals.buy_confirmation_days": [0, 1],
        "signals.sell_confirmation_days": [0],
        "score.holding_bonus": [4.0],
        "score.qdii_premium_block": [8.0],
        "score.overheat_bias_threshold": [12.0],
        "rebalance.keep_if_rank_le": [4],
        "rebalance.replace_only_if_new_score_better_by": [3.0],
    }
    keys = list(grid)
    return [dict(zip(keys, values, strict=False)) for values in product(*(grid[key] for key in keys))]


def _feature_cache_key(params: dict[str, Any]) -> tuple[Any, ...]:
    return (
        params["lookback_momentum"],
        params["signals.buy_confirmation_days"],
        params["signals.sell_confirmation_days"],
    )


def _parameter_distance(params: dict[str, Any], reference: dict[str, Any]) -> float:
    """Return a simple normalized distance from a reference parameter set."""
    distance = 0.0
    for key, ref in reference.items():
        value = params.get(key)
        if isinstance(value, (int, float)) and isinstance(ref, (int, float)):
            distance += abs(float(value) - float(ref)) / max(1.0, abs(float(ref)))
        elif value != ref:
            distance += 1.0
    return distance


def _score_variant(
    *,
    params: dict[str, Any],
    strategy: dict[str, Any],
    cfg: ProjectConfig,
    prices: pd.DataFrame,
    cases: list[dict[str, Any]],
    feature_cache: dict[tuple[Any, ...], tuple[pd.DataFrame, dict[str, Any]]],
) -> dict[str, Any]:
    key = _feature_cache_key(params)
    if key not in feature_cache:
        variant_cfg = _patched_cfg(cfg, strategy)
        features, symbols = prepare_features(prices, variant_cfg, pools=["broad_etf"])
        code_map, _ = etf_maps(symbols)
        feature_cache[key] = (features, code_map)
    features, code_map = feature_cache[key]
    max_hold = int(cfg.universe.get("broad_etf", {}).get("max_hold", strategy.get("max_hold_broad", 2)))

    rows: list[dict[str, Any]] = []
    doc_exact = doc_hit = doc_count = 0.0
    manual_target_exact = manual_signal_hit = manual_signal_total = 0.0
    turnover = 0.0
    for case in cases:
        latest_features = features[features["date"].eq(case["signal_date"])].copy()
        if latest_features.empty:
            continue
        pipeline = run_strategy_pipeline(latest_features, case["yesterday"], strategy, max_hold=max_hold)
        final_codes = pipeline.target_holdings
        final_names = names_for_codes(final_codes, code_map)
        expected_names = names_for_codes(case["expected"], code_map)
        exact = exact_match(expected_names, final_names)
        hit = hit_ratio(expected_names, final_names)
        turnover_value = max(
            len(set(final_codes) - set(case["yesterday"])),
            len(set(case["yesterday"]) - set(final_codes)),
        )
        turnover += turnover_value

        signal_rows = latest_features[["code", "latest_signal"]].copy()
        buy_codes = set(signal_rows[signal_rows["latest_signal"].astype(str).str.endswith("_B")]["code"].astype(str))
        sell_codes = set(signal_rows[signal_rows["latest_signal"].astype(str).str.endswith("_S")]["code"].astype(str))
        expected_buy = set(case["expected_buy"])
        expected_sell = set(case["expected_sell"])
        if case["source"] == "docx":
            doc_count += 1
            doc_exact += 1 if exact else 0
            doc_hit += hit
        else:
            manual_target_exact += 1 if exact else 0
            expected_signal_count = len(expected_buy | expected_sell)
            if expected_signal_count:
                manual_signal_total += expected_signal_count
                manual_signal_hit += len(expected_buy & buy_codes) + len(expected_sell & sell_codes)

        rows.append(
            {
                "source": case["source"],
                "label_date": pd.Timestamp(case["label_date"]).strftime("%Y-%m-%d"),
                "signal_date": pd.Timestamp(case["signal_date"]).strftime("%Y-%m-%d"),
                "expected": expected_names,
                "final": final_names,
                "exact": exact,
                "hit_ratio": hit,
                "layer1": names_for_codes(layer1_targets(pipeline.layer1_candidates, max_hold), code_map),
                "layer2": names_for_codes(layer2_targets(pipeline.layer2_candidates, max_hold), code_map),
                "turnover": turnover_value,
                "expected_buy": sorted(expected_buy),
                "actual_buy": sorted(buy_codes),
                "expected_sell": sorted(expected_sell),
                "actual_sell": sorted(sell_codes),
            }
        )

    doc_exact_rate = doc_exact / doc_count if doc_count else 0.0
    doc_hit_rate = doc_hit / doc_count if doc_count else 0.0
    manual_target_rate = manual_target_exact / max(1, sum(1 for case in cases if case["source"] == "manual"))
    manual_signal_rate = manual_signal_hit / manual_signal_total if manual_signal_total else 0.0
    avg_turnover = turnover / max(1, len(rows))
    objective = (
        doc_exact_rate * 1000
        + doc_hit_rate * 200
        + manual_target_rate * 100
        + manual_signal_rate * 80
        - avg_turnover * 20
    )
    return {
        **params,
        "objective": objective,
        "doc_exact_rate": doc_exact_rate,
        "doc_hit_rate": doc_hit_rate,
        "manual_target_rate": manual_target_rate,
        "manual_signal_rate": manual_signal_rate,
        "avg_turnover": avg_turnover,
        "rows": rows,
    }


def _write_report(
    cfg: ProjectConfig,
    baseline: dict[str, Any],
    best: dict[str, Any],
    ranked: list[dict[str, Any]],
    skipped_manual: list[dict[str, Any]],
) -> None:
    ensure_dir(cfg.reports_dir)
    candidate_path = cfg.reports_dir / "strategy_param_fit_candidates.csv"
    public_cols = [
        key
        for key in ranked[0]
        if key
        not in {
            "rows",
        }
    ]
    pd.DataFrame([{key: row[key] for key in public_cols} for row in ranked]).to_csv(candidate_path, index=False)

    detail_path = cfg.reports_dir / "strategy_param_fit_best_detail.csv"
    pd.DataFrame(best["rows"]).to_csv(detail_path, index=False)

    lines = [
        "# Strategy Parameter Fit Report",
        "",
        "Offline supervised fit against parsed DOCX labels plus scoreable manual object labels.",
        "",
        "## Baseline",
        "",
        f"- objective: {baseline['objective']:.4f}",
        f"- doc_exact_rate: {baseline['doc_exact_rate'] * 100:.2f}%",
        f"- doc_hit_rate: {baseline['doc_hit_rate'] * 100:.2f}%",
        f"- manual_target_rate: {baseline['manual_target_rate'] * 100:.2f}%",
        f"- manual_signal_rate: {baseline['manual_signal_rate'] * 100:.2f}%",
        f"- avg_turnover: {baseline['avg_turnover']:.2f}",
        "",
        "## Best",
        "",
        f"- objective: {best['objective']:.4f}",
        f"- doc_exact_rate: {best['doc_exact_rate'] * 100:.2f}%",
        f"- doc_hit_rate: {best['doc_hit_rate'] * 100:.2f}%",
        f"- manual_target_rate: {best['manual_target_rate'] * 100:.2f}%",
        f"- manual_signal_rate: {best['manual_signal_rate'] * 100:.2f}%",
        f"- avg_turnover: {best['avg_turnover']:.2f}",
        "",
        "Best parameters:",
        "",
        "```yaml",
        yaml.safe_dump(
            {
                key: best[key]
                for key in best
                if key
                not in {
                    "objective",
                    "doc_exact_rate",
                    "doc_hit_rate",
                    "manual_target_rate",
                    "manual_signal_rate",
                    "avg_turnover",
                    "parameter_distance",
                    "rows",
                }
            },
            allow_unicode=True,
            sort_keys=False,
        ).strip(),
        "```",
        "",
        "## Manual Labels Not Scored",
        "",
    ]
    if skipped_manual:
        for row in skipped_manual:
            lines.append(f"- {row['report_date']}: {row['reason']}")
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Output Files",
            "",
            f"- candidates: `{candidate_path}`",
            f"- best_detail: `{detail_path}`",
        ]
    )
    (cfg.reports_dir / "strategy_param_fit_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    cfg = load_project_config()
    prices = load_prices(cfg)
    price_dates = sorted(pd.Timestamp(dt).normalize() for dt in prices["date"].drop_duplicates())
    doc_cases = _load_doc_cases(cfg)
    manual_cases, skipped_manual = _load_manual_cases(cfg, price_dates)
    cases = doc_cases + manual_cases

    base_params = {
        "lookback_momentum": cfg.strategy.get("lookback_momentum", 20),
        "signals.buy_confirmation_days": cfg.strategy.get("signals", {}).get("buy_confirmation_days", 0),
        "signals.sell_confirmation_days": cfg.strategy.get("signals", {}).get("sell_confirmation_days", 0),
        "score.holding_bonus": cfg.strategy.get("score", {}).get("holding_bonus", 4.0),
        "score.qdii_premium_block": cfg.strategy.get("score", {}).get("qdii_premium_block", 8.0),
        "score.overheat_bias_threshold": cfg.strategy.get("score", {}).get("overheat_bias_threshold", 12.0),
        "rebalance.keep_if_rank_le": cfg.strategy.get("rebalance", {}).get("keep_if_rank_le", 4),
        "rebalance.replace_only_if_new_score_better_by": cfg.strategy.get("rebalance", {}).get(
            "replace_only_if_new_score_better_by", 3.0
        ),
    }

    feature_cache: dict[tuple[Any, ...], tuple[pd.DataFrame, dict[str, Any]]] = {}
    baseline_strategy = _strategy_variant(cfg.strategy, base_params)
    baseline = _score_variant(
        params=base_params,
        strategy=baseline_strategy,
        cfg=cfg,
        prices=prices,
        cases=cases,
        feature_cache=feature_cache,
    )

    results: list[dict[str, Any]] = []
    for idx, params in enumerate(_param_grid(), start=1):
        strategy = _strategy_variant(cfg.strategy, params)
        scored = _score_variant(
            params=params,
            strategy=strategy,
            cfg=cfg,
            prices=prices,
            cases=cases,
            feature_cache=feature_cache,
        )
        results.append(scored)
        if idx % 50 == 0:
            print(f"scored {idx} variants; best objective={max(item['objective'] for item in results):.4f}", flush=True)

    for row in results + [baseline]:
        row["parameter_distance"] = _parameter_distance(row, base_params)
    ranked = sorted(results + [baseline], key=lambda row: (row["objective"], -row["parameter_distance"]), reverse=True)
    best = ranked[0]
    _write_report(cfg, baseline, best, ranked[:50], skipped_manual)
    print(f"baseline objective={baseline['objective']:.4f}")
    print(f"best objective={best['objective']:.4f}")
    print(f"best doc_exact={best['doc_exact_rate'] * 100:.2f}% doc_hit={best['doc_hit_rate'] * 100:.2f}%")
    print(f"best manual_target={best['manual_target_rate'] * 100:.2f}% manual_signal={best['manual_signal_rate'] * 100:.2f}%")
    print(cfg.reports_dir / "strategy_param_fit_report.md")


if __name__ == "__main__":
    main()
