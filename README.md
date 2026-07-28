# ETF Rotation Rebuild

Research-only rebuild of a personal ETF rotation strategy. The project generates signals, backtests, calibration reports, daily reports, paper-trade plans, and manual trade sheets. It does not connect to a broker and does not place orders.

The current focus is the broad ETF rotation strategy: hold at most two broad ETFs. Sector ETFs are included as an observation pool only. LOF arbitrage and micro-cap rotation are not implemented.

## Repository Contents

```text
configs/                 Strategy, universe, and data paths
src/etf_rotation/         Main package
etf_rotation/             Local shim for python -m etf_rotation.cli
scripts/                 Research and maintenance scripts
tests/                   Pytest suite
data/*/.gitkeep          Empty runtime directories
PROJECT_STATUS.md         Older detailed status log
task.md                  Current handoff for the next Codex
```

At the user's request, this GitHub repo includes the current data snapshot: raw DOCX, price caches, parsed labels, generated reports, frozen signals, execution locks, and manual July labels. It intentionally excludes only regenerated local environment files such as `.venv`, `.env`, Python caches, and test caches.

## Setup

Python 3.10+ is required.

```bash
git clone https://github.com/Kavin52-afk/etf-rotation.git
cd etf-rotation
python -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -r requirements.txt
```

Optional editable install:

```bash
pip install -e .
```

The project also works from the repo root without editable install:

```bash
python -m etf_rotation.cli --help
```

## Offline Smoke Test

Use deterministic sample data first to verify the environment:

```bash
python -m etf_rotation.cli init-sample
python -m etf_rotation.cli backtest --start 2021-01-01 --end latest --sample
python -m etf_rotation.cli daily --date latest --sample
pytest
```

Sample and generated outputs are written under `data/cache/` and `data/reports/`; the current snapshot is committed for continuity.

## Real Data

Real prices are fetched through AKShare/Eastmoney. In the PJLab environment, enable proxy first:

```bash
source <(curl -sSL http://deploy.i.h.pjlab.org.cn/infra/scripts/setup_proxy.sh)
python -m etf_rotation.cli fetch --start 2021-01-01 --end latest
```

The main cache path is:

```text
data/cache/prices.parquet
```

If recent broad ETF rows are missing, try the Sina incremental helper:

```bash
python scripts/fetch_sina_incremental.py
```

Optional QDII premium/PB data can be placed at:

```text
data/cache/premium.csv
```

Accepted columns include `code` plus `premium_pct`, `pb`, or `premium_pb`.

## Source DOCX

The current source document is committed in the data snapshot. To replace it, put a new local copy here:

```text
data/raw/股票策略etf.docx
```

Then parse it:

```bash
python -m etf_rotation.cli parse-doc --doc data/raw/股票策略etf.docx
python scripts/check_doc_parse_quality.py
```

Generated labels:

```text
data/labels/doc_labels.csv
data/labels/doc_rows.csv
data/reports/doc_parse_quality_report.md
```

## Strategy Logic

The broad ETF pipeline is split into three layers:

1. `selector.py`: rank candidates by recent momentum and score.
2. `risk_overlay.py`: apply overheat, weak-signal, trend, and QDII premium/PB gates.
3. `execution_policy.py`: apply holding inertia, replacement threshold, and max-one-change execution control.

`strategy_pipeline.py` is the combined entrypoint. Key parameters live in `configs/strategy.yaml`; the ETF universe lives in `configs/universe.yaml`.

Important current settings:

- `lookback_momentum: 23`
- `max_hold_broad: 2`
- `rebalance.keep_if_rank_le: 4`
- `rebalance.replace_only_if_new_score_better_by: 3.0`
- `score.overheat_bias_threshold: 12.0`
- `score.qdii_premium_block: 8.0`

## Main Commands

Backtest:

```bash
python -m etf_rotation.cli backtest --start 2021-01-01 --end latest
python -m etf_rotation.cli backtest --sample
```

Daily report:

```bash
python -m etf_rotation.cli daily --date latest
python -m etf_rotation.cli daily --date latest --no-execution-stability
python -m etf_rotation.cli daily --date latest --sample
```

Calibration against parsed DOCX labels:

```bash
python -m etf_rotation.cli calibrate --labels data/labels/doc_labels.csv
python -m etf_rotation.cli calibrate --labels data/labels/doc_labels.csv --mode layered
```

Research diagnostics:

```bash
python -m etf_rotation.cli counterfactual --labels data/labels/doc_labels.csv
python -m etf_rotation.cli source-attribution
python scripts/diagnose_ret20_alignment.py
python scripts/fit_strategy_params.py
python scripts/plot_prediction_comparison.py
```

Paper-trade and manual review workflow:

```bash
python -m etf_rotation.cli paper-trade --days 30
python -m etf_rotation.cli trade-sheet --date latest
python -m etf_rotation.cli execute --date latest
python -m etf_rotation.cli review --start 2026-01-01 --end latest
```

`execute` only records a manual YES/NO decision after the user has reviewed the trade sheet. It still does not submit orders.

## Generated Outputs

Typical outputs:

```text
data/reports/backtest_summary.md
data/reports/backtest_nav.csv
data/reports/backtest_trades.csv
data/reports/backtest_positions.csv
data/reports/backtest_plot.png
data/reports/daily_YYYY-MM-DD.md
data/reports/daily_YYYY-MM-DD.csv
data/reports/calibration_report.md
data/reports/calibration_layered_report.md
data/reports/counterfactual_report.md
data/reports/source_attribution_report.md
data/reports/paper_trade_report.md
data/reports/trade_sheet_YYYY-MM-DD.csv
data/reports/risk_notice_YYYY-MM-DD.md
data/processed/frozen_signals/YYYY-MM-DD.json
data/processed/execution_locks/YYYY-MM-DD.json
```

These outputs are runtime artifacts. The current snapshot is committed for continuity, and future runs may update them.

## Tests

```bash
pytest
```

The tests cover config loading, indicators, B/S signals, selection, risk and execution policy, backtesting, DOCX parsing, source attribution, paper-trade execution, trade-sheet workflow, risk disclosure, and logging.

## Safety Notes

- This project is not investment advice.
- There is no live trading, broker API, order placement, or fill reconciliation.
- Backtest results depend on data source, adjusted prices, transaction cost, and rebalance timing.
- QDII premium/PB data is optional and may default to rough values if no cache is provided.
- The source strategy appears to be a hybrid of deterministic rules and discretionary/report-driven behavior; exact reproduction is not guaranteed.

For continuation details, read `task.md`.
