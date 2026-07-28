# Strategy Source Attribution Report

本报告只做结构归因分析，不修改策略、不优化收益、不重新回测。

## Structural Feature Vector

| group    | feature                           | present   |   weight | evidence                                                                          |
|:---------|:----------------------------------|:----------|---------:|:----------------------------------------------------------------------------------|
| momentum | lookback = 20                     | yes       |      1   | configs/strategy.yaml lookback_momentum=20                                        |
| momentum | top-k selection = 2               | yes       |      1   | configs/universe.yaml broad_etf.max_hold=2                                        |
| momentum | cross-asset ETF universe          | yes       |      1   | broad ETF asset classes=5                                                         |
| risk     | overheat threshold filter         | yes       |      1.2 | overheat_bias_threshold=12.0; risk_overlay contains OVERHEAT gate                 |
| risk     | PB/QDII gating                    | yes       |      1   | qdii_premium_block=8.0; risk_overlay blocks QDII premium                          |
| risk     | market_signal (star / weak)       | yes       |      1.2 | indicators define STAR/WEAK and risk_overlay suppresses MARKET_SIGNAL_WEAK        |
| behavior | holding inertia (keep_if_rank_le) | yes       |      1.2 | rebalance.keep_if_rank_le=4                                                       |
| behavior | turnover constraint               | yes       |      1   | execution_policy.py contains max_changes = 1                                      |
| behavior | replace threshold gate            | yes       |      1   | replace_only_if_new_score_better_by=3.0                                           |
| output   | daily report style                | yes       |      1.4 | report.py renders source-style daily text and target holdings                     |
| output   | ranking table format              | yes       |      1   | report.py renders ranking rows with PB and feature lists                          |
| output   | status mark encoding              | yes       |      1.2 | selector.py defines three-character recent-holding marks using check/cross glyphs |
| output   | B/S signal system                 | yes       |      1.2 | signals.py emits date-stamped B/S labels and report.py displays them              |

## Template Similarity

| template                                 |   similarity |   matched_weight |   total_weight |
|:-----------------------------------------|-------------:|-----------------:|---------------:|
| A. classic momentum ETF rotation         |        27.78 |              4   |           14.4 |
| B. factor rotation + risk parity hybrid  |        59.72 |              8.6 |           14.4 |
| C. discretionary ETF rotation blog style |       100    |             14.4 |           14.4 |

## Attribution Scores

- similarity_A: 27.78%
- similarity_B: 59.72%
- similarity_C: 100.00%
- final_source_classification: Hybrid
- confidence: 82%

## Required Judgments

1. 是否存在“人为调仓规则痕迹”: yes
2. 是否存在“非公式化阈值”: yes
3. 是否存在“日报驱动行为”: yes
4. 是否存在“风险优先于收益排序”: yes

## Forced Conclusion

- strategy_origin_guess: discretionary ETF rotation blog style with factor/risk-control components
- reasoning:
  - 20-day momentum and top-2 target selection match classic ETF rotation, but they explain only similarity_A=27.78%.
  - Cross-asset ETF universe is present: broad ETF asset classes=5.
  - Risk overlay contains overheat, QDII/PB, and star/weak market-signal gates, supporting similarity_B=59.72%.
  - Holding inertia, max-one-change execution, and replacement threshold create human-like rebalancing behavior.
  - Daily markdown text, PB feature rows, status marks, and B/S labels match discretionary report-driven blog style.
  - Human rebalance trace: yes.
  - Non-formulaic thresholds: yes.
  - Daily-report-driven behavior: yes.
  - Risk priority over raw return ranking: yes.
  - Counterfactual analysis showed structural risk-overlay removal changes outputs more than small score noise, consistent with a rule-plus-heuristic source.
- confidence interval: 74% - 90%

