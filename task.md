# ETF Rotation Rebuild Task Handoff

Updated: 2026-07-28

This file is for the next Codex after cloning the GitHub repo. Read this first, then read `README.md`, `PROJECT_STATUS.md`, `configs/strategy.yaml`, `src/etf_rotation/strategy_pipeline.py`, `src/etf_rotation/execution_policy.py`, and `src/etf_rotation/report.py`.

## Task Goal

We are rebuilding and investigating a personal ETF rotation strategy from a source DOCX plus user-provided July object-strategy examples. The goal is not to create a live trading bot. The goal is to create a deterministic, testable research system that can:

- parse the source strategy document into labels;
- fetch/cache ETF and index daily prices;
- reproduce the source-style daily report;
- compare local signals with source labels;
- explore which parts of the source logic are momentum, risk overlay, holding inertia, or manual/discretionary behavior.

The GitHub upload requested by the user should include the current project data snapshot: raw DOCX, market caches, parsed labels, generated reports, frozen signals, execution locks, and manual label CSVs. Keep only regenerated environment files out of Git: `.venv`, `.env`, Python caches, and test caches.

## Strategy Logic

The current strategy is a three-layer decision system:

1. Layer 1 candidate generation: `selector.py` ranks broad ETFs by recent momentum and score. Key features come from `indicators.py`: recent return, MA20/MA60 trend, bias, trend convexity, star/weak market signal, date-stamped B/S signals, and pseudo NAV.
2. Layer 2 risk overlay: `risk_overlay.py` blocks or warns candidates using QDII premium/PB, overheat bias, weak market signals, and trend gates. Overheated existing holdings can become risk exits instead of being preserved by inertia.
3. Layer 3 execution policy: `execution_policy.py` applies holding inertia, rank/score replacement thresholds, and max-one broad ETF change per day. `strategy_pipeline.py` is the main entrypoint for this layered path.

The broad ETF portfolio holds at most two symbols, normally equal weight. Sector ETFs are observation-only in the first version. LOF arbitrage and micro-cap rotation are not implemented.

The current config has `lookback_momentum: 23`. This came from July ret20 alignment diagnostics: parsed DOCX broad rows matched best with close-price window 23 and previous trading-row context; manual July labels were close to 24. The parameter fit report found a best candidate at 25 but did not justify changing the default because the objective tied the baseline and the evidence is not stable enough.

## What Has Been Completed

- Python package scaffold under `src/etf_rotation`, with a small root package shim so `python -m etf_rotation.cli` works from the project root.
- CLI commands for sample data, real data fetch, daily reports, backtests, DOCX parsing, calibration, counterfactual analysis, source attribution, paper trading, trade sheets, manual execution marking, and execution review.
- Config-driven ETF universe in `configs/universe.yaml`, including broad ETFs, market indexes used for alignment, and observation-only sector ETFs.
- Sample data path works offline through `init-sample`, `--sample` backtests, and `--sample` daily reports.
- Real data cache has worked locally via AKShare/Eastmoney plus a later Sina incremental helper. GitHub will not include cache files.
- DOCX parser works locally for `data/raw/股票策略etf.docx`; parsed outputs are included in the uploaded data snapshot and can also be regenerated.
- Calibration reports compare generated holdings against parsed source labels. Latest local default calibration report showed `exact_match: 55.88%`, `average_hit_ratio: 77.94%` on 34 valid broad dates.
- Layered calibration exists, but the latest local layered result regressed after later ret20/config experiments: `final_exact_match: 44.12%`, while Layer 2 alone reached `58.82%`. This is a signal that execution inertia needs another audit.
- Counterfactual analysis exists. Latest local report concluded the system still looks manual-like / non-deterministic rather than a uniquely identifiable deterministic rule system.
- Source attribution exists. The latest committed/generated report may be stale because it still says lookback 20 even though config is now 23. Rerun it after clone if attribution is needed.
- Real-world execution decision layer exists: frozen signals, T+1 execution plan, stability controls, conflict logging, paper-trade simulation, trade sheet generation, risk notices, execution locks, and manual YES/NO confirmation. It still does not place orders.
- July exploration scripts were added:
  - `scripts/fetch_sina_incremental.py`: fill recent broad ETF prices from Sina via AKShare.
  - `scripts/diagnose_ret20_alignment.py`: test ret20 field/window/date-offset hypotheses against DOCX/manual labels.
  - `scripts/fit_strategy_params.py`: offline grid fit against DOCX labels plus manual July object labels.
  - `scripts/plot_prediction_comparison.py`: compare real ETF moves with distilled-object and local model predictions.

## Uploaded Data Snapshot

At the user's request, the GitHub repository should include the current local data snapshot:

- `data/raw/股票策略etf.docx`: source document.
- `data/cache/prices.parquet`, `data/cache/sample_prices.parquet`, `data/cache/premium.csv`, and cache backups.
- `data/labels/doc_labels.csv`, `data/labels/doc_rows.csv`.
- `data/labels/manual_object_signals_2026-07.csv`, `data/labels/manual_ret20_targets.csv`.
- `data/processed/holding_overrides.csv`, frozen signal JSON, execution locks, and any execution log if present.
- `data/reports/*`: generated markdown/csv/png reports.

The only intentionally ignored files should be regenerated local environment files such as `.venv`, `.env`, `__pycache__`, `.pytest_cache`, `.mypy_cache`, and `.ruff_cache`.

## How To Rebuild After Clone

Use Python 3.10+.

```bash
git clone https://github.com/Kavin52-afk/etf-rotation.git
cd etf-rotation
python -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -r requirements.txt
```

Offline smoke test:

```bash
python -m etf_rotation.cli init-sample
python -m etf_rotation.cli backtest --start 2021-01-01 --end latest --sample
python -m etf_rotation.cli daily --date latest --sample
pytest
```

Real data fetch in PJLab needs proxy:

```bash
source <(curl -sSL http://deploy.i.h.pjlab.org.cn/infra/scripts/setup_proxy.sh)
python -m etf_rotation.cli fetch --start 2021-01-01 --end latest
python scripts/fetch_sina_incremental.py
```

DOCX parsing and calibration:

```bash
# The uploaded repo should already contain 股票策略etf.docx, but this command
# also works after replacing it with a new local copy.
python -m etf_rotation.cli parse-doc --doc data/raw/股票策略etf.docx
python scripts/check_doc_parse_quality.py
python -m etf_rotation.cli calibrate --labels data/labels/doc_labels.csv
python -m etf_rotation.cli calibrate --labels data/labels/doc_labels.csv --mode layered
python -m etf_rotation.cli counterfactual --labels data/labels/doc_labels.csv
python -m etf_rotation.cli source-attribution
```

Daily research workflow:

```bash
python -m etf_rotation.cli daily --date latest
python -m etf_rotation.cli paper-trade --days 30
python -m etf_rotation.cli trade-sheet --date latest
```

Manual execution audit workflow, still no broker integration:

```bash
python -m etf_rotation.cli execute --date latest
python -m etf_rotation.cli review --start 2026-01-01 --end latest
```

## What Is Not Finished

- Reconcile the mismatch between default calibration, layered calibration, and July manual object labels after `lookback_momentum` moved to 23.
- Rerun and update stale reports after the latest config changes, especially `source_attribution_report.md`.
- Decide whether the final ret20 convention should be 23, 24, 25, or a conditional rule. Do not tune to one July day only.
- Audit Layer 3 execution inertia. Current latest layered report says Layer 2 improves matching but Layer 3 hurts May matches; identify whether this is a real source-rule gap or a stale artifact.
- Improve QDII premium/PB data. `data/cache/premium.csv` is optional and local; missing data defaults can distort QDII gates.
- Clarify how market indexes should be used. `market_index` symbols are for alignment/features, not current trade candidates.
- Turn July manual labels into a reproducible fixture or documented private input flow if the user wants them used after GitHub clone.
- Update tests around `lookback_momentum: 23`, layered calibration expectations, Sina incremental behavior, and report distillation paths.
- Do not add broker APIs, automatic order placement, or fill reconciliation unless the user explicitly changes the project scope.

## Good Next Prompt

```text
Continue the ETF rotation project from task.md.
First inspect README.md, PROJECT_STATUS.md, configs/strategy.yaml,
src/etf_rotation/strategy_pipeline.py, src/etf_rotation/execution_policy.py,
and scripts/diagnose_ret20_alignment.py.
Then rerun tests and tell me which calibration path should be investigated next.
```
