# ETF Rotation Rebuild Project Status

Last updated: 2026-06-28

## Project Path

```text
/mnt/shared-storage-gpfs2/wam-model-gpfs/cuiwenze/experiment/etf_rotation_rebuild
```

## Current State

- Project scaffold is complete.
- `.venv` exists and dependencies are installed.
- `pytest` passes: `29 passed`.
- Synthetic sample data works.
- Real market data fetch works through PJLab proxy setup script and the direct Eastmoney adapter.
- Original DOCX parsing works.
- Default calibration works.
- Layered calibration works.
- Layered risk/execution policy now treats overheat as a risk exit instead of preserving it by inertia.
- Counterfactual strategy uniqueness validation works and writes `data/reports/counterfactual_report.md`.
- Strategy source attribution works and writes `data/reports/source_attribution_report.md`.
- Real-world execution layer works: signal freeze, T+1 execution plan, conflict logging, stability controls, and paper-trade simulation.
- Human-in-the-loop execution workbench works: trade sheet generation, risk notice, execution locks, frozen-signal execution id binding, and manual confirmation workflow.
- No live trading, broker API, or order placement code exists.

## Important Files

```text
data/raw/股票策略etf.docx
data/cache/prices.parquet
data/labels/doc_labels.csv
data/labels/doc_rows.csv
data/reports/doc_parse_quality_report.md
data/reports/backtest_summary.md
data/reports/calibration_report.md
data/reports/calibration_layered_report.md
data/reports/counterfactual_report.md
data/reports/source_attribution_report.md
data/reports/paper_trade_report.md
data/reports/trade_sheet_2026-06-26.csv
data/reports/risk_notice_2026-06-26.md
data/processed/frozen_signals/2026-06-26.json
data/processed/execution_locks/2026-06-26.json
```

## Real Data Cache

```text
data/cache/prices.parquet
```

Latest verified coverage:

- Rows: 46,574
- ETF count: 39
- Date range: 2021-01-04 to 2026-06-26
- Main broad ETF coverage exists for:
  - `513520.SH` 日经225
  - `513100.SH` 纳指
  - `588000.SH` 科创50
  - `159949.SZ` 创业板50
  - `159338.SZ` 中证A500
  - `563300.SH` 中证2000

To fetch again:

```bash
cd /mnt/shared-storage-gpfs2/wam-model-gpfs/cuiwenze/experiment/etf_rotation_rebuild
source .venv/bin/activate
source <(curl -sSL http://deploy.i.h.pjlab.org.cn/infra/scripts/setup_proxy.sh)
python -m etf_rotation.cli fetch --start 2021-01-01 --end latest
```

## DOCX Parsing

Parser module:

```text
src/etf_rotation/parser_docx.py
```

Current parsing results:

- Parsed total dates: 35
- Valid broad ETF dates: 34
- Broad ETF single rows: 510
- `2026-06-10` is correctly marked `broad_valid=false` because broad ETF block says `等待数据更新`.
- Seven required anchor checks pass.

Regenerate labels and quality report:

```bash
python -m etf_rotation.cli parse-doc --doc data/raw/股票策略etf.docx
python scripts/check_doc_parse_quality.py
```

## Default Calibration

Command:

```bash
python -m etf_rotation.cli calibrate --labels data/labels/doc_labels.csv
```

Report:

```text
data/reports/calibration_report.md
```

Latest real-data result:

- Effective broad labels: 34
- exact_match: 47.06%
- average_hit_ratio: 73.53%
- mismatched dates: 18

## Layered Pipeline Refactor

New modules:

```text
src/etf_rotation/risk_overlay.py
src/etf_rotation/execution_policy.py
src/etf_rotation/strategy_pipeline.py
```

Design:

- Layer 1: `selector.py` candidate generator, existing ranking and scoring left unchanged.
- Layer 2: `risk_overlay.py`, rule-based risk permissions.
- Layer 3: `execution_policy.py`, holding inertia and max one broad ETF change per day.
- Total entrypoint: `strategy_pipeline.py`.

Layered calibration command:

```bash
python -m etf_rotation.cli calibrate --labels data/labels/doc_labels.csv --mode layered
```

Report:

```text
data/reports/calibration_layered_report.md
```

Latest layered result:

- layer1_match_rate: 47.06%
- layer2_match_rate: 47.06%
- layer2_filter_effect: 0.00%
- execution_turnover: 0.09
- layer3_execution_effect: 5.88%
- final_exact_match: 52.94%
- layer2 average filtered candidates: 6.27

May mismatch impact:

- 2026-05-12 to 2026-05-31:
  - Layer 1: 28.57%
  - Layer 2: 42.86%
  - Final: 50.00%
  - Layer 2 contribution: +14.29%
  - Layer 3 contribution: +7.14%
- Biggest May mismatch impact: Layer 2 filter.

Interpretation:

The previous strict execution policy preserved overheat old holdings too strongly in May. `risk_overlay.py` now marks overheat rows as `allow_hold=false`, and `execution_policy.py` lets a risk-exit removal receive a qualified replacement without applying the positive score-margin gate against the removed high-score holding.

Remaining mismatches are now mostly candidate-generation / Layer 2 target differences and a few inertia lags, not the May overheat-preservation failure.

## Counterfactual Strategy Uniqueness Validation

Module:

```text
src/etf_rotation/counterfactual_analysis.py
```

Command:

```bash
python -m etf_rotation.cli counterfactual --labels data/labels/doc_labels.csv
```

Report:

```text
data/reports/counterfactual_report.md
```

Latest real-data result:

- baseline exact_match: 52.94%
- baseline hit_ratio: 76.47%
- no risk overlay exact_match: 32.35%
- no execution policy exact_match: 50.00%
- noisy scoring exact_match: 52.94%
- strategy_identifiability_score: 29.12
- small_perturbation_impact: 0.00
- structural_impact: 29.12
- conclusion: B. hybrid rule + heuristic
- confidence: 67%

Interpretation:

The current system is deterministic as code, but the source-document strategy is not uniquely identified as a strict deterministic rule system by these ablations. The small +/-5% ret20 scoring perturbation does not collapse document matching, while structural risk-overlay removal materially changes both matching and holdings. This supports a hybrid rule + heuristic interpretation rather than a uniquely identifiable deterministic rule system.

## Strategy Source Attribution

Module:

```text
src/etf_rotation/source_attribution.py
```

Command:

```bash
python -m etf_rotation.cli source-attribution
```

Report:

```text
data/reports/source_attribution_report.md
```

Latest structural attribution result:

- similarity_A classic momentum ETF rotation: 27.78%
- similarity_B factor rotation + risk parity hybrid: 59.72%
- similarity_C discretionary ETF rotation blog style: 100.00%
- final_source_classification: Hybrid
- confidence: 82%
- confidence interval: 74% - 90%
- strategy_origin_guess: discretionary ETF rotation blog style with factor/risk-control components

Required judgments:

- Human rebalance trace: yes
- Non-formulaic thresholds: yes
- Daily-report-driven behavior: yes
- Risk priority over raw return ranking: yes

Interpretation:

The structure is closest to discretionary ETF rotation blog style, but the factor/risk-control layer is substantial enough to classify the origin as Hybrid rather than pure C. This attribution uses only structural evidence from configs and source modules; it does not run a backtest or optimize returns.

## Real-World Execution Upgrade

New modules:

```text
src/etf_rotation/realworld_execution.py
src/etf_rotation/stability_controller.py
```

Modified modules:

```text
src/etf_rotation/execution_policy.py
src/etf_rotation/metrics.py
src/etf_rotation/report.py
src/etf_rotation/cli.py
```

New commands:

```bash
python -m etf_rotation.cli paper-trade --days 30
python -m etf_rotation.cli daily --date latest
```

Paper-trade report:

```text
data/reports/paper_trade_report.md
```

Latest paper-trade result over 30 recent trading days:

- stability_score_before: 88.51
- stability_score_after: 95.40
- turnover_rate_before: 0.17
- turnover_rate_after: 0.07
- execution_reliability_score: 100.00
- execution_mismatch_rate: 0.00%
- real_world_fidelity_score: 100.00
- ignored unstable signals: 6 rows
- signal conflicts: 2 rows

Daily report now includes:

- recommended holdings
- frozen signals
- T+1 execution plan
- ignored unstable signals
- signal conflicts
- risk warnings
- turnover estimate
- stability score

Latest daily report:

```text
data/reports/daily_2026-06-26.md
```

Latest frozen signal:

```text
data/processed/frozen_signals/2026-06-26.json
```

Real-world usability assessment:

- Meets stable decision-system requirements: yes
- Rationale: signals are frozen per date, execution is planned only for next trading-day open, churn is capped at one broad ETF change per day, unstable 2-day flips are ignored, conflicts are logged with risk priority over execution inertia over ranking, and paper-trade mismatch rate is 0.00%.
- Limitation: this is still a research/paper-trading decision system. It does not connect to a broker, submit orders, verify liquidity/slippage, or reconcile real fills.

## Human-In-The-Loop Execution Workbench

New modules:

```text
src/etf_rotation/execution_workbench.py
src/etf_rotation/risk_disclosure.py
src/etf_rotation/execution_logger.py
```

New commands:

```bash
python -m etf_rotation.cli trade-sheet --date latest
python -m etf_rotation.cli execute --date latest
python -m etf_rotation.cli review --start 2026-01-01 --end latest
```

Generated / managed artifacts:

```text
data/reports/trade_sheet_2026-06-26.csv
data/reports/risk_notice_2026-06-26.md
data/processed/execution_locks/2026-06-26.json
data/processed/execution_log.jsonl  # created after execute YES/NO
```

Latest trade sheet result:

- execution_id: `EXE-2026-06-26-da639b5c2d`
- signal_date: 2026-06-26
- execution_date: 2026-06-29 open
- status: generated
- frozen_signals: `513520.SH`, `159949.SZ`
- orders:
  - HOLD 日经225 `0.50 -> 0.50`, risk_flag=QDII, priority=4
  - HOLD 创业板50 `0.50 -> 0.50`, risk_flag=NORMAL, priority=5
- turnover_estimate: 0

Manual workflow:

1. Generate trade sheet.
2. Review risk notice and trade explanations.
3. Run `execute --date latest`.
4. Type `YES` only after manual broker-side execution, or `NO` to reject the frozen signal.
5. The workflow writes execution status to the lock file and appends an audit row to `data/processed/execution_log.jsonl`.

Safety constraints:

- No automatic order placement.
- No broker API connection.
- No fill reconciliation.
- Same signal date cannot be marked executed twice.
- Frozen signal JSON is bound to an execution id.
- All trade rows include reason, risk flag, priority, and confidence score for manual review.

## Commands To Reproduce Current State

```bash
cd /mnt/shared-storage-gpfs2/wam-model-gpfs/cuiwenze/experiment/etf_rotation_rebuild
source .venv/bin/activate

python -m pytest
python -m etf_rotation.cli parse-doc --doc data/raw/股票策略etf.docx
python scripts/check_doc_parse_quality.py
python -m etf_rotation.cli backtest --start 2021-01-01 --end latest
python -m etf_rotation.cli calibrate --labels data/labels/doc_labels.csv
python -m etf_rotation.cli calibrate --labels data/labels/doc_labels.csv --mode layered
python -m etf_rotation.cli counterfactual --labels data/labels/doc_labels.csv
python -m etf_rotation.cli source-attribution
python -m etf_rotation.cli paper-trade --days 30
python -m etf_rotation.cli daily --date latest
python -m etf_rotation.cli trade-sheet --date latest
# Interactive human confirmation only:
python -m etf_rotation.cli execute --date latest
python -m etf_rotation.cli review --start 2026-01-01 --end latest
```

## Current Constraints

- Do not add broker APIs.
- Do not add live trading.
- Do not place or simulate real orders beyond research backtest records.
- Do not hard-code specific DOCX dates to improve match rate.
- Do not change strategy parameters unless explicitly requested.
- Keep default backtest behavior unchanged unless explicitly asked.

## Good Next Prompt

```text
Continue ETF rotation project from PROJECT_STATUS.md.
First read PROJECT_STATUS.md, data/reports/calibration_layered_report.md,
src/etf_rotation/strategy_pipeline.py, src/etf_rotation/execution_policy.py.
Then help me ...
```
