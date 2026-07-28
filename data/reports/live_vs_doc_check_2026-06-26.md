# Live Market Signal vs DOCX Check - 2026-06-26

本报告只做单日核验：使用当前真实行情缓存生成策略信号，并与 `data/raw/股票策略etf.docx` 解析出的原文结果对比。不修改策略、不优化参数、不重新拟合。

## Inputs

- Market data cache: `data/cache/prices.parquet`
- Market data latest date: `2026-06-26`
- DOCX source: `data/raw/股票策略etf.docx`
- Parsed label file: `data/labels/doc_labels.csv`
- Strategy report: `data/reports/daily_2026-06-26.md`
- Trade sheet: `data/reports/trade_sheet_2026-06-26.csv`
- Layered calibration report: `data/reports/calibration_layered_report.md`

## Single-Day Comparison

| item | value |
|---|---|
| test_date | 2026-06-26 |
| docx_yesterday_holdings | `['日经225', '科创50']` |
| docx_target_holdings | `['日经225', '科创50']` |
| strategy_target_holdings | `['日经225', '创业板50']` |
| frozen_signals | `['日经225', '创业板50']` |
| T+1_execution_date | 2026-06-29 open |
| trade_sheet_action | HOLD 日经225; HOLD 创业板50 |
| turnover_estimate | 0 |
| stability_score | 95.40 |

## Gap

- exact_match: false
- hit_ratio: 50.00%
- matched_holdings: `['日经225']`
- missing_from_strategy: `['科创50']`
- extra_in_strategy: `['创业板50']`
- sleeve_gap: 1 of 2 target sleeves differ

## Attribution

- Layer 1 matched the DOCX target on this date: `['日经225', '科创50']`.
- Layer 2 risk overlay changed the candidate set because `科创50` was flagged `OVERHEAT`.
- Final execution layer kept the stable holding pair `['日经225', '创业板50']`.
- The discrepancy is therefore mainly a risk-overlay interpretation difference, not raw momentum ranking failure.

## June Coverage Summary

For valid broad ETF labels from `2026-06-01` to `2026-06-26`:

- count: 16
- final_exact_match: 56.25%
- exact matched dates: 9
- mismatched dates: 7
- average sleeve-level hit ratio: approximately 78.13%
- mismatched dates: `['2026-06-01', '2026-06-02', '2026-06-03', '2026-06-04', '2026-06-05', '2026-06-22', '2026-06-26']`

## Practical Interpretation

For `2026-06-26`, the system would not tell you to adjust the current model holdings; it would keep `日经225 + 创业板50`. The DOCX source says `日经225 + 科创50`. The operational gap is one 50% sleeve: the system chooses to avoid or not re-enter `科创50` because of risk-overlay handling.
